# Thuật toán Đồng thuận Hội tụ (Convergence Consensus)

## Triết lý: Dĩ bất biến ứng vạn biến

> **Dùng cái không đổi để ứng phó với mọi thứ thay đổi.**

Cái bất biến ở đây là:

> **Thị trường chỉ có 2 phe: mua hoặc bán. Phân phối TPO là vật lý — bất biến với cách đo.**

Vì chỉ có 2 phe, phân phối TPO trong một session có dominant side bắt buộc phải lệch về 1 phía — không thể lồi lõm ngẫu nhiên vì lực cung cầu là liên tục, không phải random. Gradient này tồn tại độc lập với block_size. Thay đổi block_size chỉ thay đổi độ phân giải của representation — giống như zoom ảnh, càng zoom càng rõ, không bao giờ zoom vào cái cốc lại thấy quả bóng.

Từ axiom đơn giản này, toàn bộ thuật toán được derive ra — không cần assumption thêm, không cần magic number, không cần hardcode.

---

## Tại sao phải dùng Block, không phải Tick

Block là **đơn vị ngữ nghĩa tối thiểu** của Market Profile. Mọi khái niệm phân tích đều được định nghĩa trên block:

```
POC               = block có nhiều TPO nhất
Minus development = block chỉ có 1 TPO (single print)
Unfair extreme    = block ở rìa bị reject
Single print      = block không overlap với session khác
```

Nếu dùng tick-level thì không thể định nghĩa được các khái niệm này — "minus development = 1 tick missing" hoàn toàn vô nghĩa. Tick là raw data, không phải ngôn ngữ phân tích.

**Đánh đổi có chủ đích:**
```
Tick-level: chính xác tuyệt đối
→ Nhưng không thể mô hình hóa minus development,
  unfair extreme, single print...

Block-level: có sai số nhỏ
→ Nhưng toàn bộ pipeline phân tích consistent,
  đơn giản, và có thể mô hình hóa được
```

Thuật toán này đảm bảo block_size đủ nhỏ để sai số tối thiểu — không cần tick-level perfect.

---

## Tại sao thuật toán này tồn tại

Vấn đề chỉ xảy ra khi **buy và sell gần cân bằng**. Lúc này POC và TPO count rất nhạy với block boundary — dịch 1 tick là đổi chiều hoàn toàn. Đây là case khó nhất vì:

- Nhìn từ ngoài: session trông như sideway bình thường
- Bên trong: một phe đang tích lũy âm thầm, tạo năng lượng cho breakout
- Dùng block_size sai → không phân biệt được ai đang thắng

**2 việc cần làm:**
```
1. Detect: session có đang gần cân bằng không?
2. Tìm: điểm làm mất cân bằng ở đâu?
   → target_rows mà tại đó boundary effect < signal thật
   → BUY/SELL bắt đầu tách ra rõ ràng
```

Mục tiêu: **detect accumulation direction trong compression session để anticipate hướng breakout tiếp theo.**

---

## Quan trọng: Chỉ đánh giá nội tại của session

Thuật toán này hoạt động **hoàn toàn trên nội tại của từng session riêng lẻ** — không so sánh cross-session, không dùng thông tin từ session khác. Mỗi session được calibrate độc lập dựa trên chính phân phối TPO của nó.

Đây là điều kiện bắt buộc vì accumulation direction là tính chất nội tại — nó nằm trong phân phối tick data của session đó, không phải trong mối quan hệ với session khác.

---

## Case thực tế: Vấn đề gặp phải

```
AUDCADm | READY (BULLISH) | BREAKOUT | BULLISH | IN BALANCE | BULLISH
W:READY(Bull) [3-1-3_ready] @2026-02-09

[Weekly] 3 sessions
  2026-02-02  NORMAL_VARIATION 3-1-3  POC=4860  VA=4740-4960
  2026-02-09  NEUTRAL 3-1-3  POC=5020  VA=4970-5080
  2026-02-16  NORMAL 1-2-3  POC=4960  VA=4900-5010
```

Root cause:
```
Scanner:  target_rows = 40 (hardcode) → POC = X   → BULLISH
Observer: target_rows = 50 (hardcode) → POC = X+1 → BEARISH
```

Cùng data, cùng session, 2 kết luận ngược nhau chỉ vì 2 con số arbitrary khác nhau 10 đơn vị. Với FX range hẹp, chỉ cần 1-2 tick là POC nhảy vị trí — tín hiệu đảo chiều hoàn toàn.

Sau khi có thuật toán này, cả Scanner lẫn Observer đều gọi chung `find_target_rows(session)` → cùng ra 1 giá trị → không bao giờ mâu thuẫn nhau nữa.

---

## Bối cảnh áp dụng

Thuật toán không chạy liên tục cho mọi phiên. Nó được kích hoạt tại một thời điểm cụ thể trong workflow:

- **Thời điểm kích hoạt**: Ngay sau khi đã xác định được Last Imbalance Session.
- **Mục tiêu**: Phân tích các phiên Balance tiếp theo để xác định liệu đây là Balance thực thụ hay Compression session có dominant side ẩn bên trong.
- **Vai trò**: Bộ lọc cuối cùng loại bỏ false signal do gán nhầm target_rows, giúp xác định Market Regime một cách bền vững.

Việc giới hạn phạm vi phân tích từ Last Imbalance trở đi giúp thu hẹp đáng kể số phiên cần xử lý, làm cho linear scan từng bước +1 hoàn toàn khả thi về mặt tính toán.

---

## Vấn đề cốt lõi: Noise Zone ở mức thô

Trái với trực giác, mức target_rows thấp (thô) không phải là anchor ổn định — đây thực chất là vùng nhiễu cao nhất.

Ở block_size lớn, ranh giới của mỗi block có thể gom hoặc tách các cụm tick theo cách tùy tiện:

```
target_rows = 10 → BUY
target_rows = 11 → SELL
target_rows = 12 → SELL
target_rows = 13 → BUY
...
target_rows = 26 → BUY
target_rows = 27 → BUY
target_rows = 28 → BUY  ← signal thật lộ diện, dừng ở đây
```

Trong Noise Zone, thị trường không thay đổi — chỉ là cách gộp ticks đang tạo ra ảo giác flip. Một khi signal thật xuất hiện và giữ nguyên N=3 consecutive, đó là phân phối vật lý đã lộ diện — zoom thêm chỉ làm rõ hơn, không đổi chiều. Đây là hệ quả trực tiếp từ axiom "chỉ có 2 phe".

---

## Tham số cấu hình

Default level là mức "dễ nhìn" cho từng loại session — đủ rõ để thấy structure, không quá chi tiết. Cấu hình trong config.py:

```
Monthly (dùng bar W1): default_rows = 25
Weekly  (dùng bar D1): default_rows = 25
Daily   (dùng bar H4): default_rows = 20
```

```
N = 3
max_target_rows = min(100, (session_high - session_low) / tick_size)
```

Scan bắt đầu từ **default_rows**, không phải từ 10 — vì từ 10 đến default là vùng quá thô, không có ý nghĩa phân tích với TF lớn dùng bar W1/D1/H4.

---

## Cách thức hoạt động

### Bước 1: Tính baseline tại default_rows

```
Buying TPO   = số blocks phía dưới POC (exclude single prints)
Selling TPO  = số blocks phía trên POC (exclude single prints)
baseline_dir = BUY nếu Buying > Selling, ngược lại SELL
```

### Bước 2: Scan từ default_rows + 1 → max_target_rows

Tăng dần +1. Ở mỗi level:

```
Buying == Selling  → skip (tie, boundary artifact), tiếp tục
Buying > Selling   → direction = BUY
Buying < Selling   → direction = SELL
```

Tie không cắt streak — granularity chưa đủ để phân biệt, zoom thêm tự vỡ ra.
Streak bị reset chỉ khi direction flip.

### Bước 3: Tìm điểm gradient thay đổi

**Tìm được N=3 consecutive với direction KHÁC baseline_dir:**
```
→ Dừng ngay
→ Output = level thứ 3 của streak
→ Direction = direction mới (khác baseline)
```

Baseline tại default_rows là artifact của block thô. Direction mới mới là thực tế — vì phân phối vật lý đã lộ diện, zoom thêm chỉ làm rõ hơn, không đổi chiều.

**Không tìm được N=3 flip đến max_target_rows:**
```
→ Output = default_rows
→ Direction = baseline_dir
```

Gradient ổn định từ default — không có cân bằng nhập nhằng, baseline là thực tế.

**Flip liên tục đến max_target_rows, không có N=3 consecutive:**
```
→ Output = UNSTABLE
```

Session không có dominant side thật sự — Balance thực thụ, không phải Compression.

---

## Ví dụ minh họa

**Gradient ổn định từ default:**
```
default = 20, baseline = BUY
21-100: BUY liên tục (không flip)
→ Output = default_rows = 20, direction = BULLISH
```

**Gradient thay đổi sau default — case quan trọng nhất:**
```
default = 20, baseline = BUY
21-45: BUY
46: SELL
47: SELL
48: SELL ← N=3 confirm
→ Output = 48, direction = BEARISH
→ Baseline BUY tại 20 là artifact của block thô
→ BEARISH mới là thực tế nội tại của session
```

**UNSTABLE — Balance thực thụ:**
```
default = 20
20-100: flip liên tục, không có N=3 consecutive
→ Output = UNSTABLE
→ Không có dominant side, không đưa ra tín hiệu
```

---

## Đầu ra

| Output | Ý nghĩa |
|---|---|
| `target_rows` | default_rows hoặc level confirm thứ 3 khi flip |
| `direction` | `BUY` hoặc `SELL` — accumulation direction nội tại của session |
| `stable_start` | Level đầu tiên của streak — điểm gãy thật |
| `UNSTABLE` | Không tìm được N=3 → Balance thực thụ |

`stable_start` cho biết độ mạnh của signal: xuất hiện càng sớm → accumulation càng rõ → breakout càng gần.

---

## Tác động lên toàn bộ hệ thống

Trước đây:
```
Scanner:  target_rows = 40 (hardcode) → BULLISH
Observer: target_rows = 50 (hardcode) → BEARISH
→ Mâu thuẫn nội tại, không thể tin cậy
```

Sau khi có thuật toán này:
```
Scanner:  find_target_rows(session) → target_rows = 48, BEARISH
Observer: find_target_rows(session) → target_rows = 48, BEARISH
→ Nhất quán hoàn toàn, deterministic
```

Mọi analytical step phía sau (TPO count, minus development, unfair high/low, overlap, breakout detection) đều inherit độ chính xác từ bước calibration này.

---

## TPO Profile — Thay đổi cần implement trong tpo.py

### 1. TPOResult dataclass

Thêm field `target_rows: int = 0` vào sau `block_size: float = 0.0`.

Field này lưu lại target_rows đã được dùng để tính profile của session đó.
Mặc định = 0 nghĩa là chưa qua Convergence algorithm (dùng default từ config).

### 2. analyze_session

Thêm `target_rows = 0` vào TPOResult constructor (sau `block_size = self.tick_size`).

### 3. analyze_dynamic

Sau khi gọi `analyze_session`, gán `result.target_rows = target_rows` trước khi append vào results.

**Lý do:** target_rows là tham số truyền vào nhưng không được lưu lại trong result. Khi Convergence algorithm chạy, nó cần biết target_rows nào đã được dùng để đánh giá tpo_counts_up vs tpo_counts_down — vì đây là thông tin nội tại của session, không thể suy ngược lại từ block_size do calc_block_size có rounding (nhiều target_rows khác nhau có thể cho cùng block_size).

---

## Hướng tối ưu về sau

Hiện tại default_rows được hardcode theo kinh nghiệm. Về lâu dài, sau khi có đủ data thực tế từ việc chạy thuật toán, có thể backtest để tìm pattern giữa session characteristics (TF, số bars, price range, tick_size) và target_rows tối ưu → derive công thức tính trực tiếp thay vì duyệt.
