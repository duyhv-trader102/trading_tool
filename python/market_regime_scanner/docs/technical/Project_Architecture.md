# Project Structure - Market Regime Scanner

> Last Updated: 2026-02-23

## Overview

A Python-based trading analysis framework that combines **Market Profile (TPO)** analysis with **MBA (Macro Balance Area)** detection for regime classification, readiness evaluation, and automated trading.

**Key Capabilities:**
- TPO Profile analysis (POC, VAH, VAL, Value Area, Distribution shapes)
- Balance vs Imbalance regime classification (rule-based)
- MBA detection with distribution chain tracking
- Multi-timeframe top-down readiness evaluation
- Automated trading via EA bots (MT5 live + Binance backtest)
- Market filter & symbol ranking
- Interactive HTML visualizations (Plotly)
- MT5 + Binance + VNStock data integration

---

## Directory Structure

```
market_regime_scanner/
├── core/               # Core primitives (TPO, OB, Session, Resampler)
├── analytic/           # Domain-specific analysis modules
│   ├── tpo_mba/            # MBA detection, tracking, readiness
│   ├── tpo_regime/         # Session-level regime classification
│   ├── tpo_confluence/     # Multi-TF alignment (nested gating)
│   ├── tpo_context/        # MTF context analysis
│   ├── ob_analysis/        # Order block analysis & mitigation
│   └── performance/        # Performance analytics & regime backtesting
├── EA/                 # Expert Advisors (Trading Bots) — modular architecture
│   ├── alpha/              # Signal generation facade
│   ├── analytics/          # Research & analysis
│   ├── risk/               # Capital preservation
│   ├── portfolio/          # [Phase 2] Portfolio-level backtest
│   ├── infra/              # [Phase 3] MT5 connector, scheduler, Telegram
│   ├── shared/             # Cross-cutting: indicators, backtest_utils, filters
│   ├── macro_trend_catcher/  # V1/V2 Top-Down MBA Alignment strategy
│   ├── macro_balance_scalper/# Balance scalper strategy
│   ├── tests/              # EA test suite
│   └── data/               # Runtime state (positions_v2.json)
├── data_providers/     # Unified data access layer (Parquet + MT5)
│   ├── __init__.py         # Public API: get_data(), get_provider()
│   ├── unified_provider.py # Parquet-first, MT5-fallback
│   ├── parquet_data_provider.py
│   └── mt5_data_provider.py
├── markets/            # Market-specific adapters with unified interface
│   ├── base/               # BaseDataProvider, MT5DataProvider, BaseScanner
│   ├── fx/                 # FX (27 pairs: 7 majors + 20 crosses)
│   ├── comm/               # Commodities (metals + energy)
│   ├── us_stock/           # US Stocks + indices
│   ├── coin/               # Crypto (MT5 symbols)
│   ├── binance/            # Binance Spot (ccxt)
│   ├── vnstock/            # Vietnam Stocks
│   ├── cli.py              # Per-market CLI: scan/viz/log
│   ├── daily_scan.py       # ★ All-market daily scanner → HTML dashboard
│   ├── pnl_tracker.py      # ★ Signal Tracker — snapshot-based regime diff
│   ├── manager.py          # MarketManager — orchestrates scan + charts
│   ├── registry.py         # MarketRegistry — provider + symbol routing
│   └── reporting.py        # Per-market HTML report generation
├── workflow/           # Pipeline orchestration (shared by observer + EA)
├── viz/                # Visualization (Plotly-based charts, heatmaps)
├── infra/              # Infrastructure (MT5, config, parquet, signal logger)
│   ├── data/               # Low-level data provider adapters (legacy)
│   ├── signal_logger.py    # Persistent READY-signal log (CSV per day)
│   └── parquet_manager.py  # Parquet I/O helpers
├── scripts/            # CLI tools, observers, research
│   ├── daily_scan.py       # ★ All-market daily scanner → HTML dashboard
│   ├── mt5/                # MT5 observer, data fetch, review CLI
│   └── research/           # Backtest research scripts
├── data/               # Data files (fully gitignored)
│   ├── binance/            # 441 H4 parquets (Binance spot)
│   ├── mt5/                # MT5 H4/D1/W1 parquets
│   └── signal_logs/        # Daily signal logs (CSV)
├── tests/              # pytest test suite
│   ├── conftest.py
│   ├── test_smoke.py       # Import smoke tests
│   ├── test_registry.py    # MarketRegistry tests
│   ├── test_signal_logger.py
│   ├── test_parquet_provider.py
│   └── test_scanner.py     # Integration: analyze_symbol()
├── docs/               # Documentation
└── pyproject.toml      # Project metadata + pytest config
```

---

## Layer Architecture

```
┌──────────────────────────────────────────────────────┐
│  EA/                  Trading bots & backtesting     │
├──────────────────────────────────────────────────────┤
│  scripts/             CLI entry points, observers    │
├──────────────────────────────────────────────────────┤
│  viz/                 Visualization layer            │
├──────────────────────────────────────────────────────┤
│  workflow/            Pipeline orchestration         │
├──────────────────────────────────────────────────────┤
│  analytic/            Analysis (regime, MBA, etc.)   │
├──────────────────────────────────────────────────────┤
│  core/                Core primitives                │
├──────────────────────────────────────────────────────┤
│  infra/               Infrastructure (MT5, config)   │
└──────────────────────────────────────────────────────┘
```

**Dependency Rules:**
- `core/` -> No internal dependencies (only stdlib + pandas/numpy/polars)
- `analytic/` -> Can import from `core/`
- `workflow/` -> Can import from `core/` and `analytic/`
- `viz/` -> Can import from `core/` and `analytic/`
- `EA/` -> Can import from all layers
- `scripts/` -> Can import from all layers

---

## Core Layer (`core/`)

### `tpo.py`
TPO Profile implementation for Market Profile analysis.

**Key Classes:**
- `TPOResult` -- Dataclass containing all session metrics
- `TPOProfile` -- Calculator class

**Key Metrics:**
| Metric | Description |
|--------|-------------|
| POC | Point of Control -- price with most TPO |
| VAH/VAL | Value Area High/Low (70% of volume) |
| Single Prints | Price levels with only 1 TPO |
| Minus Development | Contiguous single print zones |
| Unfair Extremes | Single prints at session highs/lows |
| IB | Initial Balance (first N bars range) |
| Day Type | Normal, Normal Variation, Neutral, Trend |
| Profile Shape | P (bullish), b (bearish), D (balanced) |
| Distribution | 3-1-3, 3-2-1, 1-2-3, or other |

### `ob.py`
Order Block detection algorithms.

| Function | Pattern |
|----------|---------|
| `find_wick_ob()` | Large wick candles (>50% of spread) |
| `find_insidebar_ob()` | Inside bar patterns |
| `find_prev_outsidebar_ob()` | Outside bar + previous candle |
| `find_swing_ob()` | Swing high/low breakouts |
| `find_all_ob()` | Combined detection |
| `attach_mitigation_status()` | Track OB tests/breaks |

### `candle.py`
OHLC utility functions and candle pattern detection.

### `resampler.py`
Data resampling for multi-timeframe analysis.

**Key Function:**
```python
resample_data(df, interval)  # H4 -> D1, D1 -> W1, etc.
```
Used by Binance backtest to convert H4 parquets into D1/W1 bars.

### `session_splitter.py`
Splits raw bars into sessions (Daily/Weekly/Monthly).

**Key Function:**
```python
split_sessions(df, session_type)  # 'D', 'W', 'M'
```

### `session_policy.py`
Session boundary rules for different markets.

**Key Classes:**
- `SessionPolicy` (ABC)
- `MT5ForexPolicy` -- Skips weekends for Forex
- `Default247Policy` -- 24/7 markets (crypto)

### `data_provider.py`
Abstract data provider interface.

### `path_manager.py`
Path utilities and project root detection.

---

## Analysis Layer (`analytic/`)

### `tpo_mba/` -- MBA Detection & Tracking
The core engine for Macro Balance Area analysis.

| File | Purpose |
|------|---------|
| `tracker.py` | Top-level API: `build_mba_context()` -> `MBAMetadata` |
| `detector.py` | `find_last_directional_move()`, distribution chain building |
| `schema.py` | Dataclasses: `MBAUnit`, `MacroBalanceArea`, `MBAReadiness`, `MBAMetadata` |

**Key Pipeline:**
```python
build_mba_context(sessions, timeframe)
  -> find_last_directional_move() -> track_mba_evolution()
  -> evaluate_mba_readiness() -> MBAMetadata
```

### `tpo_regime/` -- Session Regime Classification

| File | Purpose |
|------|---------|
| `schema.py` | `RegimeResult`, `RegimeFeatures` dataclasses |
| `analytics.py` | Detection performance analysis & threshold tuning |

### `tpo_confluence/` -- Multi-TF Alignment
Nested gating logic for cross-timeframe confluence.

| File | Purpose |
|------|---------|
| `tpo_alignment.py` | TPO balance detection, IB extension analysis, MTF confluence |

### `tpo_context/` -- MTF Context
Historical and multi-timeframe context analysis.

| File | Purpose |
|------|---------|
| `analyzer.py` | Context analysis utilities |
| `schema.py` | Context dataclasses |

### `ob_analysis/` -- Order Block Analysis

| File | Purpose |
|------|---------|
| `ob_analysis.py` | Combined OB detection and analysis |
| `ob_mitigation.py` | Mitigation/test status tracking |

### `performance/` -- Performance Analytics

| File | Purpose |
|------|---------|
| `analytics.py` | Strategy performance analysis |
| `regime_mechanical.py` | Mechanical regime backtesting |

---

## EA Layer (`EA/`)

### Modular Architecture (Feb 2026)

```
EA/
├── alpha/          # Signal generation facade (re-exports)
├── analytics/      # Scoring, validation, attribution, monitoring
├── risk/           # Circuit breaker, position sizer, portfolio guard, reconciler
├── portfolio/      # [Phase 2] Portfolio-level backtest
├── infra/          # [Phase 3] MT5 connector, scheduler, Telegram
├── shared/         # Cross-cutting: indicators, backtest_utils, filters
├── macro_trend_catcher/  # V1/V2 trend strategy
├── macro_balance_scalper/# Balance scalper strategy
├── tests/          # EA-specific tests
└── data/           # Runtime state persistence
```

### `alpha/` — Signal Generation Facade

Re-exports core signals and universe configs for clean imports:
- `alpha.signals` → `AlignmentState`, `SignalGeneratorV2`, indicators
- `alpha.universe` → `TrendCatcherV2Config`
- `alpha.regime` → `MBATracker` (from `analytic.tpo_mba`)

### `analytics/` — Research & Analysis

| Subpackage | Status | Purpose |
|---|---|---|
| `scoring/` | Active | Re-exports `market_filter` + `rank_symbols` |
| `validation/` | Active | Re-exports `Trade`, `BacktestMetrics`, metrics |
| `attribution/` | Phase 2 | Trade attribution, factor analysis |
| `monitoring/` | Phase 3 | Equity monitoring, health checks, alerts |

### `risk/` — Capital Preservation

| Module | Purpose |
|---|---|
| `circuit_breaker.py` | Daily/weekly P&L limits, trailing DD halt (prop firm) |
| `position_sizer.py` | Fixed fractional + volatility-adjusted sizing |
| `portfolio_guard.py` | Max positions, sector concentration, exposure limits |
| `reconciler.py` | EA vs broker state diff detection & auto-resolve |

### `shared/` — Cross-Cutting Utilities

| File | Key Exports |
|------|-------------|
| `indicators.py` | `calculate_atr()`, `calculate_adx()`, `calculate_rsi()`, `calculate_ema()`, `calculate_sma()`, `calculate_bollinger_bands()` |
| `backtest_utils.py` | `Trade`, `BacktestMetrics`, `calculate_metrics()`, `print_metrics()`, `calculate_equity_curve()` |
| `market_filter.py` | `FilterConfig`, `ScoredSymbol`, `score_symbols()`, `export_watchlist()` |
| `rank_symbols.py` | `RankConfig`, `rank_symbols()`, `save_rank_output()`, `print_ranking()` |

### `macro_trend_catcher/` (Active)
Top-down MBA alignment strategy with automated trading.

| File | Purpose |
|------|---------|
| `config.py` | Strategy params, asset universe, TF mapping |
| `signals.py` | `AlignmentState`, `SignalGeneratorV2`, entry/exit logic |
| `bot.py` | Live MT5 trading bot (scheduled loop) |
| `backtest.py` | Single-symbol MT5 walk-forward backtest |
| `backtest_binance.py` | Batch backtest on 259 Binance spot symbols |
| `backtest_spot.py` | LONG-only spot backtest (Binance) |
| `backtest_spot_v21.py` | V2.1 spot backtest with compression gate |
| `backtest_v21_detailed.py` | V2.1 with per-trade CSV/JSON logging (35 fields) |

**Strategy:**
```
Monthly ready (anchor) -> Weekly ready (same dir) -> Daily ready (same dir) -> ENTER
```

**V2.1 Compression Gate:** Each TF's last session must be compressed
(Normal/Neutral/3-1-3 without minus dev) for alignment to hold.

**TF Mapping (V2):**
| Session | Bar TF | Bars/Session |
|---------|--------|-------------|
| Monthly | W1 | ~4-5 |
| Weekly | D1 | ~5 |
| Daily | H4 | ~6 |

### `macro_trend_catcher/v1/` (Legacy)
Baseline pure M/W/D alignment without filters.

### `macro_balance_scalper/`
Trades bounces within Monthly MBA range targeting Daily MBA (I→B→I fractal).
Separate strategy with V1 (swing) and V2 (scalp) modes.

---

## Visualization Layer (`viz/`)

| File | Purpose |
|------|---------|
| `tpo_visualizer.py` | TPO charts with blocks, regime markers, MBA bands |
| `dashboard_visualizer.py` | Dashboard generation |
| `heatmap_generator.py` | Regime heatmap |
| `generate_html_report.py` | HTML report output |
| `generate_normalized_report.py` | Performance reports with Monte Carlo |
| `visualizer.py` | Order Block visualization |
| `utils/tpo_viz_utils.py` | Shared viz utilities |

**Key Functions:**
```python
visualize_tpo_blocks(results, block_size, n_sessions, filename)
visualize_tpo_topdown(mtf_results, target_rows, filename)
visualize_tpo_with_regime(results, regime_results, block_size, n_sessions, filename)
```

---

## Infrastructure Layer (`infra/`)

### `mt5.py`
MetaTrader 5 integration.
```python
start_mt5(username, password, server, mt5Pathway)
get_historical_data(symbol, timeframe, bars)
get_tick_size(symbol)
```

### `parquet_manager.py`
Historical data storage using Parquet (Polars-based, ~3x faster than pandas).
```python
get_parquet_path(symbol, timeframe)
load_from_parquet(symbol, timeframe)        # -> pandas DataFrame
load_from_parquet_polars(symbol, timeframe)  # -> polars DataFrame
fetch_and_store_history(symbol, timeframe, years=5)
update_parquet(symbol, timeframe)
```

### `data/` -- Data Providers

| File | Purpose |
|------|---------|
| `mt5_provider.py` | MT5 data fetching (H4 parquets -> resample to D1/W1) |
| `binance_provider.py` | Binance data provider |
| `vnstock_provider.py` | VNStock data provider |

### `settings_loader.py` + `settings.yaml`
Config loading for MT5 credentials, TPO analysis params.

### `detection_logger.py`
Logging for regime detection review.

---

## Workflow Layer (`workflow/`)

| File | Purpose |
|------|---------|
| `pipeline.py` | Core analysis pipeline: `get_data()`, `analyze_from_df()`, `analyze_timeframe()`, `classify_regime()` |
| `list_symbols.py` | Symbol listing utilities |

**Key Pipeline:**
```python
from workflow.pipeline import get_data, analyze_from_df, analyze_timeframe

# Low-level
df = get_data("XAUUSDm", "H4", bars=600)
results, block_size = analyze_from_df(df, session_type="D")

# High-level (used by bot.py)
result = analyze_timeframe(symbol, tf_build, tf_session, n_sessions)
```

---

## Market Layer (`markets/`)

Market-specific adapters with unified interface. All markets share the same
`BaseScanner` + `BaseDataProvider` contract; only the symbol list and data
source differ.

| Directory | Market | Symbols | Data Source |
|-----------|--------|---------|------------|
| `fx/` | FX Majors + Crosses | 27 pairs | MT5 parquet |
| `comm/` | Commodities | 6 (metals + energy) | MT5 parquet |
| `us_stock/` | US Stocks + Indices | 19 | MT5 parquet |
| `coin/` | Crypto (MT5) | 15 | MT5 live/parquet |
| `binance/` | Binance Spot | 259 | ccxt / local parquets |
| `vnstock/` | Vietnam Stocks | VN30/VN100 | vnstock API |
| `base/` | Abstract base classes | — | — |

**Routing via Registry:**
```python
from markets.registry import MarketRegistry

MarketRegistry.list_markets()           # ['FX', 'COMM', 'US_STOCK', 'COIN', ...]
MarketRegistry.get_provider('FX')       # -> FXDataProvider instance
MarketRegistry.get_symbols('FX')        # -> ['EURUSDm', 'GBPUSDm', ...]
```

**Per-market CLI:**
```powershell
# Scan all FX pairs
python markets/cli.py scan --market FX --all

# Scan single symbol
python markets/cli.py scan --market COMM --symbol XAUUSDm

# View signal log history
python markets/cli.py log --days 7 --ready
```

**Daily all-market scanner:**
```powershell
# Scan FX + COMM + US_STOCK + COIN → generates HTML dashboard
python -m scripts.daily_scan

# Specific markets, no charts
python -m scripts.daily_scan --markets FX COMM --no-charts

# Open browser after scan
python -m scripts.daily_scan --open
```
Output: `scripts/output/daily/YYYY-MM-DD/dashboard.html`

---

## Scripts Layer (`scripts/`)

### MT5 Scripts (`scripts/mt5/`)

| File | Purpose |
|------|---------|
| `observer.py` | Main MTF dashboard generator |
| `fetch_history.py` | Download historical data to parquet |
| `data_prefetch.py` | Prefetch data for observer |
| `review_cli.py` | Interactive CLI for regime detection review |
| `config.py` | Symbol/TF configuration |

### Daily Scanner (`scripts/daily_scan.py`) ★

All-market daily scanner — runs FX, COMM, US_STOCK, and COIN in one pass,
generates per-market HTML reports and a combined filterable dashboard.

```powershell
# Full scan (all markets)
python -m scripts.daily_scan --open

# Selected markets only
python -m scripts.daily_scan --markets FX COMM --open

# Skip chart generation (faster)
python -m scripts.daily_scan --no-charts
```

| Arg | Default | Description |
|-----|---------|-------------|
| `--markets` | FX COMM US_STOCK COIN | Markets to include |
| `--no-charts` | False | Skip TPO chart generation |
| `--open` | False | Auto-open dashboard in browser |
| `--output-dir` | scripts/output/daily | Base output directory |

**Output:** `scripts/output/daily/YYYY-MM-DD/dashboard.html`
(per-market sub-reports + combined filterable dashboard)

### Signal Tracker (`markets/pnl_tracker.py`) ★

Snapshot-based regime diff tracker. Monitors how READY signals evolve over time
by comparing saved regime snapshots against current state across M/W/D timeframes.

**Workflow:**
1. **First Run**: Analyze all READY signals from signal log → save M/W/D regime state as snapshot baseline.
2. **Subsequent Runs**: Load snapshot → re-analyze current → diff. Only update snapshot entries where regime (status/trend) changed.
3. **Output**: Terminal report + HTML dashboard grouped by market (MARKET_META ordering).

```powershell
# All signals from today
python -m markets.pnl_tracker

# Specific date + markets
python -m markets.pnl_tracker --date 2026-02-23 --markets BINANCE FX

# Reset snapshot (fresh baseline)
python -m markets.pnl_tracker --date 2026-02-23 --reset

# No browser auto-open
python -m markets.pnl_tracker --no-open
```

| Arg | Default | Description |
|-----|---------|-------------|
| `--date` | today | Signal date (YYYY-MM-DD) |
| `--days` | 1 | Include last N days of signals |
| `--markets` | all | Filter markets (e.g. BINANCE FX) |
| `--reset` | false | Delete snapshot, create fresh baseline |
| `--no-open` | false | Don't auto-open dashboard |
| `--output` | `markets/output/signal_tracker.html` | Dashboard output path |

**Snapshot Storage:** `markets/logs/tracker/YYYY-MM-DD.csv`
**Dashboard Output:** `markets/output/signal_tracker.html`

---

### Research Scripts (`scripts/research/`)

| File | Purpose |
|------|---------|
| `macro_swing_stats.py` | Historical swing trade statistics |
| `batch_position_backtest.py` | Batch position sizing backtest |

---

## Dependencies

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "numpy>=1.24",
    "pyarrow>=14.0",
    "polars>=0.20",
    "MetaTrader5>=5.0",
    "plotly>=5.0",
    "PyYAML>=6.0",
    "vnstock>=3.0",
    "ccxt>=4.0",
]
```

---

## Quick Start

```powershell
cd D:\code\trading_tool\python\market_regime_scanner
& D:\code\trading_tool\.venv\Scripts\Activate.ps1
pip install -e .

# 1. Fetch/update MT5 data
python scripts/mt5/fetch_history.py

# 2. Daily all-market scan (FX + COMM + US_STOCK + COIN)
python -m scripts.daily_scan --open

# 3. Signal Tracker — track regime changes
python -m markets.pnl_tracker --no-open

# 4. Single market scan
python markets/cli.py scan --market FX --all

# 5. MTF top-down HTML dashboard (observer)
python -m scripts.mt5.observer

# 6. V2 Backtest (Binance)
python -m scripts.research.binance_v3_4scenarios --symbols BTC ETH --scenarios C

# 7. Run tests
python -m pytest tests/ -v
```
