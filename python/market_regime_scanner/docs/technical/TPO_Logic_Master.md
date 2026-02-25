# TPO Regime — System Logic Documentation

> Tổng hợp toàn bộ logic phân tích Regime (BALANCE / IMBALANCE) và MBA (Macro Balance Area) từ codebase `market_regime_scanner`.

---

## Mục lục

1. [Tổng quan hệ thống](#1-tổng-quan-hệ-thống)
2. [Distribution Detection — Phát hiện phân phối](#2-distribution-detection--phát-hiện-phân-phối)
3. [Regime Classification — Phân loại BALANCE / IMBALANCE](#3-regime-classification--phân-loại-balance--imbalance)
4. [MBA Detection — Tìm Macro Balance Area](#4-mba-detection--tìm-macro-balance-area)
5. [Distribution Chain — Chuỗi phân phối](#5-distribution-chain--chuỗi-phân-phối)
6. [Readiness Evaluation — Đánh giá sẵn sàng](#6-readiness-evaluation--đánh-giá-sẵn-sàng)
7. [Responsive Participation — Tham gia phản hồi](#7-responsive-participation--tham-gia-phản-hồi)
8. [Data Structures — Cấu trúc dữ liệu](#8-data-structures--cấu-trúc-dữ-liệu)
9. [Pipeline tổng thể](#9-pipeline-tổng-thể)

---

## 1. Tổng quan hệ thống

### Nguyên lý cốt lõi

Thị trường luân chuyển theo chu kỳ:

```
IMBALANCE → BALANCE → IMBALANCE → BALANCE ...
```

- **BALANCE**: Thị trường giao dịch quanh một vùng giá trị (Value Area) → phân phối xong → sẵn sàng cho trend mới.
- **IMBALANCE**: Thị trường di chuyển 1 chiều, tìm kiếm vùng giá trị mới.

### Hai tầng phân tích

| Tầng | Module | Mục đích |
|-------|--------|----------|
| **Session-level** | `analysis/regime/` | Phân loại từng session là BALANCE hay IMBALANCE |
| **Multi-session** | `analysis/mba/` | Tìm MBA — vùng balance lớn (macro) spanning nhiều sessions |

### Top-down flow

```
topdown_observer.py
  ├── get_data() → raw candles
  ├── analyze_from_df() → TPOResult per session
  ├── build_mba_context() → MBAMetadata (MBA + direction + readiness)
  │    ├── find_last_directional_move()
  │    ├── track_mba_evolution()
  │    └── evaluate_mba_readiness()
  └── visualize_tpo_topdown (MBA bands and confluence results)
```

---

## 2. Distribution Detection — Phát hiện phân phối

### 2.1 Ký hiệu Distribution (Market Profile notation)

Đọc profile từ trên xuống dưới:

| Ký hiệu | Ý nghĩa |
|----------|----------|
| **3** | Unfair extreme — vùng single prints / rejection zone |
| **2** | Don't care (body) |
| **1** | Value Area (VA) — vùng giá trị được chấp nhận |

### 2.2 Các loại Distribution

| Loại | Cấu trúc | Ý nghĩa |
|------|-----------|----------|
| **3-1-3** | Unfair high + VA + Unfair low | Distribution hoàn chỉnh — thị trường đã phân phối xong cả 2 phía |
| **3-2-1** | Unfair high + body + VA | Nửa trên — chỉ có rejection ở top (imbalance UP move đã bị reject) |
| **1-2-3** | VA + body + Unfair low | Nửa dưới — chỉ có rejection ở bottom (imbalance DOWN move đã bị reject) |
| **(none)** | Không có unfair extreme | Không có pattern distribution rõ ràng |

### 2.3 Nguồn phát hiện Duy nhất (Source of Truth)

Logic phân loại Distribution hiện đã được hợp nhất vào `core/tpo.py` để đảm bảo tính nhất quán giữa visualization và analysis.

| Thuộc tính | Logic | Vị trí |
|------------|-------|--------|
| **Classification** | Kiểm tra Unfair High/Low và TPO Density Taper | `core/tpo.py` |
| **Is Ready** | `shape == "3-1-3"` và không có minus development | `core/tpo.py` |
| **Composite** | Ghép cặp 3-2-1 và 1-2-3 bổ sung | `analysis/regime/` |

Quy trình phát hiện:
1. Tính toán TPO density taper (>0.65) để xác định rejection ở edges.
2. Kiểm tra Unfair Extremes (Single Prints tại đỉnh/đáy).
3. Hợp nhất thành nhãn: 3-1-3, 3-2-1, 1-2-3 hoặc other.

### 2.4 Composite Distribution

Hai session liền kề với nửa bổ sung tạo thành composite 3-1-3:

```
Session A: 3-2-1  +  Session B: 1-2-3  =  Composite 3-1-3
Session A: 1-2-3  +  Session B: 3-2-1  =  Composite 3-1-3
```

**Điều kiện**:
- Hai nửa **bổ sung** (complementary) — một 3-2-1 và một 1-2-3
- **Không** yêu cầu VA overlap (đã bỏ gate này)
- Tại **regime classifier**: vẫn check VA overlap cho fast-path (`va_overlap_low > va_overlap_high → reject`)
- Tại **MBA chain**: bỏ VA overlap gate — bất kỳ 2 nửa bổ sung nào đều compose

---

## 3. Regime Classification — Phân loại BALANCE / IMBALANCE

Hệ thống sử dụng bộ quy tắc đặc định (Priority-based rules) để phân loại, thay thế cho cơ chế tính điểm (scoring) cũ để tăng độ chính xác và tính minh bạch.

### 3.1 Quy tắc ưu tiên (Priority Rules)

Hệ thống kiểm tra các điều kiện theo thứ tự từ trên xuống dưới. Nếu thỏa mãn một điều kiện, kết quả được trả về ngay lập tức.

| Ưu tiên | Điều kiện (Logic) | Kết quả | Confidence |
| :--- | :--- | :--- | :--- |
| **0** | **Fast-Path**: VA Overlap ≥ 70% | **BALANCE** | 90% |
| **1** | **Fixed Structure**: Session có 3-1-3 distribution (phân phối hoàn chỉnh) HOẶC là `NEUTRAL` session (bidirectional extension). | **BALANCE** | 95% |
| **2** | **High Value Overlap**: VA overlap với session trước đó **> 50%**. | **BALANCE** | 90% |
| **3** | **Responsive Confirmation**: VA overlap thấp nhưng có activity **Responsive Buying** hoặc **Responsive Selling** mạnh. | **BALANCE** | 85% |
| **4** | **Default (Trend)**: Không thỏa mãn các điều kiện trên. | **IMBALANCE** | 80% |

### 3.2 Scoring System (Sub-indicators)

Nếu không rơi vào Fast-Path, hệ thống sử dụng Scoring để đánh giá chi tiết:

#### Balance Indicators (+score)
- **VA Overlap > 40%**: +0.30
- **POC Shift < 30% of range**: +0.25
- **Counter-trend Responsive**: +0.45
- **Both Extremes Rejected**: +0.25

#### Imbalance Indicators (+score)
- **VA Overlap < 40%**: +0.30
- **POC Shift > 30% of range**: +0.25
- **Strong Minus Dev (≥2 zones)**: +0.25
- **VA Expanding**: +0.10

### 3.3 Responsive participation (Tham gia phản hồi)

Responsive activity là chìa khóa để xác định sự từ chối (rejection) tại các cực:
- **Responsive Selling (in uptrend)**: Giá tăng nhưng bị reject tại Unfair High hoặc đóng cửa ngược sâu vào VA.
- **Responsive Buying (in downtrend)**: Giá giảm nhưng bị reject tại Unfair Low hoặc đóng cửa ngược sâu vào VA.
- **Counter-trend**: Nếu VA di chuyển ngược hướng với bối cảnh xu hướng (VD: Trend Up nhưng VA shift Down) -> Một tín hiệu Balance cực mạnh.

### 3.3 Phase Detection

Dựa trên xu hướng VA range qua 5 session gần nhất:

| VA range trend | Phase |
|----------------|-------|
| Contracting (VA[-1] < VA[-2] < VA[-3]) | **late** (compression) |
| Expanding (VA[-1] > VA[-2] > VA[-3]) | **early** |
| Khác | **mid** |

### 3.5 Direction (cho IMBALANCE)

```python
if POC > POC_prev → "bullish"
if POC < POC_prev → "bearish"
# Nếu không có POC_prev:
if profile_shape == "P" → "bullish"
if profile_shape == "b" → "bearish"
```

---

## 4. MBA Detection — Tìm Macro Balance Area

### 4.1 Thuật toán tổng quát

```
find_macro_balance_area(sessions, regimes):
    Step 1: _find_last_imbalance()     → tìm IMBALANCE gần nhất (đi ngược)
    Step 2: _build_distribution_chain() → xây chuỗi distribution
    Step 3: classic fallback            → nếu chain rỗng, dùng mother balance
```

### 4.2 Step 1: Tìm IMBALANCE gần nhất

```python
_find_last_imbalance(regimes, sessions, end):
    # Walk backward from end
    for k in range(end-1, -1, -1):
        if regime[k] == "IMBALANCE" AND session[k+1] != NEUTRAL:
            return (k, direction)
    return None
```

- **Bỏ qua NEUTRAL sessions** — dù regime scorer đánh IMBALANCE, nếu session_type=NEUTRAL thì skip (vì Neutral = bidirectional, không phải true imbalance).

### 4.3 Step 2: Distribution Chain

*(Chi tiết xem Section 5)*

### 4.4 Step 3: Classic Fallback

Nếu distribution chain trả None (không tìm thấy distribution nào):

### 4.4 Phân loại Mother Balance (Anchoring)

Hệ thống ưu tiên tìm kiếm điểm neo (anchor) dựa trên tính bền vững của bối cảnh:

1. **Structural Mother (Ưu tiên)**:
   - Dựa trên profile có phân phối hoàn chỉnh (**3-1-3**) hoặc được ghép từ 2 nửa (**Composite**).
   - Vùng MBA được xác định bằng chính các cạnh rejection (**unfair extremes**) của profile đó.
   - Đây là điểm neo mạnh nhất vì nó đại diện cho một chu kỳ phân phối đã hoàn tất.

2. **Value-based Mother (Fallback)**:
   - Nếu không tìm thấy cấu trúc 3-1-3, hệ thống tìm session `Balance` đầu tiên có sự ổn định về giá trị (Value Area).
   - Vùng MBA được xác định bằng `VAH-VAL` của session đó.

3. **Reset Logic (Chuyển đổi vùng)**:
   - Khi đang ở trong một MBA, nếu xuất hiện một session `Balance` mới nhưng có **Overlap VA < 50%** so với MBA hiện tại -> Hệ thống coi là có sự dịch chuyển (Shift) và sẽ **Reset** để tạo điểm neo MBA mới tại vị trí mới.

---

## 5. Distribution Chain — Chuỗi phân phối

### 5.1 Khái niệm

Distribution chain là chuỗi các **MBA unit** (mỗi unit = 1 distribution 3-1-3, đơn hoặc composite).

```
[IMBALANCE] → [Unit 1: 3-1-3] → [Breakout] → [Unit 2: 3-1-3] → ...
                                                                    ↑
                                                              Current MBA
```

**Current MBA = unit cuối cùng** (mới nhất).

### 5.2 Algorithm chi tiết

```
_build_distribution_chain(sessions, regimes, imb_idx, imb_direction, end):

    scan_start = imb_idx + 1  (hoặc 0 nếu không có IMBALANCE)

    # Session[0] check (đặc biệt — không có regime entry)
    if scan_start == 0:
        label = classify_distribution(sessions[0])
        if "3-1-3" → tạo unit, set area/uf
        if "3-2-1" hoặc "1-2-3" → lưu prev_half (k=-1)

    # Main loop: k = scan_start → end-1
    for k in range(scan_start, end):
        sess = sessions[k + 1]

        # 1. BREAKOUT CHECK
        if uf_h and uf_l exist:
            if sess.high > uf_h → breakout bullish
            if sess.low < uf_l → breakout bearish
            → reset area/uf, update imbalance info
            → check breakout session cho distribution mới
            → continue

        # 2. INNER DISTRIBUTION SKIP
        if uf_h and uf_l exist:
            if sess.high <= uf_h AND sess.low >= uf_l:
                → skip (session nằm hoàn toàn trong MBA)

        # 3. CLASSIFY & PROCESS
        label = classify_distribution(sess)
        _process_dist(label, sess, ...)
```

### 5.3 Breakout Detection

**Breakout** = session's price range phá qua outer edges (unfair extreme boundaries):

```
Breakout bullish: session_high > uf_high (outer edge trên)
Breakout bearish: session_low  < uf_low  (outer edge dưới)
```

Khi breakout xảy ra:
1. Reset area/uf → MBA cũ bị phá
2. Update `last_imb_idx` = k (breakout = structural imbalance mới)
3. Check breakout session cho distribution mới ngay lập tức
4. Chain tiếp tục tìm MBA mới

### 5.4 Inner Distribution Skip

Session nằm **hoàn toàn** trong MBA's uf range → skip (không phải distribution mới, đang ở trong vùng balance).

### 5.5 MBA Area Calculation

#### Single 3-1-3:
```
area_high = unfair_high[0]   (inner edge — cạnh trong của UH)
area_low  = unfair_low[1]    (inner edge — cạnh trong của UL)
uf_high   = unfair_high[1]   (outer edge — breakout level up)
uf_low    = unfair_low[0]    (outer edge — breakout level down)
```

#### Composite 3-1-3:
```
# 3-2-1 side provides upper rejection, 1-2-3 side provides lower rejection
area_high = half_321.unfair_high[0]   (inner edge from 3-2-1 session)
area_low  = half_123.unfair_low[1]    (inner edge from 1-2-3 session)
uf_high   = half_321.unfair_high[1]   (outer edge from 3-2-1 session)
uf_low    = half_123.unfair_low[0]    (outer edge from 1-2-3 session)
```

### 5.6 Half Tracking & Composite Formation

```
prev_half_k = None       # regime index của session half trước
prev_half_shape = None   # "3-2-1" hoặc "1-2-3"

Khi gặp half distribution (3-2-1 hoặc 1-2-3):
  → Thử composite với prev_half:
     if complementary (3-2-1 + 1-2-3 hoặc ngược): → tạo composite unit
     else: ghi đè prev_half = current half

Khi gặp 3-1-3:       → tạo unit đơn, reset prev_half
Khi gặp "" (none):   → reset prev_half
```

### 5.7 Return Logic

```python
if not all_units:
    return None  # → fallback to classic

current = all_units[-1]  # latest unit = current MBA
# Luôn trả về — kể cả sau breakout chưa có unit mới
# (imb_direction cho biết MBA đã bị phá)
```

---

## 6. Readiness Evaluation — Đánh giá sẵn sàng

### 6.1 "Ready for New Beginning" = Sẵn sàng cho trend mới

Trạng thái `READY` đánh giá xem một vùng MBA đã tích lũy đủ để bùng nổ sang xu hướng mới hay chưa.

| # | Tín hiệu | Ready? | Logic |
|---|-----------|--------|--------|
| 1 | **3-1-3 distribution** | ✅ | Session cuối đóng lại với phân phối hoàn chỉnh (3-1-3) và không còn Minus Development. |
| 2 | **Neutral Session** | ✅ | Đã quét thanh khoản cả 2 phía (bidirectional extension) -> Xóa bỏ sự mất cân bằng cục bộ. |
| 3 | **Normal Session** | ✅ | Giai đoạn nén (compression) hẹp, không có extension -> Tích lũy lực cho breakout. |
| 4 | **Normal Variation** | ❌ | Có biên extension meaningful (>20% IB) -> Chưa đủ độ nén (per user request). |
| 5 | **Imbalance** | ❌ | Đang di chuyển mạnh -> Chưa đạt độ chín để breakout bền vững. |

**Reason code:**
- `STRUCTURAL_313`: Phân phối hoàn tất.
- `SWEEP`: Quét thanh khoản hoàn tất (Neutral).
- `COMPRESSION`: Nén giá hoàn tất (Normal).

---

## 7. Responsive Participation — Tham gia phản hồi

### 7.1 Khái niệm

Responsive = market participants **phản hồi** tại các mức giá extreme → tín hiệu Balance.

- Trong **uptrend** → tìm **responsive selling** (người bán phản hồi ở mức cao)
- Trong **downtrend** → tìm **responsive buying** (người mua phản hồi ở mức thấp)

### 7.2 Trend Context & VA Direction

```python
trend_context:
    prior_direction == "bullish"    →  "higher"
    prior_direction == "bearish"    →  "lower"
    fallback: POC > prev_POC       →  "higher"
    fallback: POC < prev_POC       →  "lower"

va_direction:
    va_overlap > 0.2 AND close in prev VA  →  "stable"
    VA shifted up                          →  "higher"
    VA shifted down                        →  "lower"
```

**Counter-trend** = trend_context ≠ va_direction (trend lên nhưng VA shift xuống, hoặc ngược lại) → strong balance signal.

### 7.3 Ba loại Responsive (mỗi phía)

#### Responsive Selling (in uptrend — trend higher):

| Loại | Điều kiện | Score |
|------|-----------|-------|
| **At unfair high** | `has_unfair_high AND close < VAH` (rejected back) | +0.15 |
| **In VA** | Pattern A: `prev_tpo_at_vah > curr_tpo_at_vah` (TPO giảm, activity giảm ở top)<br>Pattern B: `close < prev_close AND close in prev_VA` (close rejected vào VA cũ)<br>Pattern C: `POC shifted down` (POC di chuyển xuống) | +0.20 |
| **Extension** | `ib_ext_up > ib_ext_down` nhưng `close < vah` (mở rộng lên nhưng đóng thấp) | +0.10 |

#### Responsive Buying (in downtrend — trend lower):

| Loại | Điều kiện | Score |
|------|-----------|-------|
| **At unfair low** | `has_unfair_low AND close > VAL` | +0.15 |
| **In VA** | Pattern A: `prev_tpo_at_val > curr_tpo_at_val`<br>Pattern B: `close > prev_close AND close in prev_VA`<br>Pattern C: `POC shifted up` | +0.20 |
| **Extension** | `ib_ext_down > ib_ext_up` nhưng `close > val` | +0.10 |

### 7.4 MIN_VA_OVERLAP_FOR_RESPONSIVE_VA = 0.2

VA overlap phải ≥ 20% mới check responsive_in_VA (nếu VA tách hoàn toàn → không thể nói responsive).

---

## 8. Data Structures — Cấu trúc dữ liệu

### 8.1 DistributionInfo

```python
@dataclass
class DistributionInfo:
    shape: str           # "3-1-3", "3-2-1", "1-2-3", "other"
    is_complete: bool    # shape == "3-1-3"
    has_minus_dev: bool
    ready_to_move: bool  # is_complete AND NOT has_minus_dev
    composite: bool = False  # True nếu là composite từ 2 sessions
    upper_taper: float = 0.0  # mức độ thon ở trên (0-1)
    lower_taper: float = 0.0  # mức độ thon ở dưới (0-1)
```

### 8.2 ResponsiveParticipation

```python
@dataclass
class ResponsiveParticipation:
    responsive_selling_unfair: bool    # selling tại unfair high
    responsive_selling_va: bool        # selling trong VA
    responsive_selling_extension: bool # selling via IB extension
    responsive_buying_unfair: bool     # buying tại unfair low
    responsive_buying_va: bool         # buying trong VA
    responsive_buying_extension: bool  # buying via IB extension
    trend_context: str                 # "higher" / "lower"
    va_direction: str                  # "higher" / "lower" / "stable"
    is_counter_trend: bool             # trend_context != va_direction
```

### 8.3 RegimeFeatures

```python
@dataclass
class RegimeFeatures:
    # POC
    poc, poc_prev, poc_shift, poc_shift_pct
    # VA
    va_high, va_low, va_range, va_overlap_pct, va_expanding
    # Single prints & minus dev
    single_print_count, single_print_pct, minus_dev_count
    # Unfair extremes
    has_unfair_high, has_unfair_low
    # IB
    ib_range, ib_extension_up, ib_extension_down
    # Session info
    day_type, session_range, close_in_va, total_tpo
    close_price, profile_shape
    tpo_above_poc, tpo_below_poc
    # Responsive
    responsive_high, responsive_low, has_range_extension
    responsive_participation: ResponsiveParticipation
    # Distribution
    distribution: DistributionInfo
    # Context
    prior_direction: str  # "bullish" / "bearish" / None
```

### 8.4 RegimeResult

```python
@dataclass
class RegimeResult:
    regime: str          # "BALANCE" / "IMBALANCE"
    confidence: float    # 0.0 - 1.0
    phase: str           # "early" / "mid" / "late"
    direction: str       # "bullish" / "bearish" / None (chỉ cho IMBALANCE)
    control_price: float # POC
    range_high: float    # VAH
    range_low: float     # VAL
    features: RegimeFeatures
    rules_triggered: List[str]
    uncertain_because: str  # None nếu confident
    ready_to_move: bool     # distribution sẵn sàng (3-1-3 + no minus dev)
```

### 8.5 MBAUnit

```python
@dataclass
class MBAUnit:
    area_high: float      # inner edge trên (MBA boundary)
    area_low: float       # inner edge dưới (MBA boundary)
    mother_index: int     # session index tạo ra unit này
    composite: bool       # True nếu từ 2 half sessions
    uf_high: float        # outer edge trên (breakout level up)
    uf_low: float         # outer edge dưới (breakout level down)
```

### 8.6 MacroBalanceArea

```python
@dataclass
class MacroBalanceArea:
    area_high, area_low: float     # MBA boundaries
    source: str                    # "distribution" / "unfair_extremes" / "value_area"
    mother_session: TPOResult
    mother_index: int
    imbalance_session: TPOResult   # IMBALANCE trước MBA
    imbalance_index: int
    imbalance_direction: str       # "bullish" / "bearish"
    all_units: List[MBAUnit]       # mọi unit trong chain (bao gồm cả bị breakout)
```

### 8.7 MBAMetadata

```python
@dataclass
class MBAMetadata:
    mba: MacroBalanceArea          # MBA chính (None = không tìm thấy)
    compression_sessions: List     # sessions nén/quét trong MBA
    compression_count: int
    last_closed_is_compression: bool
    last_closed_session: TPOResult
    last_closed_session_type: SessionType
    ready_for_new_beginning: bool  # sẵn sàng cho trend mới
    ready_reason: str
    direction_signal: DirectionSignal

    # Derived
    has_mba: bool                  # mba is not None
    reversal_alert: bool           # has_mba AND last_closed_is_compression
```

---

## 9. Pipeline tổng thể

### 9.1 Config mặc định

```python
SYMBOLS = ["XAUUSDm", "EURUSDm", "USDJPYm", "BTCUSDm", "GBPJPYm"]
TIMEFRAMES = {
    "Monthly": {"build": "W1",  "session": "MN1"},
    "Weekly":  {"build": "D1",  "session": "W1"},
    "Daily":   {"build": "H4",  "session": "D1"},
}
KEEP_SESSIONS = {"Monthly": 4, "Weekly": 10, "Daily": 10}
ANALYSIS_TARGET_ROWS = 40  # fine block size cho analysis pass
```

### 9.2 Dual-pass Architecture

| Pass | Block size | Mục đích |
|------|-----------|----------|
| **Viz pass** | Coarse (default) | Vẽ chart, hiển thị TPO profile |
| **Analysis pass** | Fine (`ANALYSIS_TARGET_ROWS=40`) | Regime classification + MBA detection |

### 9.3 Ví dụ Flow hoàn chỉnh

```
GBPJPYm Weekly:
  Sessions: [W49, W50, W51, W01, W02, W03, W04, W05, W06, W07, W08]
  
  1. Classify each session → [BAL, BAL, IMB, BAL, BAL, BAL, BAL, BAL, BAL, BAL, ...]
  
  2. find_macro_balance_area():
     a. _find_last_imbalance() → W51 (regime idx 2)
     b. _build_distribution_chain() starting from idx 3:
        - W01: classify_distribution → "3-1-3" → Unit[0]
        - W02: range inside Unit[0]'s uf → skip
        - W03: "1-2-3" → save as prev_half
        - W04: "3-2-1" → complementary with prev_half → COMPOSITE Unit[1]
        - W05: breakout of Unit[1]'s uf_low → reset, new imbalance
        - W06: "3-1-3" → Unit[2] = current MBA
  
  3. MBAMetadata:
     - MBA area: Unit[2]'s area_high / area_low
     - Compression check: inner sessions
     - Ready: check mother + inner sessions
     - Direction: detect from last closed session
```

---

## Diagram tổng quát

```
Session TPOResults
       │
       ▼
┌─────────────────────────────┐
│ find_last_directional_move()│  ← find imbalance origin
│  ├── _find_last_imbalance() │
│  ├── _build_distribution_   │
│  │   chain()                │
│  │   ├── classify_dist()    │  ← single source of truth
│  │   ├── breakout detect    │
│  │   ├── composite merge    │
│  │   └── inner skip         │
│  └── classic fallback       │
└─────────┬───────────────────┘
          │ DirectionalMoveResult
          ▼
┌─────────────────────────────┐
│ track_mba_evolution()       │  ← multi-session MBA chain
│  ├── compute MBA units      │
│  └── detect_mba_break()     │
└─────────┬───────────────────┘
          │ MBAEvolution
          ▼
┌─────────────────────────────┐
│ evaluate_mba_readiness()    │
│  ├── compression scan       │
│  └── _evaluate_ready()      │
└─────────┬───────────────────┘
          │ MBAReadiness
          ▼
┌─────────────────────────────┐
│ build_mba_context()         │  ← bridge wrapper
│  packs all above into       │
│  MBAMetadata                │
└─────────┬───────────────────┘
          │ MBAMetadata
          ▼
     Scanner output / 
     Visualization
```

---

*Tài liệu này tổng hợp từ source code tại thời điểm tạo. Khi logic thay đổi, cần cập nhật tương ứng.*
