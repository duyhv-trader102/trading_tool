# Prop Firm-Grade Upgrade Roadmap

> Created: 2026-02-17
> Status: Planning
> Goal: Nâng hệ thống từ retail-grade lên prop firm-grade

---

## Current Assessment

| Area | Current | Prop Firm Target | Gap |
|:-----|:-------:|:----------------:|:---:|
| **Strategy** | 9/10 | 9/10 | OK |
| **Risk Management** | 4/10 | 8/10 | **Critical** |
| **Backtest Reliability** | 5/10 | 8/10 | High |
| **Testing** | 1/10 | 7/10 | High |
| **Infra Robustness** | 5/10 | 8/10 | Medium |

---

## Phase 1: Survival (1-2 tuần)

> *Mục tiêu: Không blow prop account*

### 1.1 Circuit Breaker — Daily & Total Drawdown

**File:** `EA/shared/risk_manager.py`

Prop firms enforce:
- **Daily DD limit**: 4-5% (FTMO = 5%)
- **Total DD limit**: 8-12% (FTMO = 10%)
- **Consecutive losses**: halt after N losses

```python
@dataclass
class CircuitBreaker:
    max_daily_dd_pct: float = 5.0
    max_total_dd_pct: float = 10.0
    max_consecutive_losses: int = 3
    
    def should_halt(self, equity_now, equity_start_of_day, equity_peak) -> bool
    def record_loss(self) -> None
    def reset_daily(self) -> None
```

**Integration:** Call `should_halt()` in `bot.py` before every new entry.

- [ ] Create `risk_manager.py`
- [ ] Integrate into `bot.py` main loop
- [ ] Add daily equity snapshot to state file
- [ ] Test with edge cases (gap down, multiple SL same day)

---

### 1.2 Fix Magic Number Mismatch

**Files:** `infra/mt5.py`, `EA/macro_trend_catcher/config.py`

**Problem:** `config.py` sets `MAGIC_NUMBER = 20260202` but `mt5.py` uses hardcoded `magic=123456`.
Bot cannot distinguish its own orders from manual trades or other EAs.

**Fix:** Wire `MAGIC_NUMBER` from config through to `place_order()` and `get_positions()`.

- [ ] Pass `magic` param to `place_order()` in `mt5.py`
- [ ] Filter `get_positions()` by magic number
- [ ] Verify bot only manages its own orders

---

### 1.3 Order Reconciliation

**File:** `bot.py` + `infra/mt5.py`

**Problem:** Bot's internal `positions_v2.json` can desync from MT5 actual positions
(manual close, broker-side SL, disconnection).

```python
class Reconciler:
    def sync(bot_state: dict, mt5_positions: list) -> List[Discrepancy]:
        # Detect: bot thinks open but MT5 closed (phantom)
        # Detect: MT5 open but bot doesn't know (orphan)
        # Auto-fix or alert
```

- [ ] Add reconciliation step at start of each bot cycle
- [ ] Log discrepancies
- [ ] Auto-remove phantom positions from state
- [ ] Alert on orphan positions

---

### 1.4 Telegram Alerting

**File:** `infra/alerting.py`

Events to alert:
- Entry / exit executed (symbol, direction, price, lot)
- DD breach warning (>3% daily)
- Circuit breaker triggered
- MT5 disconnect / reconnect
- Error in signal generation
- Daily equity summary

```python
class TelegramAlert:
    def __init__(self, token: str, chat_id: str)
    def send(self, event: str, details: dict) -> None
    def send_daily_summary(self, equity, dd, open_positions) -> None
```

- [ ] Create `alerting.py` with Telegram bot
- [ ] Add alert hooks in `bot.py`
- [ ] Add `.env` config for token/chat_id
- [ ] Test with dry-run mode

---

## Phase 2: Validation (2-3 tuần)

> *Mục tiêu: Biết chắc system có edge thật trên data chưa thấy*

### 2.1 Slippage + Commission trong Backtest

**File:** `EA/shared/cost_model.py`

```python
@dataclass
class CostModel:
    spread_pips: float = 2.0        # Crypto ~0.1%, Forex 1-3 pips
    commission_per_lot: float = 7.0  # Round-turn
    slippage_pips: float = 1.0
    
    def adjust_entry(self, price, direction) -> float
    def adjust_exit(self, price, direction) -> float
    def total_cost_usd(self, lots) -> float
```

Impact estimate: ~5-15% reduction in total return.

- [ ] Create `cost_model.py`
- [ ] Integrate into `backtest.py` and `backtest_binance.py`
- [ ] Re-run batch backtest with costs
- [ ] Compare results with/without costs

---

### 2.2 Compounding Equity Tracker

**File:** `EA/shared/backtest_utils.py`

**Problem:** Each trade return is independent. Real account compounds.

```python
class EquityTracker:
    def __init__(self, initial: float = 10_000):
        self.equity = initial
        self.peak = initial
        self.history: List[float] = [initial]
    
    def apply_trade(self, return_pct: float, risk_pct: float = 0.02) -> float
    def current_drawdown(self) -> float
    def max_drawdown(self) -> float
```

- [ ] Add `EquityTracker` to `backtest_utils.py`
- [ ] Update backtest to use compounding returns
- [ ] Report both simple and compounded metrics

---

### 2.3 Out-of-Sample Walk-Forward Validation

**File:** `EA/shared/walk_forward.py`

**Problem:** Parameters (SL mult, cooldown) evaluated on same data = curve-fitting risk.

```python
class WalkForwardValidator:
    n_folds: int = 5
    train_ratio: float = 0.7
    
    def split(self, data) -> List[Tuple[train, test]]
    def validate(self, strategy, data, param_grid) -> WFReport
    
@dataclass
class WFReport:
    in_sample_metrics: List[Metrics]
    out_of_sample_metrics: List[Metrics]
    degradation_pct: float  # OOS vs IS performance drop
    is_robust: bool         # degradation < 30%
```

- [ ] Create `walk_forward.py`
- [ ] Run WFA on current params (SL=3.0, cooldown=20)
- [ ] Report IS vs OOS degradation
- [ ] Determine if system is robust or overfit

---

### 2.4 Unit & Regression Tests

**Directory:** `tests/`

```
tests/
├── test_signals.py              # AlignmentState logic, entry/exit rules
├── test_backtest_utils.py       # Metrics: PF, Sharpe, DD calculation
├── test_indicators.py           # ATR, lot sizing edge cases
├── test_backtest_regression.py  # Golden file: fixed data → exact trade count + metrics
├── test_data_integrity.py       # Parquet validation (columns, gaps, timestamps)
├── test_risk_manager.py         # Circuit breaker, reconciliation
├── conftest.py                  # Shared fixtures
```

- [ ] Set up pytest framework
- [ ] Write tests for signal generation
- [ ] Write regression test with golden backtest output
- [ ] Write edge-case tests (zero ATR, empty sessions, missing data)
- [ ] Achieve >80% coverage on core logic

---

### 2.5 Portfolio Correlation Guard

**File:** `EA/shared/risk_manager.py`

**Problem:** 10 concurrent trades can all be correlated (e.g., 7 forex pairs = 1 USD trade).

```python
class PortfolioRiskManager:
    max_correlation: float = 0.7
    max_positions_per_class: int = 3
    
    def check_correlation(self, new_symbol, existing_positions) -> bool
    def get_portfolio_exposure(self, positions) -> Dict[str, float]
```

- [ ] Add correlation check before entry
- [ ] Add per-asset-class position limits
- [ ] Pre-compute correlation matrix for all symbols
- [ ] Log rejection reasons

---

## Phase 3: Edge Optimization (3-4 tuần)

> *Mục tiêu: Extract maximum alpha từ system đã validated*

### 3.1 Regime-Aware Position Sizing

**Files:** `signals.py`, `EA/shared/risk_manager.py`

System đã có regime detection nhưng chỉ dùng cho entry signals, không dùng cho sizing.

```python
class RegimeAwarePositionSizer:
    base_risk_pct: float = 2.0
    
    def size(self, regime: str, vol_rank: float, portfolio_dd: float) -> float:
        # High conviction + low vol → 2.5%
        # Normal → 2.0%
        # High vol or portfolio DD > 3% → 1.0%
        # Circuit breaker proximity → 0.5%
```

- [ ] Create regime-to-risk mapping
- [ ] Integrate vol_rank (ATR percentile rank)
- [ ] Backtest impact of dynamic sizing vs fixed 2%

---

### 3.2 PnL Attribution

**File:** `viz/attribution.py`

Answer: *Where is the alpha coming from?*

```python
def attribute_pnl(trades: List[Trade]) -> AttributionReport:
    # Breakdown by:
    #   - Asset class (Forex, Crypto, Commodities, Stocks)
    #   - Direction (Long vs Short)
    #   - Regime type at entry (Balance vs Imbalance)
    #   - Month / Quarter
    #   - Hold duration bucket
```

- [ ] Create attribution analysis
- [ ] Generate visual report (bar charts, heatmap)
- [ ] Identify strongest/weakest segments

---

### 3.3 Rolling Performance Monitor

**File:** `analytic/performance/rolling_monitor.py`

Detect strategy degradation in real-time.

```python
class RollingMonitor:
    window: int = 30  # trades
    
    def calculate(self, trades) -> List[RollingMetrics]:
        # PF, Sharpe, WR, avg_return per rolling window
    
    def detect_degradation(self, metrics) -> bool:
        # Alert if rolling PF < 1.0 or Sharpe < 0 for 2 consecutive windows
```

- [ ] Create rolling metrics calculator
- [ ] Add degradation detection
- [ ] Integrate alert when strategy underperforms

---

### 3.4 Multi-Symbol Portfolio Backtest

**File:** `EA/shared/portfolio_backtest.py`

**Problem:** Binance batch runs symbols independently. No portfolio-level DD or
concurrent position tracking.

```python
class PortfolioBacktest:
    max_positions: int = 10
    initial_equity: float = 10_000
    
    def run(self, symbols, config) -> PortfolioMetrics:
        # Chronological merge of all signals
        # Respect max_positions globally
        # Track portfolio equity curve
        # Report portfolio DD, not per-symbol DD
```

- [ ] Create portfolio-level backtest engine
- [ ] Merge signals chronologically across symbols
- [ ] Track concurrent positions + portfolio equity
- [ ] Compare portfolio DD vs sum-of-individual DDs

---

## Priority Matrix

```
Impact ↑
    │
    │  P0: Circuit Breaker    P1: Portfolio Correlation
    │  P0: Slippage/Costs     P1: Unit Tests
    │  P0: Magic Number Fix   P1: Order Reconciliation
    │
    │  P2: Walk-Forward       P2: Compounding Equity
    │  P2: Telegram Alerts    
    │
    │  P3: Regime Sizing      P3: PnL Attribution
    │  P3: Rolling Monitor    P3: Portfolio Backtest
    │
    └──────────────────────────────── Effort →
         Low                          High
```

---

## Success Criteria

| Milestone | Metric | Target |
|:----------|:-------|:-------|
| Phase 1 complete | Can pass FTMO challenge rules | Daily DD < 5%, Total DD < 10% enforced |
| Phase 2 complete | OOS validation positive | IS/OOS degradation < 30% |
| Phase 2 complete | Test coverage | > 80% on core logic |
| Phase 2 complete | Realistic backtest | Costs included, compounding, Sharpe recalculated |
| Phase 3 complete | Alpha source identified | PnL attribution by asset/regime/direction |
| Phase 3 complete | Portfolio-level metrics | Portfolio Sharpe > 1.0, Portfolio DD < 25% |

---

## References

- FTMO Rules: 5% daily DD, 10% total DD, 80% profit split
- The5ers: 4% daily DD, 6% total DD
- MFF: 5% daily DD, 12% total DD
- Topstep: $2K daily loss limit on $50K account (4%)

---

*"Strategy is the easy part. Risk management is what separates survivors from statistics."*
