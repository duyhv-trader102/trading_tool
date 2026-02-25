# EA — Expert Advisor Framework

> Last Updated: 2026-02-17

## Overview

`EA/` chứa toàn bộ hệ thống giao dịch tự động (Expert Advisors) — từ signal generation, risk management, backtesting đến live execution. Kiến trúc module hóa cho phép phát triển nhiều strategy song song với shared infrastructure.

**Core Philosophy:**
- Market chỉ có 2 trạng thái: **Balance** và **Imbalance**
- Entry khi cả 3 TF (Monthly/Weekly/Daily) đồng thuận về hướng (MBA alignment)
- Risk-first approach: circuit breaker, position sizing, portfolio guard

---

## Architecture

```
EA/
├── alpha/                    # Signal generation facade (re-exports)
│   ├── regime/                   # MBA/TPO regime detection
│   ├── signals/                  # Signal generators + indicators
│   └── universe/                 # Symbol universe config
│
├── analytics/                # Research, scoring, validation
│   ├── scoring/                  # Market filter + HealthyTrendScore
│   ├── validation/               # Trade metrics + equity curve
│   ├── attribution/              # [Phase 2] Factor analysis
│   └── monitoring/               # [Phase 3] Equity alerts
│
├── risk/                     # Capital preservation
│   ├── circuit_breaker.py        # P&L drawdown halts (prop firm)
│   ├── position_sizer.py         # Risk-based lot sizing
│   ├── portfolio_guard.py        # Exposure constraints
│   └── reconciler.py             # EA vs broker reconciliation
│
├── portfolio/                # [Phase 2] Portfolio-level backtest
│   └── portfolio_backtest.py     # Multi-strategy allocation
│
├── infra/                    # [Phase 3] Execution infrastructure
│                                 # MT5 connector, Telegram, scheduler
│
├── shared/                   # Cross-cutting utilities
│   ├── indicators.py             # ATR, ADX, RSI, EMA, SMA, Bollinger
│   ├── backtest_utils.py         # Trade, BacktestMetrics, equity curve
│   ├── market_filter.py          # Tiered symbol scoring (0-100)
│   ├── rank_symbols.py           # HealthyTrendScore (0-1)
│   └── filters/                  # [Reserved] Custom filter modules
│
├── macro_trend_catcher/      # Strategy: Top-Down MBA Alignment
│   ├── v1/                       # V1 Legacy baseline
│   ├── v2/                       # V2/V2.1 Active (compression gate)
│   └── docs/                     # Strategy-specific docs
│
├── macro_balance_scalper/    # Strategy: MBA Range Bounce
│   ├── strategy.py               # V1 swing (21-day hold)
│   ├── strategy_v2.py            # V2 scalp (72-hour hold)
│   └── manager.py                # Order execution + state
│
├── tests/                    # EA test suite
│   ├── test_risk.py              # 12 tests (CB, sizer, guard, reconciler)
│   └── conftest.py               # Shared fixtures
│
├── data/                     # Runtime state
│   └── ea_state_v2.json          # Position persistence
│
└── docs/                     # This documentation
```

---

## Module Dependency Graph

```
EA.alpha.signals ──re-exports──→ EA.macro_trend_catcher.signals
                                           │
EA.alpha.universe ─re-exports──→ EA.macro_trend_catcher.config
                                           │
EA.alpha.regime ───re-exports──→ analytic.tpo_mba.tracker
                                           │
EA.analytics.scoring ──────────→ EA.shared.market_filter
                                 EA.shared.rank_symbols
                                           │
EA.analytics.validation ───────→ EA.shared.backtest_utils
                                           │
EA.risk.* ─────── standalone (no external deps)
EA.portfolio.* ─── skeleton (depends on risk/ + analytics/)
EA.infra.* ──────── placeholder
```

**Layer Rules:**
- `shared/` → Không phụ thuộc vào strategy cụ thể
- `alpha/` → Re-export facade, không chứa logic mới
- `risk/` → Standalone, không phụ thuộc vào signal hay strategy
- Strategy (`macro_trend_catcher/`, `macro_balance_scalper/`) → Import từ `shared/`, `analytic/`, `core/`

---

## Strategies

### 1. Macro Trend Catcher (Active)

**Market Type:** Trending (Imbalance phase)
**Hold Time:** Swing (avg 54 days)
**Direction:** Follows Monthly MBA direction

| Version | Status | Key Feature |
|---------|--------|-------------|
| V1 | Legacy | Pure M/W/D alignment, no filters |
| V2 | Active | MBA readiness + cooldown + price validation |
| V2.1 | Active | V2 + Compression Gate (Normal/Neutral/3-1-3) |

**Entry:** Monthly MBA ready → Weekly aligned → Daily aligned → ENTER
**Exit:** Monthly direction flip or stop-loss (3x ATR)

> Chi tiết: xem [macro_trend_catcher/docs/README.md](../macro_trend_catcher/docs/README.md)

### 2. Macro Balance Scalper

**Market Type:** Ranging (Balance phase)
**Hold Time:** V1 Swing (21 days max) / V2 Scalp (72 hours max)
**Direction:** Counter-trend bounces within MBA range

**Entry:** Price tại biên MBA (±0.5%) + Monthly MBA established (≥3 sessions)
**Exit:** Touch opposite MBA edge (TP) hoặc break qua MBA edge (SL)

---

## Risk Management

### Circuit Breaker (`risk/circuit_breaker.py`)

Prop firm compliant drawdown monitoring:

| Limit | Default | Description |
|---|---|---|
| Daily limit | 4% | Max daily loss before halt |
| Weekly limit | 8% | Max weekly loss before halt |
| Trailing DD | 10% | Max drawdown from equity peak |
| Cool-off | 30 min | Minimum pause after halt |

```python
from EA.risk.circuit_breaker import CircuitBreaker

cb = CircuitBreaker(daily_limit_pct=4.0, trailing_dd_pct=10.0)
if cb.can_trade(equity, daily_pnl, weekly_pnl):
    # proceed with entry
```

### Position Sizer (`risk/position_sizer.py`)

Fixed fractional sizing with volatility adjustment:

```python
from EA.risk.position_sizer import PositionSizer

sizer = PositionSizer(risk_pct=1.0, prop_mode=True)
lot = sizer.calculate(equity=50_000, stop_distance=150, pip_value=10)
```

| Mode | Logic |
|---|---|
| Normal | `risk_pct × equity / (stop_distance × pip_value)` |
| Prop | Uses `max_risk_pct_prop` (default 0.5%) — tighter for challenge |
| Vol-adjusted | Factor in ATR when provided |

### Portfolio Guard (`risk/portfolio_guard.py`)

Portfolio-level exposure constraints:

| Constraint | Default | Description |
|---|---|---|
| Max positions | 5 | Total concurrent positions |
| Max sector % | 40% | Single sector concentration limit |
| Max exposure | 300% | Total notional / equity |
| Max correlated | 2 | Same-sector concurrent positions |

### Reconciler (`risk/reconciler.py`)

Detects discrepancies between EA internal state and broker positions:

| Diff Type | Meaning | Auto-resolution |
|---|---|---|
| PHANTOM | EA thinks position exists, broker doesn't | Remove from EA state |
| ORPHAN | Broker has position, EA doesn't know | Alert for manual review |
| SIZE_MISMATCH | Position sizes differ | Alert with details |
| PRICE_MISMATCH | Entry prices differ | Log for investigation |

---

## Shared Utilities

### Indicators (`shared/indicators.py`)

| Function | Signature | Returns |
|---|---|---|
| `calculate_atr()` | `(highs, lows, closes, period=14)` | `float` |
| `calculate_adx()` | `(highs, lows, closes, period=14)` | `float` (0-100) |
| `calculate_rsi()` | `(closes, period=14)` | `float` (0-100) |
| `calculate_ema()` | `(values, period)` | `List[float]` |
| `calculate_sma()` | `(values, period)` | `List[float]` |
| `calculate_bollinger_bands()` | `(closes, period=20, std_dev=2.0)` | `(upper, middle, lower)` |

### Backtest Utils (`shared/backtest_utils.py`)

```python
from EA.shared.backtest_utils import Trade, calculate_metrics, calculate_equity_curve

# Trade dataclass
trade = Trade(entry_time=..., exit_time=..., direction='long',
              entry_price=100, exit_price=120, exit_reason='direction_flip')

# Calculate metrics
metrics = calculate_metrics(trades, annual_periods=252)
# -> BacktestMetrics(total_trades, wins, win_rate, profit_factor, sharpe, max_dd, ...)

# Equity curve
curve = calculate_equity_curve(trades, initial_equity=100)
# -> [{'time': ..., 'equity': ..., 'drawdown': ...}, ...]
```

### Market Filter (`shared/market_filter.py`)

Composite scoring with 6 dimensions → 4-tier classification:

| Dimension | Weight | Scoring Logic |
|---|---|---|
| Return/Year | 25% | Annualized profitability |
| Profit Factor | 25% | Reward-to-risk ratio |
| Sharpe Ratio | 20% | Risk-adjusted consistency |
| Win Rate | 10% | Hit rate |
| Trade Count | 10% | Statistical confidence |
| Drawdown Risk | 10% | Capital preservation (inverted) |

**Tiers:** Elite ≥70 | Strong ≥50 | Watch ≥35 | Rejected <35

**Hard Filters:** trades ≥7, data ≥3y, PF ≥1.3, DD ≤95%

### Rank Symbols (`shared/rank_symbols.py`)

Lightweight alternative with log-scale scoring → HealthyTrendScore [0, 1]:

| Dimension | Weight | Normalization |
|---|---|---|
| Return | 30% | Log-scale, p99 cap |
| Profit Factor | 25% | Linear, PF=1 baseline |
| Drawdown | 20% | Inverted (lower = better) |
| Consistency | 15% | trades / 10 |
| Longevity | 10% | years / 8 |

---

## Running

### Prerequisites

```powershell
cd D:\code\trading_tool\python\market_regime_scanner
& D:\code\trading_tool\.venv\Scripts\Activate.ps1
pip install -e .
```

> **Important:** EA modules are NOT in `setuptools.packages.find`.
> Always run from project root using `python -m EA.xxx`.

### Common Commands

```powershell
# -- Backtest (single symbol, MT5) --
python -m EA.macro_trend_catcher.backtest --symbol XAUUSDm --years 3

# -- Backtest (batch Binance spot) --
python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0

# -- Backtest (with compression gate + trade logging) --
python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0

# -- Live Bot --
python -m EA.macro_trend_catcher.bot --dry-run --once

# -- Tests --
python -m pytest EA/tests/test_risk.py -v
```

### Key Output Files

| File | Location | Content |
|---|---|---|
| Backtest results | `macro_trend_catcher/reports/` | Per-symbol JSON metrics |
| Watchlist | `macro_trend_catcher/reports/spot_v21_watchlist.json` | Tiered symbol list |
| Ranking | `macro_trend_catcher/reports/spot_v21_ranked_top50.json` | HealthyTrendScore |
| Trade log | `macro_trend_catcher/reports/v21_trade_log.csv` | 35 fields per trade |
| Summary report | `macro_trend_catcher/reports/v21_summary_report.txt` | Aggregate statistics |
| EA state | `data/ea_state_v2.json` | Live bot position state |
| Bot logs | `macro_trend_catcher/logs/` | Activity logs |

---

## Development Roadmap

| Phase | Status | Modules |
|---|---|---|
| Phase 1: Core | ✅ Done | `shared/`, `risk/`, `macro_trend_catcher/v1-v2.1`, `tests/` |
| Phase 2: Analytics | 🔄 Partial | `analytics/scoring` ✅, `attribution` ⬜, `portfolio` ⬜ |
| Phase 3: Infra | ⬜ Planned | `infra/` (MT5 connector, Telegram, scheduler) |

---

## Related Documentation

| Doc | Location | Content |
|---|---|---|
| Project Architecture | `docs/technical/Project_Architecture.md` | Full system structure |
| API Reference | `docs/api_list.md` | All public APIs |
| TF Confluence Logic | `docs/technical/TF_Confluence_Logic.md` | Nested gating rules + V2.1 |
| TPO Logic Master | `docs/technical/TPO_Logic_Master.md` | Full TPO/MBA logic |
| Market States Theory | `docs/concepts/Market_States_Theory.md` | Trading theory foundation |
| Trend Catcher Details | `macro_trend_catcher/docs/README.md` | Strategy-specific docs |
