# Pipeline Workflow — Từ Backtest đến Signal Tracking

> Last Updated: 2026-02-23

Luồng vận hành đầy đủ của hệ thống, từ backtest đến theo dõi tín hiệu hàng ngày.

---

## Tổng quan Pipeline

```
┌──────────────────────────────────────────────────────────────────────┐
│  Stage 1 — BACKTEST (chạy lại khi thay đổi logic EA/alignment)     │
│  python -m EA.macro_trend_catcher.backtest                         │
│  → reports/*.json, *.csv, *.txt                                    │
└─────────────────────────┬────────────────────────────────────────────┘
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Stage 2 — UNIVERSE SCREENING (chạy lại khi backtest results đổi)  │
│  python -m universe.cli screen                                     │
│  → universe/watchlist.json (Tier 1/2/3/4)                          │
└─────────────────────────┬────────────────────────────────────────────┘
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Stage 3 — DAILY SCAN (chạy mỗi ngày)                             │
│  python -m markets.daily_scan --universe-only                      │
│  → markets/logs/YYYY-MM-DD.csv + markets/output/daily/*/           │
└─────────────────────────┬────────────────────────────────────────────┘
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Stage 4 — SIGNAL TRACKER (chạy sau daily scan)                    │
│  python markets/pnl_tracker.py                                     │
│  → markets/logs/tracker/ + markets/output/signal_tracker.html      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Stage 1 — Backtest

Chạy backtest trên toàn bộ universe để đánh giá hiệu suất EA.

### MT5 (FX + Commodities)

```bash
cd D:\code\trading_tool\python\market_regime_scanner

# FX + Commodities, 2 năm, soft SL, signal v3, long + short
python -m EA.macro_trend_catcher.backtest \
    --market mt5 \
    --groups FOREX_MAJORS FOREX_CROSSES COMMODITIES \
    --min-years 2 --soft-sl --signal-version v3
```

### Binance (Crypto)

```bash
# Binance LONG-ONLY, 2 năm, soft SL, signal v3
python -m EA.macro_trend_catcher.backtest \
    --market binance --min-years 2 --soft-sl --signal-version v3
```

### Tham số quan trọng

| Flag | Mô tả | Default |
|------|--------|---------|
| `--market` | `binance` (LONG-ONLY) hoặc `mt5` (LONG+SHORT) | `binance` |
| `--groups` | MT5 groups: `FOREX_MAJORS`, `FOREX_CROSSES`, `COMMODITIES`, `US_INDICES`, `CRYPTO` | FX+COMM |
| `--min-years` | Minimum years of data | `3.0` |
| `--soft-sl` | Không dùng hard SL, exit chỉ khi Monthly flip | OFF |
| `--signal-version` | `v2` (balance-only) hoặc `v3` (unified: balance + breakout) | `v2` |
| `--symbols` | Chạy symbol cụ thể: `--symbols XAUUSDm AUDJPYm` | all |
| `--cooldown` | Ngày nghỉ sau khi SL hit | `20` |
| `--sl-mult` | SL = N × ATR | per-asset |
| `--btc-filter` | Skip LONG khi BTC Monthly bearish | OFF |

### Output files

```
EA/macro_trend_catcher/reports/
├── mt5_v21_trade_log_v3_softsl.csv          ← MT5 trade log
├── mt5_v21_trade_log_v3_softsl.json
├── mt5_v21_backtest_results_v3_softsl.json  ← per-symbol results (input cho universe)
├── mt5_v21_summary_report_v3_softsl.txt     ← human-readable summary
├── v21_trade_log_v3_softsl.csv              ← Binance trade log
├── v21_trade_log_v3_softsl.json
├── v21_backtest_results_v3_softsl.json
├── v21_summary_report_v3_softsl.txt
├── spot_v21_ranked_top50.csv                ← top 50 symbols ranked
├── spot_v21_ranked_top50.json
└── spot_v21_watchlist.json                  ← tiered watchlist (market filter)
```

---

## Stage 2 — Universe Screening

Lọc từ ~440 coins Binance → watchlist chất lượng cao (dùng cho daily scan).

```bash
# Full pipeline: pre-screen → backtest → score → watchlist.json
python -m universe.cli screen

# Pre-screen only (nhanh, không backtest)
python -m universe.cli screen --no-backtest

# Force re-run, bỏ qua cache
python -m universe.cli screen --force

# Xem report từ lần chạy trước
python -m universe.cli report

# List symbol Tier 1 only
python -m universe.cli list --tier 1
```

### Pipeline chi tiết

```
441 coins (local parquet)
    → [Stage 1] Pre-screen: volume ≥ 5M USDT/day, history ≥ 365 days
        → ~173 coins passed
    → [Stage 2] Backtest: EA V3 signals + compression gate
        → ~177 coins ran (including cached)
    → [Stage 3] Score: tiered ranking (PF, WR, DD, Sharpe)
        → 29 coins: 10 Tier 1, 9 Tier 2, 10 Tier 3
            → universe/watchlist.json
```

### Output & Cache files

```
universe/
├── watchlist.json                     ← OUTPUT CHÍNH — daily scan dùng file này
└── cache/
    ├── pre_screen_results.json        ← cache stage 1 (skip re-screen)
    ├── backtest_results.json          ← cache stage 2 (skip re-backtest)
    └── screen_run.log                 ← log lần chạy cuối
```

---

## Stage 3 — Daily Scan

Scan hàng ngày trên các market đã chọn, tìm tín hiệu READY.

```bash
# Scan tất cả markets (FX, COMM, BINANCE full)
python -m markets.daily_scan

# Scan FX + COMM + BINANCE từ watchlist (recommended)
python -m markets.daily_scan --universe-only

# Chỉ scan FX + COMM
python -m markets.daily_scan --markets FX COMM

# Scan không tự mở browser
python -m markets.daily_scan --no-open
```

### Output files

```
markets/
├── logs/
│   ├── 2026-02-23.csv                 ← signal log (mỗi ngày 1 file)
│   ├── 2026-02-22.csv
│   └── ...
└── output/
    └── daily/
        └── 2026-02-23/
            ├── fx/                    ← per-market output
            │   ├── dashboard.html
            │   └── topdown_*.html
            ├── comm/
            ├── binance/
            └── combined_dashboard.html
```

---

## Stage 4 — Signal Tracker (PnL)

Theo dõi tín hiệu READY đã phát, tracking regime changes, tự đóng trade khi Monthly flip.

```bash
# Chạy tracker (so sánh ngày mới nhất vs snapshot trước)
python markets/pnl_tracker.py

# Hoặc chạy như module
python -m markets.pnl_tracker
```

### Output files

```
markets/
├── logs/
│   └── tracker/
│       ├── 2026-02-23.csv             ← daily snapshot (regime state)
│       ├── 2026-02-22.csv
│       └── trade_history.csv          ← persistent trade log (tất cả closed trades)
└── output/
    ├── signal_tracker.html             ← PnL dashboard
    └── pnl_dashboard.html              ← older dashboard format
```

---

## Khi nào cần Reset?

### Scenario 1: Thay đổi logic EA / alignment (breakout rules, readiness, etc.)

**Cần chạy lại toàn bộ pipeline:**

```bash
# 1. Xóa backtest reports cũ (optional, sẽ bị overwrite)
# 2. Chạy lại backtest
python -m EA.macro_trend_catcher.backtest --market mt5 --groups FOREX_MAJORS FOREX_CROSSES COMMODITIES --min-years 2 --soft-sl --signal-version v3
python -m EA.macro_trend_catcher.backtest --market binance --min-years 2 --soft-sl --signal-version v3

# 3. Reset universe cache + re-screen
python -m universe.cli screen --force

# 4. Daily scan sẽ dùng watchlist mới
python -m markets.daily_scan --universe-only
```

**Xóa gì:**
| File/Folder | Lý do | Bắt buộc xóa? |
|-------------|--------|----------------|
| `EA/macro_trend_catcher/reports/*` | Kết quả backtest cũ | Không (bị overwrite) |
| `universe/cache/*.json` | Cache backtest + pre-screen cũ | **Có**, hoặc dùng `--force` |
| `universe/watchlist.json` | Watchlist dựa trên logic cũ | **Có** (tự sinh lại) |

---

### Scenario 2: Chỉ update data (download data mới, không đổi logic)

```bash
# 1. Re-screen universe (backtest lại trên data mới)
python -m universe.cli screen --force

# 2. Daily scan bình thường
python -m markets.daily_scan --universe-only
```

**Xóa gì:**
| File/Folder | Bắt buộc xóa? |
|-------------|----------------|
| `universe/cache/*.json` | **Có**, hoặc `--force` |
| Signal logs (`markets/logs/*.csv`) | Không |
| Tracker snapshots (`markets/logs/tracker/`) | Không |

---

### Scenario 3: Reset signal tracker (bắt đầu tracking lại từ đầu)

Khi muốn xóa toàn bộ lịch sử tín hiệu và trade history:

```powershell
# Xóa tất cả signal logs
Remove-Item markets/logs/*.csv
Remove-Item markets/logs/*.json

# Xóa tracker snapshots + trade history
Remove-Item markets/logs/tracker/*.csv

# Xóa dashboard output
Remove-Item markets/output/signal_tracker.html
Remove-Item markets/output/pnl_dashboard.html
```

**Xóa gì:**
| File/Folder | Mô tả | Bắt buộc xóa? |
|-------------|--------|----------------|
| `markets/logs/YYYY-MM-DD.csv` | Signal logs hàng ngày | **Có** |
| `markets/logs/tracker/YYYY-MM-DD.csv` | Daily regime snapshots | **Có** |
| `markets/logs/tracker/trade_history.csv` | Persistent trade log | **Có** |
| `markets/output/signal_tracker.html` | Dashboard output | Không (bị overwrite) |

---

### Scenario 4: Reset chỉ 1 ngày signal log bị lỗi / stale

```powershell
# Xóa signal log ngày cụ thể
Remove-Item markets/logs/2026-02-23.csv

# Chạy lại daily scan
python -m markets.daily_scan --universe-only
```

---

### Scenario 5: Full factory reset (toàn bộ hệ thống)

```powershell
cd D:\code\trading_tool\python\market_regime_scanner

# 1. EA reports
Remove-Item EA/macro_trend_catcher/reports/*.csv
Remove-Item EA/macro_trend_catcher/reports/*.json
Remove-Item EA/macro_trend_catcher/reports/*.txt

# 2. Universe cache + watchlist
Remove-Item universe/cache/*.json
Remove-Item universe/cache/*.log
Remove-Item universe/watchlist.json

# 3. Signal logs + tracker
Remove-Item markets/logs/*.csv
Remove-Item markets/logs/*.json
Remove-Item markets/logs/tracker/*.csv

# 4. Dashboard output
Remove-Item -Recurse markets/output/daily/*
Remove-Item markets/output/*.html

# 5. Chạy lại pipeline từ đầu
python -m EA.macro_trend_catcher.backtest --market mt5 --groups FOREX_MAJORS FOREX_CROSSES COMMODITIES --min-years 2 --soft-sl --signal-version v3
python -m EA.macro_trend_catcher.backtest --market binance --min-years 2 --soft-sl --signal-version v3
python -m universe.cli screen --force
python -m markets.daily_scan --universe-only
python markets/pnl_tracker.py
```

---

## Tham chiếu nhanh — File Map

```
EA/macro_trend_catcher/
├── backtest.py                ← Stage 1 entry point
├── config.py                  ← Asset configs, symbol lists
├── signals.py                 ← Signal generation logic
└── reports/                   ← Backtest output (CSV, JSON, TXT)

universe/
├── cli.py                     ← Stage 2 entry point
├── config.py                  ← Filter thresholds
├── pre_screener.py            ← Volume/history filter
├── backtester.py              ← Wrap EA backtest
├── screener.py                ← Orchestrator
├── watchlist.py               ← I/O helpers
├── watchlist.json             ← ★ Output chính
└── cache/                     ← Cached results (xóa khi cần re-run)

markets/
├── daily_scan.py              ← Stage 3 entry point
├── pnl_tracker.py             ← Stage 4 entry point
├── manager.py                 ← Scan orchestrator
├── cli.py                     ← Single-market CLI
├── reporting.py               ← HTML generation
├── logs/
│   ├── YYYY-MM-DD.csv         ← Daily signal log
│   └── tracker/
│       ├── YYYY-MM-DD.csv     ← Regime snapshots
│       └── trade_history.csv  ← Persistent trades
└── output/
    ├── daily/YYYY-MM-DD/      ← HTML dashboards
    └── signal_tracker.html    ← PnL dashboard

analytic/tpo_mba/
├── alignment.py               ← build_tf_regime(), evaluate_overall_signal()
└── tracker.py                 ← build_mba_context(), evaluate_session_readiness()
```

---

## FAQ

**Q: Thay đổi alignment.py thì ảnh hưởng gì?**  
A: Ảnh hưởng trực tiếp đến signal detection. Cần chạy lại **toàn bộ pipeline** (Scenario 1).

**Q: Universe screening chạy lâu bao lâu?**  
A: ~2 phút nếu có cache, ~30 phút nếu `--force` (phải chạy lại backtest 440 coins).

**Q: Daily scan không dùng `--universe-only` thì sao?**  
A: Scan toàn bộ ~261 Binance coins thay vì ~29 từ watchlist. Lâu hơn và nhiều noise hơn.

**Q: Signal tracker tự detect trade khi nào?**  
A: Khi Monthly direction flip so với snapshot trước → tự close trade và ghi vào `trade_history.csv`.

**Q: Có cần chạy backtest lại khi data mới?**  
A: Khuyến nghị chạy lại universe screening (`--force`) để cập nhật ranking. Backtest EA chỉ cần khi logic thay đổi.
