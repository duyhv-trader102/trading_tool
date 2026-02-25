# API Reference

> Last Updated: 2026-02-25

## Core APIs

### `core/tpo.py`
| Function/Class | Signature | Description |
|---|---|---|
| `TPOProfile` | class | TPO profile calculator |
| `TPOResult` | dataclass | Session metrics (POC, VAH, VAL, distribution, etc.) |
| `calc_block_size()` | `(max_range, target_rows=40)` | Dynamic tick sizing |

### `core/resampler.py`
| Function | Signature | Description |
|---|---|---|
| `resample_data()` | `(df, interval)` | Resample OHLC (H4->D1, D1->W1, etc.) |

### `core/session_splitter.py`
| Function | Signature | Description |
|---|---|---|
| `split_sessions()` | `(df, session_type)` | Split bars into D/W/M sessions |

### `core/ob.py`
| Function | Signature | Description |
|---|---|---|
| `find_all_ob()` | `(ohlc_data)` | Combined OB detection |
| `attach_mitigation_status()` | `(ohlc_data, obs)` | Track OB tests/breaks |

---

## Analysis APIs

### `analytic/tpo_mba/tracker.py`
| Function | Signature | Description |
|---|---|---|
| `build_mba_context()` | `(sessions, timeframe)` -> `MBAMetadata` | Top-level MBA analysis |
| `track_mba_evolution()` | `(sessions, regimes)` -> `MBAEvolution` | Multi-session MBA chain |
| `evaluate_mba_readiness()` | `(mba, sessions)` -> `MBAReadiness` | Readiness evaluation |
| `get_current_mba()` | `(sessions, regimes)` -> `MacroBalanceArea` | Get current MBA |
| `detect_mba_break()` | `(mba, session)` -> `bool` | Check MBA breakout |

### `analytic/tpo_mba/schema.py`
| Dataclass | Key Fields | Description |
|---|---|---|
| `MBAMetadata` | `mba`, `is_ready`, `ready_direction`, `ready_reason` | Full MBA context |
| `MacroBalanceArea` | `area_high`, `area_low`, `source`, `all_units` | MBA boundaries |
| `MBAUnit` | `area_high`, `area_low`, `uf_high`, `uf_low` | Single MBA unit |
| `MBAReadiness` | `is_ready`, `reason`, `direction` | Readiness result |

### `analytic/tpo_regime/schema.py`
| Dataclass | Key Fields | Description |
|---|---|---|
| `RegimeResult` | `regime`, `confidence`, `phase`, `direction` | Session regime |
| `RegimeFeatures` | POC, VA, distribution, responsive, etc. | Feature set |

### `analytic/tpo_confluence/tpo_alignment.py`
| Function | Description |
|---|---|
| TPO balance detection, IB extension analysis, MTF confluence resolution |

---

## Workflow APIs

### `workflow/pipeline.py`
| Function | Signature | Description |
|---|---|---|
| `get_data()` | `(symbol, tf, bars)` -> `DataFrame` | Fetch OHLC data |
| `analyze_from_df()` | `(df, session_type)` -> `(results, block_size)` | Build TPO sessions |
| `analyze_timeframe()` | `(symbol, tf_build, tf_session, n)` -> `result` | High-level analysis |
| `classify_regime()` | `(sessions)` -> `regimes` | Regime classification |

---

## EA APIs

### `EA/macro_trend_catcher/signals.py`
| Class | Key Methods | Description |
|---|---|---|
| `SignalGeneratorV2` | `evaluate_alignment()`, `generate_signal()`, `check_exit()` | Signal engine |
| `AlignmentState` | `is_aligned`, `direction`, `m/w/d_ready` | Alignment snapshot |
| `TrendSignalV2` | `symbol`, `direction`, `price`, `sl` | Entry signal |

### `EA/macro_trend_catcher/config.py`
| Export | Type | Description |
|---|---|---|
| `TrendCatcherV2Config` | dataclass | Strategy parameters |
| `FOREX_V2` | config | Forex-specific config |
| `COMMODITIES_V2` | config | Commodities config |
| `US_STOCKS_V2` | config | US stocks config |
| `CRYPTO_V2` | config | MT5 crypto config |
| `BINANCE_SPOT_V2` | config | Binance spot config |
| `BINANCE_SKIP_SYMBOLS` | set | Stablecoins/wrapped tokens to skip |
| `ASSET_CONFIG` | dict | Asset class -> config mapping |

### `EA/shared/indicators.py`
| Function | Signature | Description |
|---|---|---|
| `calculate_atr()` | `(df, period=14)` | ATR calculation |
| `calculate_adx()` | `(df, period=14)` | ADX calculation |
| `calculate_rsi()` | `(df, period=14)` | RSI calculation |
| `calculate_ema()` | `(df, period)` | Exponential MA |
| `calculate_sma()` | `(df, period)` | Simple MA |

### `EA/shared/rank_symbols.py`
| Function/Class | Signature | Description |
|---|---|---|
| `RankConfig` | frozen dataclass | Scoring weights, caps, sanity filters |
| `rank_symbols()` | `(batch_json, cfg, top_n, threshold)` -> `dict` | Score & rank symbols by HealthyTrendScore [0,1] |
| `save_rank_output()` | `(out, json_path, csv_path)` | Export JSON + CSV |
| `print_ranking()` | `(ranked, top_n)` | Console ranking table |
| `_healthy_score()` | `(row, return_cap, pf_cap, cfg)` -> `float` | Log-scale composite score |
| `_compute_caps()` | `(rows, cfg)` -> `(float, float)` | Auto p99 caps for return & PF |

### `EA/shared/backtest_utils.py`
| Class/Function | Description |
|---|---|
| `Trade` | Trade record dataclass |
| `BacktestMetrics` | Metrics dataclass |
| `calculate_metrics()` | Compute PF, Sharpe, drawdown, etc. |
| `print_metrics()` | Console output of metrics |
| `calculate_equity_curve()` | Equity curve from trades |

---

## Infrastructure APIs

### `infra/s3_storage.py`

**`S3Storage` class** (thin `boto3` wrapper, singleton via `get_s3()`):
| Method | Signature | Description |
|---|---|---|
| `upload_file()` | `(local_path, s3_key)` | `put_object(Body=bytes)` — no `upload_file()` |
| `download_file()` | `(s3_key, local_path)` | Download object to local |
| `list_files()` | `(prefix)` -> `List[str]` | List all keys under prefix |
| `file_exists()` | `(s3_key)` -> `bool` | HEAD check |
| `delete_file()` | `(s3_key)` | Delete object |
| `get_presigned_url()` | `(s3_key, expiry)` -> `str` | Presigned GET URL |

**Free functions:**
| Function | Signature | Description |
|---|---|---|
| `get_s3()` | `()` -> `S3Storage` | Singleton accessor |
| `smart_read_parquet()` | `(path)` -> `DataFrame` | Local if exists, else stream from S3 via `BytesIO` |
| `read_parquet_s3()` | `(s3_key)` -> `DataFrame` | Stream S3 object into `BytesIO`, no local write |
| `list_remote_files()` | `(subdir)` -> `List[str]` | List S3 keys in `data/{subdir}/` |
| `s3_dir_mtimes()` | `(data_subdir)` -> `Dict[str, float]` | `{filename: epoch_secs}` via single `list_objects_v2` |
| `ensure_local()` | `(path)` -> `Path` | Download from S3 if local missing |
| `ensure_dir_local()` | `(subdir)` | Download all files in S3 subdir to local |
| `publish_report()` | `(local_path)` -> `str` | Upload report + linked files to S3, return presigned URL |
| `open_report()` | `(date_str)` | Open presigned URL for date's dashboard |
| `upload_log()` | `(local_path, log_subdir)` | Upload CSV/JSON log to S3 reports prefix |
| `download_log()` | `(filename, log_subdir)` -> `Path` | Download log to local temp |
| `upload_log_dir()` | `(local_dir, log_subdir)` | Upload entire log directory |

> **Note:** All uploads use `put_object(Body=bytes)`. `upload_file()` causes `AwsChunkedWrapper stream not seekable` with custom endpoint + SigV4.

### `infra/signal_logger.py`
| Class/Function | Signature | Description |
|---|---|---|
| `SignalLogger` | class | Append-only CSV logger for scan results |
| `.log_scan_results()` | `(results, date_str, market)` | Append rows to `{market}_signals.csv` |
| `.load_aggregate()` | `(markets, days)` -> `DataFrame` | Load + concat recent signal CSVs |
| `.aggregate()` | `(df)` -> `DataFrame` | Deduplicate, rank, score |
| `upload_log()` | free fn | Upload CSV to S3 `reports/markets/logs/` |
| `download_log()` | free fn | Download CSV from S3 to local temp |

### `infra/parquet_manager.py`
| Function | Signature | Description |
|---|---|---|
| `fetch_and_store_data()` | `(symbol, tf, source)` | Fetch from API + write parquet + upload to S3 |
| `fetch_h1_and_resample()` | `(symbol, source)` | Fetch H1 → write H1/H4/D1/W1/M1 parquets + upload each to S3 |
| `update_parquet()` | `(symbol, tf)` | Incremental append + upload to S3 |
| `load_from_parquet()` | `(symbol, tf)` -> `pd.DataFrame` | Load via `smart_read_parquet()` (local/S3) |
| `load_from_parquet_polars()` | `(symbol, tf)` -> `pl.DataFrame` | Polars variant |

### `infra/mt5.py`
| Function | Signature | Description |
|---|---|---|
| `start_mt5()` | `(username, password, server, path)` | Initialize MT5 |
| `get_historical_data()` | `(symbol, timeframe, bars)` | Fetch OHLC |
| `get_tick_size()` | `(symbol)` | Symbol tick size |

---

## EA Risk APIs

### `EA/risk/circuit_breaker.py`
| Class/Method | Signature | Description |
|---|---|---|
| `CircuitBreaker` | dataclass | P&L limits + trailing drawdown halt |
| `.can_trade()` | `(current_equity, daily_pnl_pct, weekly_pnl_pct)` -> `bool` | Check if trading allowed |
| `.update_equity_peak()` | `(current_equity)` | Update HWM for trailing DD |
| `.reset()` | `()` | Clear halt state |

### `EA/risk/position_sizer.py`
| Class/Method | Signature | Description |
|---|---|---|
| `PositionSizer` | dataclass | Risk-based sizing (fixed fractional / volatility) |
| `.calculate()` | `(equity, stop_distance, pip_value, atr)` -> `float` | Compute lot size |
| `.max_position_value()` | `(equity)` -> `float` | Max notional for equity |

### `EA/risk/portfolio_guard.py`
| Class/Method | Signature | Description |
|---|---|---|
| `Position` | dataclass | `symbol`, `sector`, `notional`, `direction` |
| `PortfolioGuard` | dataclass | Max positions, sector concentration, exposure |
| `.can_add_position()` | `(symbol, sector, notional, equity, positions)` -> `bool` | Validate new position |
| `.summary()` | `(positions)` -> `Dict` | Portfolio exposure summary |

### `EA/risk/reconciler.py`
| Class/Method | Signature | Description |
|---|---|---|
| `DiffType` | Enum | PHANTOM, ORPHAN, SIZE_MISMATCH, PRICE_MISMATCH |
| `Reconciler` | class | EA vs broker state comparison |
| `.compare()` | `(ea_positions, broker_positions)` -> `List[ReconciliationDiff]` | Detect discrepancies |
| `.auto_resolve()` | `(diffs)` -> `List[str]` | Generate resolution actions |

---

## EA Shared APIs

### `EA/shared/market_filter.py`
| Class/Function | Signature | Description |
|---|---|---|
| `FilterConfig` | dataclass | Weights, tiers, hard filters |
| `ScoredSymbol` | dataclass | Symbol + composite score + sub-scores |
| `score_symbols()` | `(results, config)` -> `List[ScoredSymbol]` | Score & tier-classify symbols |
| `print_report()` | `(scored, config)` | Console report |
| `export_watchlist()` | `(scored, path)` | Export tiered JSON |

### `EA/shared/rank_symbols.py`
| Function | Signature | Description |
|---|---|---|
| `rank_symbols()` | `(batch_json, cfg, top_n, threshold)` -> `Dict` | HealthyTrendScore 0-1 |
| `save_rank_output()` | `(out, json_path, csv_path)` | Export JSON + CSV |
| `print_ranking()` | `(ranked, top_n)` | Console ranking table |

---

## Markets APIs

### `markets/sync.py`
| Function | Signature | Description |
|---|---|---|
| `sync_mt5_data()` | `(symbols)` | Check S3 mtimes → skip if fresh, else incremental update |
| `sync_vnstock_data()` | `(symbols)` | Check S3 mtimes → skip if fresh, else fetch from vnstock API |
| `sync_binance_data()` | `(symbols)` | Check S3 mtimes (H4 reference) → skip if fresh, else fetch from ccxt |

> All 3 functions call `s3_dir_mtimes()` before any API fetch. If S3 has fresh data and local is missing, only an incremental update is done — not a full re-fetch.

### `markets/registry.py`
| Class/Method | Signature | Description |
|---|---|---|
| `MarketRegistry` | class | Central routing table: market → provider + symbols |
| `.list_markets()` | `() -> List[str]` | All registered market names |
| `.get_provider(market)` | `(str) -> BaseDataProvider` | Provider instance for a market |
| `.get_symbols(market)` | `(str) -> List[str]` | Symbol list for a market |
| `.get_scanner(market)` | `(str) -> BaseScanner` | Scanner instance for a market |

### `markets/base/scanner.py`
| Class/Method | Signature | Description |
|---|---|---|
| `BaseScanner` | class | Abstract per-market scanner |
| `.analyze_symbol()` | `(symbol) -> dict` | Run MTF top-down analysis |
| `.scan_all()` | `() -> List[dict]` | Scan all market symbols |
| `.scan_group()` | `(group) -> List[dict]` | Scan a named symbol group |

### `markets/manager.py`
| Class/Method | Signature | Description |
|---|---|---|
| `MarketManager` | class | Orchestrates scan + chart + report pipeline |
| `.run_scan()` | `(market, symbols) -> List[dict]` | Run scan and save results |
| `.generate_charts()` | `(market, results) -> None` | Emit TPO HTML charts |
| `.generate_report()` | `(market, results) -> None` | Write HTML scan report |

### `markets/reporting.py`
| Function | Signature | Description |
|---|---|---|
| `build_html_report()` | `(results, market, output_path)` | Generate HTML scan report |
| `build_symbol_card()` | `(result) -> str` | HTML card for one symbol |

---

## Data Providers API

### `data_providers/unified_provider.py`
| Class/Method | Signature | Description |
|---|---|---|
| `UnifiedDataProvider` | class | Parquet-first, MT5-fallback provider |
| `.get_data()` | `(symbol, tf, bars) -> DataFrame` | Load OHLC data |
| `.available_symbols()` | `() -> List[str]` | Symbols with parquet files |

### `data_providers/parquet_data_provider.py`
| Class/Method | Signature | Description |
|---|---|---|
| `ParquetDataProvider` | class | Read-only Pandas parquet loader |
| `.get_data()` | `(symbol, tf, bars) -> DataFrame` | Load parquet; resample H4→D1/W1 |
| `.has_symbol()` | `(symbol) -> bool` | Check if parquet exists |

### `data_providers/mt5_data_provider.py`
| Class/Method | Signature | Description |
|---|---|---|
| `MT5DataProvider` | class | Live MT5 OHLC provider |
| `.get_data()` | `(symbol, tf, bars) -> DataFrame` | Fetch from MT5 terminal |

---

## Daily Scanner API

### `markets/daily_scan.py`
| Function | Signature | Description |
|---|---|---|
| `scan_market()` | `(market, output_dir, generate_charts) -> List[dict]` | Scan one market; each result has `chart_url` (S3 presigned) |
| `generate_combined_report()` | `(all_results, markets, output_path) -> None` | Build HTML dashboard with filter buttons |
| `main()` | CLI entry | `--markets`, `--skip-update`, `--universe-only`; uploads to S3, deletes local `base_dir` |

---

## Signal Tracker API

### `markets/pnl_tracker.py`
| Function | Signature | Description |
|---|---|---|
| `load_snapshot()` | `(date_str) -> Dict[str, Dict]` | Load snapshot CSV keyed by `MARKET:SYMBOL` |
| `save_snapshot()` | `(date_str, data)` | Save snapshot dict to CSV |
| `analyze_symbol_full()` | `(symbol, market) -> dict` | Fresh M/W/D analysis, returns flat dict |
| `build_tracker_data()` | `(signals, date_str) -> (snapshot, diff_rows)` | Build/update snapshot + produce diff rows |
| `print_terminal_report()` | `(rows, dates, is_first)` | Print grouped terminal report |
| `generate_dashboard()` | `(rows, dates, output_path, is_first) -> Path` | Generate HTML dashboard with market grouping |
| `main()` | CLI entry | `--date`, `--days`, `--markets`, `--reset`, `--no-open`, `--output` |

**Snapshot path:** `markets/logs/tracker/YYYY-MM-DD.csv`
**Dashboard path:** `markets/output/signal_tracker.html`

---

## Data Sources

| Source | Format | S3 Location | Count |
|---|---|---|---|
| VN Stocks | vnstock API → parquet | `market_regime_scanner/data/vnstock/` | On-demand |
| Binance Spot | H4 parquets | `market_regime_scanner/data/binance/` | 441 symbols |
| MT5 | H1 + resampled (H4/D1/W1/M1) parquets | `market_regime_scanner/data/mt5/` | 45 symbols |

> Local `data/` is a transient cache only. `smart_read_parquet()` reads local if present, else streams from S3.
