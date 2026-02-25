# Risk Management

> Last Updated: 2026-02-17

Tài liệu chi tiết về hệ thống risk management trong `EA/risk/`.

---

## Overview

4 module hoạt động độc lập, bảo vệ vốn ở 4 tầng khác nhau:

```
┌──────────────────────────────────────────────┐
│  Portfolio Guard  — exposure constraints      │
├──────────────────────────────────────────────┤
│  Circuit Breaker  — drawdown halt             │
├──────────────────────────────────────────────┤
│  Position Sizer   — lot sizing                │
├──────────────────────────────────────────────┤
│  Reconciler       — state consistency         │
└──────────────────────────────────────────────┘
```

**Không có dependency lẫn nhau** — mỗi module có thể dùng riêng hoặc kết hợp.

---

## 1. Circuit Breaker

**File:** `EA/risk/circuit_breaker.py`
**Purpose:** Tự động halt trading khi P&L vượt ngưỡng cho phép.

### Config

```python
@dataclass
class CircuitBreaker:
    daily_limit_pct: float = 4.0       # Max daily loss %
    weekly_limit_pct: float = 8.0      # Max weekly loss %
    trailing_dd_pct: float = 10.0      # Max drawdown from peak
    cool_off_minutes: int = 30         # Pause duration after halt
```

### Usage

```python
from EA.risk.circuit_breaker import CircuitBreaker

cb = CircuitBreaker(daily_limit_pct=5.0, trailing_dd_pct=10.0)

# Update equity peak (call after each trading day)
cb.update_equity_peak(current_equity=51_000)

# Check before opening new position
if cb.can_trade(current_equity=49_000, daily_pnl_pct=-3.5, weekly_pnl_pct=-6.0):
    # OK to trade
    pass
else:
    print(f"HALTED: {cb.halt_reason}")
    # -> "HALTED: Daily loss -3.5% exceeds limit 5.0%"

# Reset after cool-off period
cb.reset()
```

### Prop Firm Mapping

| Prop Firm | Daily Limit | Total DD | Suggested Config |
|---|---|---|---|
| FTMO | 5% | 10% | `daily=4.0, trailing=8.0` (buffer) |
| MFF | 5% | 12% | `daily=4.0, trailing=10.0` |
| TFT | 4% | 8% | `daily=3.0, trailing=6.0` |

> **Best Practice:** Set limits 1-2% below prop firm thresholds to provide a safety buffer.

---

## 2. Position Sizer

**File:** `EA/risk/position_sizer.py`
**Purpose:** Tính lot size dựa trên risk % và stop distance.

### Config

```python
@dataclass
class PositionSizer:
    risk_pct: float = 1.0          # Risk per trade (% of equity)
    max_lot: float = 10.0          # Max lot cap
    min_lot: float = 0.01          # Min lot
    lot_step: float = 0.01         # Lot increment
    prop_mode: bool = False        # Tighter limits for prop firm
    max_risk_pct_prop: float = 0.5 # Risk % in prop mode
```

### Usage

```python
from EA.risk.position_sizer import PositionSizer

# Normal mode
sizer = PositionSizer(risk_pct=1.0)
lot = sizer.calculate(
    equity=50_000,
    stop_distance=150,    # pips or points
    pip_value=10          # value per pip per lot
)
# lot = 50_000 * 0.01 / (150 * 10) = 0.33 lots

# Prop firm mode (tighter)
sizer_prop = PositionSizer(risk_pct=1.0, prop_mode=True, max_risk_pct_prop=0.5)
lot_prop = sizer_prop.calculate(equity=50_000, stop_distance=150, pip_value=10)
# Uses 0.5% instead of 1.0% -> 0.16 lots
```

### Sizing Formula

```
Normal:  lot = (equity × risk_pct) / (stop_distance × pip_value)
Prop:    lot = (equity × max_risk_pct_prop) / (stop_distance × pip_value)
Vol-adj: lot = normal_lot × (target_atr / actual_atr)  [when atr provided]
```

---

## 3. Portfolio Guard

**File:** `EA/risk/portfolio_guard.py`
**Purpose:** Kiểm soát exposure ở cấp portfolio — max positions, sector concentration.

### Config

```python
@dataclass
class PortfolioGuard:
    max_positions: int = 5           # Max concurrent positions
    max_sector_pct: float = 40.0     # Max % in one sector
    max_total_exposure_pct: float = 300.0  # Total notional / equity
    max_correlated: int = 2          # Max same-sector positions
```

### Usage

```python
from EA.risk.portfolio_guard import PortfolioGuard, Position

guard = PortfolioGuard(max_positions=5, max_sector_pct=40.0)

current_positions = [
    Position(symbol="BTCUSDT", sector="crypto", notional=10_000, direction="long"),
    Position(symbol="ETHUSDT", sector="crypto", notional=5_000, direction="long"),
]

# Check if new position is allowed
can_add = guard.can_add_position(
    symbol="SOLUSDT",
    sector="crypto",
    notional=5_000,
    equity=50_000,
    current_positions=current_positions
)

if not can_add:
    print(f"REJECTED: {guard.rejection_reason}")
    # "REJECTED: Sector crypto already at 2 of max 2 correlated positions"

# Portfolio summary
summary = guard.summary(current_positions)
# {'total_positions': 2, 'total_exposure_pct': 30.0, 'sectors': {'crypto': 100.0}}
```

---

## 4. Reconciler

**File:** `EA/risk/reconciler.py`
**Purpose:** So sánh state nội bộ EA với vị thế thực tế trên broker.

### Diff Types

| Type | Meaning | Risk |
|---|---|---|
| `PHANTOM` | EA nghĩ có position, broker không có | Stale state, missed close |
| `ORPHAN` | Broker có position, EA không biết | Manual trade hoặc state loss |
| `SIZE_MISMATCH` | Size khác nhau | Partial fill hoặc manual adjustment |
| `PRICE_MISMATCH` | Entry price khác nhau | Slippage hoặc state corruption |

### Usage

```python
from EA.risk.reconciler import Reconciler, PositionRecord

reconciler = Reconciler(size_tolerance=0.01)

ea_positions = [
    PositionRecord("EURUSD", "long", 1.0, 1.0850, ticket=12345),
]
broker_positions = [
    PositionRecord("EURUSD", "long", 0.5, 1.0850, ticket=12345),
]

diffs = reconciler.compare(ea_positions, broker_positions)
for d in diffs:
    print(f"{d.diff_type.name}: {d.symbol} — {d.detail}")
    # "SIZE_MISMATCH: EURUSD — EA=1.0, Broker=0.5"

# Auto-resolve suggestions
actions = reconciler.auto_resolve(diffs)
# ["ALERT: EURUSD size mismatch — EA=1.0, Broker=0.5. Manual check required."]
```

---

## Integration Pattern

```python
from EA.risk.circuit_breaker import CircuitBreaker
from EA.risk.position_sizer import PositionSizer
from EA.risk.portfolio_guard import PortfolioGuard

# Initialize
cb = CircuitBreaker(daily_limit_pct=4.0, trailing_dd_pct=10.0)
sizer = PositionSizer(risk_pct=1.0, prop_mode=True)
guard = PortfolioGuard(max_positions=5)

def can_open_trade(signal, equity, daily_pnl, weekly_pnl, positions):
    """Full risk check before opening new position."""
    
    # 1. Circuit breaker — drawdown limits
    if not cb.can_trade(equity, daily_pnl, weekly_pnl):
        return False, f"Circuit breaker: {cb.halt_reason}"
    
    # 2. Portfolio guard — exposure limits
    notional = sizer.max_position_value(equity)
    if not guard.can_add_position(signal.symbol, sector, notional, equity, positions):
        return False, f"Portfolio guard: {guard.rejection_reason}"
    
    # 3. Position sizing
    lot = sizer.calculate(equity, signal.stop_distance, pip_value)
    
    return True, lot
```

---

## Testing

```powershell
cd D:\code\trading_tool\python\market_regime_scanner
python -m pytest EA/tests/test_risk.py -v
```

12 tests covering all 4 modules:
- `TestCircuitBreaker` (5) — limits, trailing DD, reset
- `TestPositionSizer` (4) — basic, zero stop, prop mode, max lot
- `TestPortfolioGuard` (3) — max positions, duplicate, valid
- `TestReconciler` (4) — no diffs, phantom, orphan, size mismatch
