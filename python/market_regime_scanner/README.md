# Market Regime Scanner

TPO-based multi-timeframe regime analysis, automated trading system, and coin universe selection pipeline.

> **Data storage:** All market data (parquet files) and HTML reports are stored on **AWS S3** — nothing is kept on local disk after scan.  See [S3 Storage](#s3-storage) below.

## Quick Start

```powershell
cd D:\code\trading_tool\python\market_regime_scanner
& D:\code\trading_tool\.venv\Scripts\Activate.ps1
pip install -e .
```

Copy `.env.example` → `.env` and fill in credentials (MT5, S3).

### Daily Scan (main entry point)
```powershell
# Full scan — all markets, open browser when done
python -m markets.daily_scan

# Selected markets only
python -m markets.daily_scan --markets FX COMM

# Skip data refresh (use existing S3 data)
python -m markets.daily_scan --skip-update

# Scan Binance watchlist only (run universe.cli screen first)
python -m markets.daily_scan --universe-only
```

**Output:** Dashboard + TPO charts published to S3 as presigned URLs, local output deleted after upload.

### Signal Tracker
```powershell
python -m markets.pnl_tracker                        # today, all markets
python -m markets.pnl_tracker --markets BINANCE FX   # specific markets
python -m markets.pnl_tracker --reset                # new baseline
```

### Observer (single symbol)
```powershell
python -m scripts.observer --symbol XAUUSDm
```

### Trading Bots (Macro Trend Catcher)
```powershell
python -m EA.macro_trend_catcher.bot --dry-run --once   # Test
python -m EA.macro_trend_catcher.bot                     # Live
python -m EA.macro_trend_catcher.backtest --symbol XAUUSDm --years 3
python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0
```

### Coin Universe Selection (Binance)
```powershell
python -m universe.cli screen          # build quality-filtered watchlist (~2 min)
python -m universe.cli report          # view last result
python -m universe.cli list --tier 1   # list Tier 1 symbols
python -m markets.daily_scan --universe-only  # scan watchlist only
```

---

## S3 Storage

All parquet data files and HTML reports live on S3 — the `data/` directory is empty locally.

```
S3 bucket : achitek-investment-application-layer  (ap-northeast-1 / Tokyo)
Data      : market_regime_scanner/data/{mt5,binance,vnstock}/
Reports   : market_regime_scanner/reports/markets/output/…
Logs      : market_regime_scanner/reports/markets/logs/
```

### Required `.env` variables

```dotenv
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_BUCKET=achitek-investment-application-layer
S3_REGION=ap-northeast-1
S3_PREFIX=market_regime_scanner/data
```

### S3 CLI

```powershell
python -m infra.s3_storage upload              # local → S3 (skip up-to-date)
python -m infra.s3_storage upload --force      # force re-upload all
python -m infra.s3_storage download            # S3 → local (missing only)
python -m infra.s3_storage sync                # bi-directional newest-wins
python -m infra.s3_storage ls                  # list all S3 objects
python -m infra.s3_storage ls binance          # list binance subdir
```

### How reads work

Every `smart_read_parquet(path)` call:
1. If local file exists → read it directly.
2. Else → stream from S3 via `boto3 get_object()` + `BytesIO` (no local write).
3. Fall back to `ensure_local()` only if `allow_download=True`.

> **Note:** Polars native `pl.read_parquet("s3://…")` does **not** work due to a Rust object-store redirect bug. All S3 reads use the boto3 workaround.

---

## Architecture

```
market_regime_scanner/
├── EA/                         # Expert Advisors (Trading Bots)
│   ├── macro_trend_catcher/    # V2/V2.1 Top-Down MBA Alignment bot + backtest
│   ├── macro_balance_scalper/  # MBA Range Bounce strategy
│   ├── regime_filters/         # BTC regime, broad market filters
│   ├── shared/                 # Indicators, backtest_utils, market filter
│   └── docs/                   # EA documentation
├── analytic/                   # Domain-specific analysis
│   ├── tpo_mba/                # MBA detection & readiness tracking
│   ├── tpo_regime/             # Session regime classification
│   ├── tpo_confluence/         # Multi-TF alignment logic
│   ├── tpo_context/            # MTF context analysis
│   └── ob_analysis/            # Order block analysis
├── core/                       # Core primitives (TPO, OB, session, resampler)
├── data_providers/             # Unified data access layer (parquet + S3 fallback)
├── infra/                      # Infrastructure
│   ├── s3_storage.py           # ★ S3 upload/download/stream/presigned URLs
│   ├── signal_logger.py        # CSV signal log (daily + aggregate), S3 sync
│   ├── parquet_manager.py      # MT5 fetch, merge, upload
│   ├── mt5.py                  # MT5 connection helpers
│   └── settings_loader.py      # .env / settings.yaml loader
├── markets/                    # Multi-market scanner & daily scan
│   ├── daily_scan.py           # ★ Main entry point — all markets → S3 dashboard
│   ├── sync.py                 # Data freshness (checks S3 mtime, fetches if stale)
│   ├── pnl_tracker.py          # Signal regime tracker
│   ├── reporting.py            # HTML dashboard & per-market report builder
│   ├── manager.py              # MarketManager (scanner factory)
│   ├── registry.py             # MarketRegistry (symbol lists)
│   ├── fx/, comm/, us_stock/   # Market adapters
│   ├── binance/                # Binance downloader, data provider, scanner
│   ├── vnstock/                # VNStock downloader, data provider, scanner
│   └── logs/                   # CSV signal logs (gitignored, synced to S3)
├── universe/                   # Coin Universe Selection Pipeline
│   ├── cli.py                  # Entry point (screen/report/list)
│   ├── pre_screener.py         # Stage 1: volume/history/price filters
│   ├── backtester.py           # Stage 2: EA backtest
│   ├── screener.py             # Stage 3: score & tier
│   └── watchlist.py            # JSON I/O + query helpers
├── scripts/                    # CLI tools
│   └── observer.py             # Single-symbol multi-TF dashboard
├── viz/                        # Visualization (Plotly TPO charts)
├── data/                       # Local data cache (gitignored, loaded from S3)
│   └── detection_logs/         # Small local-only detection logs
├── docs/                       # Documentation
└── tests/                      # Tests (62 tests, pytest)
```

## Key Components

| Component | Purpose |
|-----------|---------|
| `infra/s3_storage.py` | **★** S3 read/write, streaming, presigned URLs, log sync |
| `markets/daily_scan.py` | **★** Main scan — all markets → S3 presigned dashboard |
| `markets/sync.py` | Data freshness — checks S3 mtime before re-fetching from APIs |
| `universe/` | Coin universe selection (pre-screen → backtest → tier) |
| `EA/macro_trend_catcher/` | Active trading system (bot + backtest + filter) |
| `analytic/tpo_mba/tracker.py` | Core MBA context builder (`build_mba_context()`) |
| `viz/tpo_visualizer.py` | Interactive TPO chart generation (HTML in-memory → S3) |
| `data_providers/` | Unified parquet reader with S3 streaming fallback |

## Supported Markets

| Market | Data Source | Symbols |
|--------|-------------|---------|
| **Forex** | MT5 | 7 majors + 20 crosses |
| **Commodities** | MT5 | XAU, XAG, Oil, Gas, etc. |
| **US Stocks** | MT5 | 16 stocks + 4 indices |
| **Crypto (MT5)** | MT5 | BTC, ETH, SOL, etc. |
| **Binance Spot** | Binance API → S3 | ~259 symbols (H4 + D1 + W1) |
| **VN Stocks** | vnstock API → S3 | VN100 + VN30 |

## Documentation

### EA Framework
- [EA Overview](EA/docs/README.md) — Architecture, modules, dependency graph
- [Backtest Guide](EA/docs/Backtest_Guide.md) — All backtest variants
- [Trend Catcher](EA/macro_trend_catcher/docs/README.md) — V2/V2.1 strategy, config, CLI

### Core System
- [Project Architecture](docs/technical/Project_Architecture.md) — Full module reference
- [TPO Logic Master](docs/technical/TPO_Logic_Master.md) — Regime & MBA algorithm docs
- [API Reference](docs/api_list.md) — All public APIs

### Guides
- [Setup Guide](docs/guides/Setup_Guide.md) — Installation, S3 config, troubleshooting
- [User Guide](docs/guides/User_Guide.md) — Usage instructions
- [Running Tests](docs/guides/Running_Tests.md) — Test commands

### Universe Module
- [Universe README](universe/README.md) — Coin universe pipeline, CLI, tier system

---
*Last update: 2026-02-25*
