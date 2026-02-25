# Macro System User Guide

> Last Updated: 2026-02-25

Step-by-step instructions for operating the Market Regime Scanner and Macro Trend Catcher V2.

## 1. System Overview

The system identifies high-probability Swing Trading opportunities by analyzing market structure (TPO/MBA) across Monthly, Weekly, and Daily timeframes.

**Two Main Workflows:**

| Workflow | Purpose | Entry Point |
|----------|---------|-------------|
| **Daily Scan** | All-market scan → HTML dashboard | `markets/daily_scan.py` |
| **Signal Tracker** | Track regime changes since scan | `markets/pnl_tracker.py` |
| **Universe Filter** | Build quality coin watchlist (run once) | `universe/cli.py` |
| **Analysis** | Single-market scan or visualize regimes | `markets/cli.py`, `scripts/observer.py` |
| **Trading** | Automated backtest & live trading | `EA/macro_trend_catcher/` |

---

## 2. Analysis Workflow

### 2.1 Daily All-Market Scan ★

Scan FX, COMM, US_STOCK, and COIN in one command, producing a combined HTML dashboard:

```powershell
cd D:\code\trading_tool\python\market_regime_scanner

# Full scan — all markets
python -m markets.daily_scan

# Selected markets only
python -m markets.daily_scan --markets FX COMM

# Skip data refresh (faster, use cached parquets)
python -m markets.daily_scan --skip-update

# Only scan Binance watchlist (faster, quality filtered)
python -m markets.daily_scan --universe-only
```

**Output:** S3 presigned URL — dashboard.html is uploaded to S3 and a time-limited URL is printed to console. No local files are kept after the scan.

> **Lưu ý:** `daily_scan` dọn dẹp `base_dir` local sau khi upload S3 thành công. Không có file nào còn lại trên máy sau khi chạy.

---

### 2.2 Signal Tracker ★

Theo dõi thay đổi regime (M/W/D) của các tín hiệu READY từ Daily Scan.

**Cách hoạt động:**
- **Lần chạy đầu**: Phân tích tất cả READY signals (1M/1W/1D), lưu snapshot làm baseline vào `markets/logs/tracker/YYYY-MM-DD.csv`.
- **Lần chạy sau**: Load snapshot đã lưu, phân tích lại trạng thái hiện tại, so sánh với snapshot. Chỉ update snapshot khi có thay đổi regime (status hoặc trend).

```powershell
cd D:\code\trading_tool\python\market_regime_scanner

# Tracker cho ngày hôm nay, tất cả markets
python -m markets.pnl_tracker

# Tracker cho ngày cụ thể
python -m markets.pnl_tracker --date 2026-02-23

# Chỉ theo dõi markets cụ thể
python -m markets.pnl_tracker --markets BINANCE FX

# Xóa snapshot cũ, tạo baseline mới
python -m markets.pnl_tracker --date 2026-02-23 --reset

# Không mở browser
python -m markets.pnl_tracker --no-open
```

| Arg | Default | Mô tả |
|-----|---------|-------|
| `--date` | today | Ngày signal cần track (YYYY-MM-DD) |
| `--days` | 1 | Gộp N ngày signal gần nhất |
| `--markets` | all | Lọc theo market (VD: BINANCE FX) |
| `--reset` | false | Xóa snapshot cũ, chạy lại từ đầu |
| `--no-open` | false | Không auto-open dashboard |
| `--output` | `markets/output/signal_tracker.html` | Đường dẫn dashboard |

**Output:**
- **Snapshot**: `markets/logs/tracker/YYYY-MM-DD.csv` — Lưu trạng thái regime M/W/D của từng symbol
- **Dashboard**: `markets/output/signal_tracker.html` — HTML dark-theme với:
  - Summary cards theo market group (FX, Commodities, Binance...)
  - Filter by market / changed only
  - Bảng so sánh Snapshot vs Current cho M/W/D
  - Highlight khi regime thay đổi (status/trend)

**Snapshot CSV columns:**
| Category | Fields |
|----------|--------|
| Identity | market, symbol, signal, scanned_at, snapshot_at |
| Monthly | m_status, m_trend, m_range_low, m_range_high, m_is_ready, m_ready_direction |
| Weekly | w_status, w_trend, w_range_low, w_range_high, w_is_ready, w_ready_direction |
| Daily | d_status, d_trend, d_range_low, d_range_high, d_is_ready, d_ready_direction |

---

### 2.3 MT5 Top-Down Observer

Multi-timeframe regime dashboard for MT5 symbols.

```powershell
cd D:\code\trading_tool\python\market_regime_scanner

# All configured symbols
python -m scripts.observer

# Specific symbols
python -m scripts.observer --symbol XAUUSDm BTCUSDm

# Crypto (with weekend data)
python -m scripts.observer --symbol BTCUSDm --has-weekend
```

**Output:** `scripts/output/{SYMBOL}_topdown.html` -- Interactive multi-TF dashboard.

### 2.4 Market CLI (Single Market)

Unified CLI for scanning or visualizing one market at a time:

```powershell
# Scan all coins
python -m markets.cli scan --market COIN --all

# Scan specific symbol
python -m markets.cli scan --market VNSTOCK --symbol VNM

# Scan specific group
python -m markets.cli scan --market VNSTOCK --group VN30

# Visualize TPO top-down
python -m markets.cli viz --market COIN --symbol BTCUSDm
```

**Output:**
- Terminal: Real-time analysis reports
- HTML: `markets/{market}/output/scan_report_{market}.html`
- Viz: `markets/{market}/output/{SYMBOL}_TPO_TopDown.html`

### 2.5 Legacy Multi-Market Scanner

```powershell
python -m scripts.macro_scanner
```

### 2.6 Coin Universe Selection (Binance) ★

Xây dựng watchlist Binance chất lượng cao (chạy 1 lần, cache lại):

```powershell
# Full pipeline: pre-screen → backtest → score (lần đầu ~2 phút)
python -m universe.cli screen

# Force re-run (bỏ cache)
python -m universe.cli screen --force

# Xem kết quả lần trước
python -m universe.cli report

# Daily scan chỉ scan watchlist (nhanh hơn, quality cao hơn)
python -m markets.daily_scan --universe-only
```

**Output:** `universe/watchlist.json` — tiered ranking:

| Tier | Điểm | Ý nghĩa | Daily Scan |
|------|------|---------|------------|
| Tier 1 | ≥ 70 | Elite — full conviction | ✅ Included |
| Tier 2 | ≥ 50 | Strong — normal size | ✅ Included |
| Tier 3 | ≥ 35 | Watch — smaller size | ✅ Included |
| Tier 4 | < 35 | EA signal, kém quality | ❌ Watch only |

See [universe/README.md](../../universe/README.md) for full docs.

## 3. Trading Workflow (V2 Macro Trend Catcher)

### 3.1 Single Symbol Backtest (MT5 Data)

```powershell
# Default: XAUUSDm, 3 years, SL=3x ATR, cooldown=20 days
python -m EA.macro_trend_catcher.backtest --symbol XAUUSDm --years 3

# Custom parameters
python -m EA.macro_trend_catcher.backtest --symbol BTCUSDm --sl-mult 2.5 --cooldown 15
```

**Output:** Console metrics (PF, Sharpe, Win Rate, Drawdown, equity curve).

### 3.2 Batch Backtest (Binance Spot)

Run backtest on ALL Binance spot symbols with 3+ years of H4 data:

```powershell
python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0
```

**Output:**
- Console: Per-symbol progress, TOP 30, BOTTOM 10, aggregate stats
- JSON: `EA/macro_trend_catcher/reports/binance_batch_results.json`

### 3.3 V2.1 Detailed Backtest (with Compression Gate)

V2.1 adds the **Compression Gate** — each TF's last session must be Normal/Neutral/3-1-3.
Includes per-trade logging with 35 fields for deep analysis:

```powershell
python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0
```

**Output:**
- `v21_trade_log.csv` — Per-trade CSV (35 fields: alignment state, MBA ranges, ATR, equity)
- `v21_trade_log.json` — Same data in JSON format
- `v21_summary_report.txt` — Aggregate report with tier classification
- `spot_v21_backtest_results.json` — Per-symbol metrics
- `spot_v21_watchlist.json` — Tiered watchlist
- `spot_v21_ranked_top50.json` / `.csv` — HealthyTrendScore ranking

**TradeLogEntry Fields (per trade):**
| Category | Fields |
|----------|--------|
| Identity | symbol, trade_id |
| Timing | entry_time, exit_time, duration_days |
| Price | entry_price, exit_price, stop_loss, sl_distance_pct, atr_at_entry |
| Result | direction, exit_reason, gross_return_pct, net_return_pct, is_win |
| Monthly | m_ready, m_direction, m_compressed, m_mba_low, m_mba_high, m_continuity |
| Weekly | w_ready, w_direction, w_compressed, w_mba_low, w_mba_high, w_continuity |
| Daily | d_ready, d_direction, d_compressed, d_mba_low, d_mba_high, d_continuity |
| Summary | alignment_summary, equity_before, equity_after |

### 3.3 Market Filter (Score & Rank)

Score and rank symbols from batch backtest results:

```powershell
# Default thresholds
python -m EA.shared.market_filter

# Custom filters
python -m EA.shared.market_filter --min-trades 8 --min-pf 1.5
```

**Tiers:**
| Tier | Score | Action |
|------|-------|--------|
| Tier 1 (Elite) | >= 70 | Full conviction |
| Tier 2 (Strong) | >= 50 | Normal position size |
| Tier 3 (Watch) | >= 35 | Monitor, smaller size |
| Rejected | < 35 | Don't trade |

**Output:** `EA/shared/reports/watchlist.json`

### 3.4 Live Bot (MT5)

```powershell
# Test mode (no real trades)
python -m EA.macro_trend_catcher.bot --dry-run --once

# Live trading
python -m EA.macro_trend_catcher.bot

# Specific asset classes
python -m EA.macro_trend_catcher.bot --assets FOREX_MAJORS COMMODITIES

# Custom interval (hours between checks)
python -m EA.macro_trend_catcher.bot --interval 4
```

### 3.5 CLI Options Reference

| Option | Used By | Default | Description |
|--------|---------|---------|-------------|
| `--dry-run` | bot | false | No real trades |
| `--once` | bot | false | Run once then exit |
| `--assets` | bot | all | Asset classes to trade |
| `--interval` | bot | 4 | Hours between checks |
| `--symbol` | backtest | XAUUSDm | Symbol to backtest |
| `--years` | backtest | 3 | Years of history |
| `--sl-mult` | backtest, batch | 3.0 | Stop-loss ATR multiplier |
| `--cooldown` | backtest, batch | 20 | Cooldown days after SL |
| `--min-trades` | filter | 7 | Min trades for filter |
| `--min-pf` | filter | 1.3 | Min profit factor for filter |
| `--export` | filter | reports/watchlist.json | Watchlist output path |

---

## 4. Deep Debugging with TPO Charts

For detailed analysis of a specific symbol:

### Market CLI:
```powershell
python -m markets.cli viz --market COIN --symbol BTCUSDm
```

**Features:**
- Dynamic window (auto-zoom to recent trend session)
- Top-down view (Monthly + Weekly stacked)
- MBA bands and distribution markers

---

## 5. Data Management

Tất cả parquet files được lưu trên **S3**. Local files chỉ là cache tạm thời — chúng được tự động dọn sạch sau mỗi scan.

### S3 Sync thủ công
```powershell
# Xem danh sách file trên S3
python -m infra.s3_storage ls
python -m infra.s3_storage ls binance

# Download S3 → local (chỉ file missing)
python -m infra.s3_storage download

# Upload local → S3
python -m infra.s3_storage upload
python -m infra.s3_storage upload --force    # force re-upload

# Bi-directional sync (newest-wins)
python -m infra.s3_storage sync
```

### MT5 Data
```powershell
# `sync.py` kiểm tra S3 mtimes trước khi fetch từ MT5.
# Nếu S3 đã có file fresh → chỉ incremental update.
# Data path trên S3: market_regime_scanner/data/mt5/{SYMBOL}_H4.parquet
```

### Binance Data
```
# H4 parquets stored in S3: market_regime_scanner/data/binance/{SYMBOL}_USDT_H4.parquet
# 441 symbols available
# Resampled to D1/W1 by core.resampler during backtest
```

### VNStock Data
```
# Stored in S3: market_regime_scanner/data/vnstock/
# sync.py checks S3 freshness before re-fetching from vnstock API
```

---

## 6. Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Run `pip install -e .` from project root |
| "No Data Found" | Ensure MT5 is open, symbol in Market Watch |
| "Connection Failed" | Check `infra/settings.yaml` credentials, restart MT5 |
| Stale data warning | Run `python -m infra.s3_storage sync` to refresh |
| Visualization errors | Check `plotly` version |
| Import errors in EA | EA is not in setuptools -- run from project root with `python -m` |
| S3 upload error | All uploads use `put_object(Body=bytes)` — never `upload_file()` |
| No local output after scan | Expected — `daily_scan` deletes local files after S3 upload |
| `boto3` not found | Run `pip install boto3` |
| `.env` not loaded | Ensure `.env` is in project root and `python-dotenv` is installed |
