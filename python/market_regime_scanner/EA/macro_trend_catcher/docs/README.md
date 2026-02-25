# Macro Trend Catcher EA

**Version:** V3 (Convergence Signal + Breakout Ready)
**Last Updated:** February 2026
**Language:** Python + MT5 / Binance

## Overview

Macro Trend Catcher là một Expert Advisor (EA) tự động giao dịch dựa trên chiến lược **Multi-Timeframe MBA Alignment**. EA phân tích cấu trúc thị trường (Market Profile / TPO / MBA) trên 3 khung thời gian (Monthly → Weekly → Daily) và chỉ vào lệnh khi tất cả đều **ready** và đồng thuận về hướng đi.

## Versions

| Version | Folder | Status | Mô tả |
|---------|--------|--------|-------|
| **V1** | `v1/` | Legacy | Baseline — pure M/W/D alignment, no filters |
| **V2** | `v2/` | Legacy | MBA readiness + cooldown + price validation + market filter |
| **V2.1** | `v2/` | Legacy | V2 + Compression Gate trên cả 3 TF |
| **V3** | `v2/` | **Active** | V2.1 + Convergence signal (`evaluate_overall_signal`) + Breakout-ready gate |

## V3 Strategy (Current)

### Entry Logic

```
[V3] evaluate_overall_signal():
  1M session MBA ready  ⇒  direction (anchor)
  1W session MBA ready  +  same direction as 1M
  1D session MBA ready  +  same direction as 1W
  Convergence score > threshold  AND  breakout_ready == True  ⇒  ENTER
```

V3 bổ sung 2 điều kiện so với V2.1:
- **Convergence signal** (`evaluate_overall_signal`): tổng hợp MBA alignment + price position score
- **Breakout-ready gate**: D session phải sẵn sàng breakout (VAH/VAL test + close confirmation)

## V2 Strategy (Legacy)

### Entry Logic

```
1M session MBA ready  ⇒  direction (anchor)
1W session MBA ready  +  same direction as 1M
1D session MBA ready  +  same direction as 1W  ⇒  ENTER
```

MBA readiness được xác định bởi `build_mba_context()` từ `analytic.tpo_mba.tracker`, bao gồm:
- Phát hiện Mother Bar Area (MBA) origin
- Theo dõi evolution: balance, shift, breakout
- 3-1-3 readiness evaluation (VA dominance + close price confirmation)
- Direction override với latest close

### V2.1 Compression Gate

V2.1 thêm một layer lọc nữa: **session cuối cùng** trên mỗi TF phải ở trạng thái **compressed** (nén) thì mới cho phép entry.

| Session Type | Compressed? | Logic |
|---|---|---|
| Normal | ✅ Yes | Range hẹp, không IB extension — compression chuẩn |
| Neutral | ✅ Yes | Sweep hai hướng — giá đã thăm dò xong, đang ổn định |
| 3-1-3 (no minus dev) | ✅ Yes | Distribution cycle hoàn tất |
| Normal Variation | ❌ No | IB extension >20% — vẫn đang mở rộng |
| Trend Day | ❌ No | Directional move mạnh — chưa nén |

### Timeframe Mapping

Session lớn được build từ bars nhỏ hơn để giảm noise:

| Session Type | Bar TF | Bars/Session | Purpose |
|---|---|---|---|
| Monthly | W1 | ≈4-5 | Macro trend anchor |
| Weekly | D1 | ≈5 | Intermediate trend |
| Daily | H4 | ≈6 | Entry trigger |

### Entry Filters

1. **Price-direction consistency**: Price phải nằm trong MBA range trên tất cả TFs
2. **MBA continuity**: Configurable minimum sessions since mother (default=0)
3. **Cooldown**: Sau stop-loss, block same-direction re-entry N ngày (default=20)

### Exit Logic

- **Monthly direction flip**: Monthly MBA ready ngược chiều → close
- **Stop-loss**: Fixed ATR-based (default 3x ATR), không trailing

## V2 Architecture

```
EA/macro_trend_catcher/
├── config.py                   # Strategy params, asset universe, paths
├── signals.py                  # AlignmentState, SignalGeneratorV2, entry/exit logic
├── bot.py                      # Live MT5 trading bot (schedule loop)
├── backtest.py                 # Single-symbol MT5 walk-forward backtest (require_compression param)
├── backtest_binance.py         # Batch backtest on Binance spot H4 parquets
├── backtest_spot.py            # LONG-only spot backtest (Binance)
├── backtest_spot_v21.py        # V2.1 spot backtest with compression gate
├── backtest_v21_detailed.py    # V2.1 with per-trade CSV/JSON logging (35 fields)
├── __init__.py                 # Package exports
├── reports/
│   ├── v3_4scenarios/          # V3 4-scenario full comparison (261 Binance symbols)
│   │   ├── scenario_A_trade_log.csv/json   # 1277 trades
│   │   ├── scenario_B_trade_log.csv/json   # 1220 trades
│   │   ├── scenario_C_trade_log.csv/json   # 1019 trades
│   │   ├── scenario_D_trade_log.csv/json   #  985 trades
│   │   ├── comparison_report.txt
│   │   └── portfolio_summary.json
│   ├── spot_v21_backtest_results.json
│   ├── spot_v21_watchlist.json
│   ├── spot_v21_ranked_top50.json / .csv
│   ├── v21_trade_log.csv / .json
│   └── v21_summary_report.txt
├── state/                      # Position state persistence
└── logs/                       # Bot activity logs
```

Scripts:
```
scripts/research/
└── binance_v3_4scenarios.py    # V3 4-scenario runner (--all, --workers, --scenarios)
```

### Dependencies

| Module | Purpose |
|---|---|
| `analytic.tpo_mba.tracker` | `build_mba_context()` → MBAMetadata |
| `core.tpo` | TPOProfile — builds sessions from OHLC bars |
| `core.resampler` | `resample_data()` — H4 → D1/W1 (Binance only) |
| `EA.shared.indicators` | `calculate_atr()` |
| `EA.shared.backtest_utils` | `Trade`, `calculate_metrics()` || `EA.shared.market_filter` | `score_symbols()`, `export_watchlist()` |
| `EA.shared.rank_symbols` | `rank_symbols()`, `save_rank_output()` || `infra.data.mt5_provider` | MT5 data fetching (bot & backtest) |
| `workflow.pipeline` | `analyze_timeframe()` (bot only) |

## Configuration

### Per-Asset Class

| Asset Class | SL Multiplier | Config |
|---|---|---|
| Forex | 3.0x ATR | `FOREX_V2` |
| Commodities | 3.0x ATR | `COMMODITIES_V2` |
| US Stocks | 3.5x ATR | `US_STOCKS_V2` |
| Crypto (MT5) | 2.5x ATR | `CRYPTO_V2` |
| Binance Spot | 3.0x ATR | `BINANCE_SPOT_V2` |

### Key Parameters

| Parameter | Default | Description |
|---|---|---|
| `initial_stop_atr_mult` | 3.0 | SL = price ± N × ATR |
| `atr_period` | 14 | ATR calculation period |
| `risk_per_trade_pct` | 2.0 | % equity risked per trade |
| `max_positions` | 10 | Max concurrent positions |
| `cooldown_days` | 20 | Days blocked after SL hit |
| `min_mba_continuity` | 0 | Min MBA sessions since mother |

## Quick Start

```powershell
cd D:\code\trading_tool\python\market_regime_scanner

# -- V3 4-Scenario Backtest (Binance Spot, all 261 symbols) --
python -X utf8 scripts/research/binance_v3_4scenarios.py --all --workers 1
python -X utf8 scripts/research/binance_v3_4scenarios.py --all --scenarios C D   # filter only
python -X utf8 scripts/research/binance_v3_4scenarios.py --symbols BTC ETH BNB --scenarios A B C D

# -- Single Symbol Backtest (MT5) --
python -m EA.macro_trend_catcher.backtest --symbol XAUUSDm --years 3
python -m EA.macro_trend_catcher.backtest --symbol BTCUSDm --sl-mult 2.5

# -- Market Filter (score & rank - tiered watchlist) --
python -m EA.shared.market_filter
python -m EA.shared.market_filter --min-trades 8 --min-pf 1.5

# -- Symbol Ranker (lightweight log-scale scoring) --
python -m EA.shared.rank_symbols
python -m EA.shared.rank_symbols --top 50 --min-trades 8

# -- Live Bot --
python -m EA.macro_trend_catcher.bot --dry-run --once   # Test
python -m EA.macro_trend_catcher.bot                     # Live
python -m EA.macro_trend_catcher.bot --assets FOREX_MAJORS COMMODITIES
```

## CLI Options

```
# binance_v3_4scenarios.py
--all              Use all 261 Binance symbols with ≥2 years data
--symbols          Manual symbol list (e.g., BTC ETH BNB)
--scenarios        Scenarios to run: A B C D (default: all 4)
--workers          ThreadPool size (default: 1, use 1 to avoid lag)
--min-years        Min years of data filter (default: 2)

# bot.py
--dry-run          No real trades (simulation mode)
--once             Run once then exit
--assets           Specific asset classes (e.g., FOREX_MAJORS US_TECH_STOCKS)
--interval         Check interval in hours (default: 4)
--symbol           Symbol for single backtest (default: XAUUSDm)
--years            Years of history (default: 3)
--sl-mult          Stop-loss ATR multiplier (default: 3.0)
--cooldown         Cooldown days after SL (default: 20)
--min-trades       Minimum trades for market filter (default: 7)
--min-pf           Minimum profit factor for filter (default: 1.3)
--export           Export watchlist path (default: reports/watchlist.json)
```

## Symbol Ranking Tools

Có 2 công cụ ranking song song:

### 1. Market Filter (`market_filter.py`) — Tiered Watchlist

Đánh giá 259 Binance spot symbols và xếp hạng theo composite score (0-100):

| Dimension | Weight | Meaning |
|---|---|---|
| Return/Year | 25% | Annualized profitability |
| Profit Factor | 25% | Reward-to-risk ratio |
| Sharpe Ratio | 20% | Risk-adjusted consistency |
| Win Rate | 10% | Hit rate |
| Trade Count | 10% | Statistical confidence |
| Drawdown Risk | 10% | Capital preservation (inverted) |

### Tier System

| Tier | Score | Action |
|---|---|---|
| **Tier 1 (Elite)** | ≥ 70 | Full conviction |
| **Tier 2 (Strong)** | ≥ 50 | Normal size |
| **Tier 3 (Watch)** | ≥ 35 | Monitor, small size |
| **Rejected** | < 35 | Don't trade |

### Latest Results — V3 Backtest (261 Binance Spot, ≥2 years H4 data)

**Test config:** Signal V3, LONG-ONLY, $10,000 start, 1% risk/trade, fee 0.1%/side, SL=3×ATR, cooldown=20d

#### 4-Scenario Comparison (Portfolio — fixed-fractional 1%)

| Scenario | Label | Trades | Sym | WR% | PF | Sharpe | Acct End | P&L% | MaxDD% | RRR | Fees$ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **A** | No Filter + Hard SL | 1,277 | 250 | 35.2% | 1.13 | 0.64 | $2,042,966 | +20,330% | 81.6% | 2.07 | $368,662 |
| **B** | No Filter + Soft SL | 1,220 | 198 | 39.8% | 1.10 | 0.50 | $4,709,926 | +46,999% | 84.7% | 1.66 | $904,045 |
| **C** | With Filter + Hard SL | 1,019 | 180 | 36.9% | 1.27 | **1.17** | $2,122,684 | +21,127% | **66.8%** | **2.18** | $190,391 |
| **D** | With Filter + Soft SL | 985 | 177 | 41.2% | 1.21 | 0.92 | $4,469,480 | +44,595% | 72.3% | 1.72 | $429,421 |

> **Recommendation:** Scenario **C** cho Sharpe cao nhất (1.17) và MaxDD thấp nhất (66.8%) — tốt nhất về risk-adjusted. Scenario **D** cho P&L cao hơn C với MaxDD trung bình (72.3%).

#### Exit Breakdown

| Scenario | direction_flip | stop_loss | end_of_backtest |
|---|---|---|---|
| A | 68.9% | 30.9% | 0.2% |
| B | 98.3% | — | 1.7% |
| C | 70.3% | 29.7% | — |
| D | 99.5% | — | 0.5% |

#### Top Symbols by Cumulative Net Return

| Rank | Scenario A | Scenario B | Scenario C | Scenario D |
|---|---|---|---|---|
| 1 | ONE +2034% | ANKR +7309% | ANKR +3631% | ANKR +7309% |
| 2 | ANKR +1236% | AVAX +2483% | ONE +2982% | ONE +3631% |
| 3 | AVAX +1070% | ONE +2066% | AXS +1761% | AVAX +2483% |
| 4 | THETA +1065% | AXS +1761% | AR +1480% | ETH +1771% |
| 5 | OM +1044% | BNB +1620% | AVAX +1053% | AXS +1761% |

### 2. Rank Symbols (`rank_symbols.py`) — HealthyTrendScore

Lightweight alternative với log-scale scoring, output JSON + CSV:

| Dimension | Weight | Normalization |
|---|---|---|
| Return | 30% | Log-scale, p99 cap |
| Profit Factor | 25% | Linear, PF=1 baseline |
| Drawdown | 20% | Inverted (lower = better) |
| Consistency | 15% | trades / 10 |
| Longevity | 10% | years / 8 |

Score range: 0.0 - 1.0. Filters: min 5 trades, 4+ years data, DD ≤ 80%.

```powershell
python -m EA.shared.rank_symbols                # Default top 30
python -m EA.shared.rank_symbols --top 50       # Top 50
python -m EA.shared.rank_symbols --threshold 0.6  # Score ≥ 0.6 only
```

## MT5 Supported Assets

- **FOREX_MAJORS**: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD
- **FOREX_CROSSES**: GBPJPY, EURJPY, EURGBP, AUDJPY, CADJPY, CHFJPY, GBPAUD, EURAUD
- **COMMODITIES**: XAUUSD, XAGUSD, USOIL, UKOIL, XCUUSD, XPTUSD
- **US_INDICES**: US500, US100, US30, USTEC
- **US_TECH_STOCKS**: NVDA, AAPL, MSFT, GOOGL, AMZN, TSLA, META, AMD
- **US_OTHER_STOCKS**: JPM, BA, XOM, JNJ, V, WMT, KO, DIS
- **CRYPTO**: BTC, ETH, SOL, XRP, BNB, LTC

## Risk Warning

Trading involves significant risk of loss. Past performance does not guarantee future results.
Always test on demo account before live trading.
