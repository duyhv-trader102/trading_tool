# universe/ — Coin Universe Selection

Xây dựng **watchlist coin Binance có tiềm năng dài hạn** bằng cách chạy 3-stage pipeline:

```
~440 coins (local parquet)
    → [Stage 1] Pre-screen  : volume / lịch sử / giá
        → [Stage 2] Backtest    : EA V3 signals + compression gate ON
            → [Stage 3] Score       : tiered ranking (Tier 1/2/3/4)
                → watchlist.json
```

---

## Cấu trúc

```
universe/
├── config.py          # Tất cả tham số filter tập trung
├── pre_screener.py    # Stage 1: lọc nhanh trước backtest
├── backtester.py      # Stage 2: wrap EA backtest engine
├── screener.py        # Orchestrate cả pipeline + cache
├── watchlist.py       # I/O + query helpers
├── cli.py             # Entry point CLI
├── cache/
│   ├── pre_screen_results.json
│   └── backtest_results.json   ← cached, skip re-run
└── watchlist.json              ← output chính
```

---

## Quick Start

### Bước 1 — Chạy lần đầu (~2 phút với cache)

```bash
cd python/market_regime_scanner

# Full pipeline
python -m universe.cli screen

# Pre-screen nhanh trước (không backtest)
python -m universe.cli screen --no-backtest

# Force re-run (bỏ cache)
python -m universe.cli screen --force
```

### Bước 2 — Daily scan chỉ scan coin trong watchlist

```bash
python -m markets.daily_scan --universe-only
```

---

## CLI Commands

| Command | Mô tả |
|---|---|
| `screen` | Full pipeline (pre-screen → backtest → score) |
| `screen --no-backtest` | Chỉ pre-screen (nhanh, không có scoring) |
| `screen --force` | Bỏ qua cache, chạy lại từ đầu |
| `report` | In bảng watchlist từ lần chạy trước |
| `list` | List tất cả symbol Tier 1+2+3 |
| `list --tier 1` | Chỉ list Tier 1 |

### Options cho `screen`

```
--min-volume FLOAT    Min avg daily volume USDT (default: 5,000,000)
--min-history INT     Min days of history (default: 365)
--min-pf FLOAT        Min profit factor (default: 1.3)
--min-years FLOAT     Min data years for scoring (default: 1.0)
--output PATH         Override output path
```

---

## Tier System (kế thừa từ EA/shared/market_filter.py)

| Tier | Điểm | Ý nghĩa |
|---|---|---|
| **Tier 1** | ≥ 70 | Elite — full conviction |
| **Tier 2** | ≥ 50 | Strong — normal size |
| **Tier 3** | ≥ 35 | Watch — monitor only |
| **Tier 4** | < 35 | Coins có EA signal nhưng chưa đủ quality — watch only |
| Excluded | — | Không có EA signal, hoặc fail pre-screen |

Scoring gồm 6 chiều: Return/Year (25%) · Profit Factor (25%) · Sharpe (20%) · Win Rate (10%) · Trade Count (10%) · Drawdown (10%)

> **Tier 4** là các coin đã được EA trigger ít nhất 1 lần nhưng PF < 1.3 hoặc composite score < 35. Hữu ích để monitor các coin "borderline" theo thời gian.

---

## Pre-screen Filters (Stage 1)

| Filter | Default | Lý do |
|---|---|---|
| Avg volume ≥ | $5M/ngày | Đủ thanh khoản |
| Listing history ≥ | 365 ngày | Đủ lịch sử |
| Last price ≥ | $0.0001 | Loại dust token |
| Skip list | stablecoins, wrapped | USDC, WBTC, TUSD... |

---

## Backtest Settings (Stage 2)

- **Strategy**: EA Macro Trend Catcher V3
- **Compression gate**: **ON** — bắt buộc, đây là core edge của strategy
- **Direction**: Long-only (crypto spot)
- **SL**: 3× ATR
- **Fee**: 0.1% mỗi chiều
- **Signal rate**: ~0.5-0.8 trade/coin/năm (do compression gate gắt)

---

## Scoring Filters (Stage 3)

| Filter | Default |
|---|---|
| min_trades | **1** (compression gate → rất ít trade by design) |
| min_data_years | 1.0 |
| min_profit_factor | **1.3** |
| max_drawdown | 95% |
| PF cap | 10 (tránh outlier 1-trade distort normalization) |

---

## Cache Behaviour

- Backtest cache: `cache/backtest_results.json`
- Lần sau `screen` tự động dùng cache
- Force re-run: `python -m universe.cli screen --force`
- Pre-screen luôn chạy lại (< 1s)

---

## Tích hợp với daily_scan

```bash
# Scan toàn bộ Binance (cũ)
python -m markets.daily_scan --markets BINANCE

# Scan chỉ watchlist Tier 1+2 (mới)
python -m markets.daily_scan --markets BINANCE --universe-only
```

Nếu `watchlist.json` không tồn tại, `--universe-only` tự fallback về full list.

---

## Python API

```python
from universe.watchlist import get_tradeable_symbols

# Lấy Tier 1+2 (mặc định)
symbols = get_tradeable_symbols()

# Lấy Tier 1 only
symbols = get_tradeable_symbols(tiers=["Tier 1"])

# Lấy cả Tier 4 (watch only)
symbols = get_tradeable_symbols(tiers=["Tier 1", "Tier 2", "Tier 3", "Tier 4"])
```
