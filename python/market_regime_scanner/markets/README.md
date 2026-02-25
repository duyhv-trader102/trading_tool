# markets/ — Market Scanner Module

Central hub for all scanning, data sync, and reporting across markets
(FX, Commodities, US Stocks, Crypto/MT5, Binance, VN Stocks).

---

## Architecture

```
market_regime_scanner/
├── data_providers/          ← Infrastructure: OHLCV data access & parquet cache
│   ├── base.py              ← BaseDataProvider (ABC) — single source of truth
│   ├── parquet_data_provider.py  ← Pluggable-registry parquet reads + write helpers
│   ├── unified_provider.py  ← Parquet-first → MT5-fallback → resample
│   └── mt5_data_provider.py
│
└── markets/                 ← Domain: scanners, sync, reporting
    ├── daily_scan.py        ← ★ Main entry point (run this!)
    ├── pnl_tracker.py       ← ★ Signal Tracker — snapshot-based regime diff
    ├── sync.py              ← Data freshness: MT5 + VNStock + Binance
    ├── reporting.py         ← DashboardReporter + HTMLReporter (HTML generation)
    ├── registry.py          ← MarketRegistry — symbol & provider lookup
    ├── manager.py           ← MarketManager — scanner / visualizer orchestration
    ├── cli.py               ← Simple one-market CLI (scan / viz / log)
    │
    ├── base/                ← Shared base classes
    │   ├── scanner.py       ← BaseScanner (top-down three-TF analysis)
    │   ├── data_provider.py ← MT5DataProvider re-export
    │   └── viz_tpo_chart.py ← BaseVizTPOChart
    │
    ├── fx/                  ← Market: FX (MT5-backed)
    ├── comm/                ← Market: Commodities (MT5-backed)
    ├── coin/                ← Market: Crypto via MT5 (MT5-backed)
    ├── us_stock/            ← Market: US Stocks (MT5-backed)
    ├── binance/             ← Market: Binance (ccxt, native H4/D1/W1)
    └── vnstock/             ← Market: VN Stocks (vnstock API, D1 only)
```

### Data flow

```
daily_scan.main()
  → sync_*_data()            # ensure parquet files are fresh
  → scan_market(market)
      → MarketRegistry.get_symbols()
      → MarketManager.get_scanner()
      → scanner.analyze_symbol(sym)
           → UnifiedDataProvider.get_data(sym, tf)
                 → ParquetDataProvider (exact TF, any registered dir)
                 → MT5 live fetch + auto-cache
                 → resample from coarser stored TF
  → DashboardReporter.generate_dashboard()
```

---

## Running the Daily Scan

```bash
cd python/market_regime_scanner

# Scan all markets (default)
python -m markets.daily_scan

# Specific markets only
python -m markets.daily_scan --markets FX COMM

# Skip data refresh (faster, uses existing parquet)
python -m markets.daily_scan --skip-update

# Skip chart generation
python -m markets.daily_scan --no-charts

# Don't auto-open dashboard in browser
python -m markets.daily_scan --no-open
```

Output is written to `markets/output/daily/{YYYY-MM-DD}/dashboard.html`.

> **Backward-compat**: `python scripts/daily_scan.py` still works — it is a thin
> shim that delegates to `markets.daily_scan`.

---

## Signal Tracker

Track how READY signals evolve over time by comparing a saved regime snapshot
against live re-analysis across Monthly, Weekly, and Daily timeframes.

### How it works

```
pnl_tracker.main()
  -> sync data for signal markets     # fetch latest H4/D1/W1 parquets
  -> SignalLogger.get_ready_signals(date)   # load READY signals from CSV log
  → load_snapshot(date)                    # load saved baseline (if exists)
  → for each signal:
      → analyze_symbol_full(symbol, market) # fresh M/W/D analysis
      → compare snapshot vs current         # diff status + trend per TF
      → update snapshot only if changed     # persist regime changes
  → save_snapshot(date)                    # write markets/logs/tracker/YYYY-MM-DD.csv
  → print_terminal_report()                # grouped by market (MARKET_META order)
  → generate_dashboard()                   # HTML with filter/sort/market groups
```

### Usage

```bash
cd python/market_regime_scanner

# Track all READY signals from today
python -m markets.pnl_tracker

# Track specific date + markets
python -m markets.pnl_tracker --date 2026-02-23 --markets BINANCE FX

# Include signals from last 3 days
python -m markets.pnl_tracker --days 3

# Reset snapshot (delete saved baseline, start fresh)
python -m markets.pnl_tracker --date 2026-02-23 --reset

# Don't auto-open browser
python -m markets.pnl_tracker --no-open

# Skip data refresh (use existing parquet files)
python -m markets.pnl_tracker --skip-update
```

### CLI Options

| Arg | Default | Description |
|-----|---------|-------------|
| `--date` | today | Signal date (YYYY-MM-DD) |
| `--days` | 1 | Include last N days of signals |
| `--markets` | all | Filter by market (e.g. `BINANCE FX`) |
| `--reset` | false | Delete existing snapshot, create fresh baseline |
| `--skip-update` | false | Skip data refresh (use existing parquet files) |
| `--no-open` | false | Don't auto-open dashboard in browser |
| `--output` | `markets/output/signal_tracker.html` | Dashboard output path |

### Output

| File | Location | Description |
|------|----------|-------------|
| Snapshot | `markets/logs/tracker/YYYY-MM-DD.csv` | Persisted M/W/D regime state per symbol |
| Dashboard | `markets/output/signal_tracker.html` | HTML dark-theme with market grouping, filter, sort |

### Snapshot CSV columns

| Category | Fields |
|----------|--------|
| Identity | market, symbol, signal, scanned_at, snapshot_at |
| Monthly | m_status, m_trend, m_range_low, m_range_high, m_is_ready, m_ready_direction |
| Weekly | w_status, w_trend, w_range_low, w_range_high, w_is_ready, w_ready_direction |
| Daily | d_status, d_trend, d_range_low, d_range_high, d_is_ready, d_ready_direction |

---

## Single-market CLI

```bash
# Scan all FX symbols (auto-opens report in browser)
python -m markets.cli scan --market FX --all

# Scan without opening browser
python -m markets.cli scan --market VNSTOCK --all --no-open

# Scan one symbol
python -m markets.cli scan --market VNSTOCK --symbol VCB

# TPO chart
python -m markets.cli tpo --market COIN --symbol BTCUSDm

# View signal log
python -m markets.cli log --days 7
python -m markets.cli log --ready        # only READY signals
```

---

## Data Providers

### MT5-backed markets (FX, COMM, US_STOCK, COIN)

Data is stored in `data/mt5/{symbol}_{TF}.parquet`.
`sync_mt5_data()` fetches H4 + D1 + W1 and keeps them incremental.

### Binance

Data is stored in `data/binance/{symbol}_{TF}.parquet`.
On import, `BinanceDataProvider` auto-registers the directory:
```python
ParquetDataProvider.register_fallback(DATA_DIR, "H4")
```
`sync_binance_data()` downloads native H4 + D1 + W1 via ccxt.

### VNStock

Data is stored in `data/vnstock/{symbol}_D1.parquet`.
On import, `VNStockDataProvider` auto-registers:
```python
ParquetDataProvider.register_fallback(DATA_DIR, "D1")
```
`sync_vnstock_data()` applies a 60 s delay per symbol (API rate limit).
W1 / M1 data is derived at scan-time via `UnifiedDataProvider`'s resample step.

---

## Adding a New Market

1. **Create `markets/<name>/`** with:
   - `config.py` — `DATA_DIR`, symbol list
   - `downloader.py` — fetch from exchange / API → save parquet
   - `data_provider.py` — inherit `data_providers.base.BaseDataProvider`,
     call `ParquetDataProvider.register_fallback(DATA_DIR, stored_tf)` at import

2. **Register in `registry.py`**:
   ```python
   MarketRegistry.register("NEWMARKET", NewMarketDataProvider, symbols=[...])
   ```

3. **Add meta in `markets/daily_scan.py`**:
   ```python
   MARKET_META["NEWMARKET"] = {"label": "New Market", "color": "#xxxxxx"}
   DEFAULT_MARKETS.append("NEWMARKET")
   ```

4. **Add sync call in `markets/sync.py`** if the market needs a custom
   freshness strategy (otherwise `UnifiedDataProvider` handles it transparently).

---

## Key Design Rules

| Rule | Where enforced |
|------|---------------|
| NO resample in `data_providers/parquet_data_provider.py` | `UnifiedDataProvider.get_data()` step 3 |
| Market-specific paths NOT hardcoded in infra layer | `ParquetDataProvider.register_fallback()` |
| Single `BaseDataProvider` ABC | `data_providers/base.py` |
| All scanners use `UnifiedDataProvider` | `markets/base/scanner.py` |
