# Macro Balance Scalper EA

## Overview

The **Macro Balance Scalper** is an Expert Advisor (EA) designed to trade bounces within Monthly Macro Balance Areas (MBA). It exploits the **I→B→I (Imbalance → Balance → Imbalance)** fractal pattern at different timeframe levels.

### Core Concept

When the Monthly session enters a balance state (MBA), price tends to oscillate between the MBA high and low boundaries. Within this Monthly MBA, smaller Daily MBA units form (nested balance). The strategy:

1. **Buy** when price approaches the **low edge** of Monthly MBA
2. **Sell** when price approaches the **high edge** of Monthly MBA
3. **Target**: Nearest Daily MBA within the Monthly MBA range
4. **Stop Loss**: Beyond the MBA edge with buffer

---

## Strategy Logic

### Entry Conditions

```
1. Monthly MBA EXISTS (Balance State)
   └── Market is ranging/consolidating at macro level
   
2. Price at MBA Edge
   ├── Price ≤ MBA_Low + buffer → BUY opportunity
   └── Price ≥ MBA_High - buffer → SELL opportunity
   
3. Weekly Compression Filter (Optional)
   └── Weekly session shows compression → Energy building
   
4. Daily Ready Signal (Confirmation)
   └── Daily aligned with edge direction boosts confidence
```

### Exit Conditions

```
1. Take Profit → Nearest Daily MBA reached
2. Stop Loss   → Beyond MBA edge (1% buffer)
3. Time Exit   → 21 days max hold
4. MBA Break   → Monthly balance is broken (trend resuming)
```

---

## Position Sizing

Uses **2% Risk Model**:

```
Account Balance: $535.58
Risk per Trade:  $10.71 (2%)

Lot Size = Risk Amount / (SL Distance × Pip Value per Lot)
```

### Example Calculation

```
Symbol: XAUUSD
Entry: $3,300.00
SL:    $3,266.70 (1M MBA Low - buffer)

SL Distance = $33.30
Pip Value = $1.00 per 0.01 lot
Risk = $10.71

Lot Size = $10.71 / ($33.30 × $100) = 0.003 → 0.01 lots (minimum)
```

---

## Configuration

Edit `config.py` to customize:

```python
# Trading symbols
TRADING_CONFIG = {
    "XAUUSDm": {"lot": 0.01},
    "EURUSDm": {"lot": 0.1},
    ...
}

# Risk settings
ACCOUNT_BALANCE = 535.58
RISK_PERCENT = 0.02

# Strategy parameters
EDGE_THRESHOLD_PCT = 0.005   # 0.5% from edge to qualify
SL_BUFFER_PCT = 0.01         # 1% beyond edge for SL
MAX_HOLD_DAYS = 21           # Maximum hold period
```

---

## Key Differences: Balance Scalper vs Trend Catcher

| Feature | Macro Trend Catcher | Macro Balance Scalper |
|---------|---------------------|----------------------|
| Market State | Trend emerging | Range/Balance |
| Entry Signal | M/W/D aligned breakout | Price at MBA edge |
| Target | Unlimited (trend run) | Daily MBA **edge** (liquidity) |
| Hold Time | 60 days max | 21 days max |
| Best For | Breakout moves | Mean reversion |
| MBA Requirement | None (enter on ready) | Required (in balance) |

---

## I→B→I Fractal Theory

Markets move in cycles of **Imbalance → Balance → Imbalance**:

```
         IMBALANCE              BALANCE               IMBALANCE
        (Trending)            (Ranging)              (Trending)
        
    ↗↗↗↗↗↗              ────┬────┬────              ↗↗↗↗↗↗
   ↗                        │    │    │            ↗
  ↗                     MBA │  D │  D │           ↗
                       High │ MBA│ MBA│          ↗
                            │────│────│         ↗
                            │    │    │        ↗  ← BREAKOUT!
                       MBA  │  D │  D │       ↗
                       Low  │ MBA│ MBA│
                            ────┴────┴────
                            
   Monthly MBA with nested Daily MBA units
```

### Target Logic: MBA Edge (Liquidity Sweep)

Thanh khoản thường tập trung ở **biên** của Daily MBA:

```
BUY Trade:
  Entry: Near 1M MBA Low
  Target: Daily MBA HIGH edge (area_high)
          ↑ Liquidity pools at resistance
          
SELL Trade:
  Entry: Near 1M MBA High  
  Target: Daily MBA LOW edge (area_low)
          ↓ Liquidity pools at support
```

**Tại sao target vào biên?**
- Market makers đặt orders ở các vùng hỗ trợ/kháng cự
- Price thường "quét thanh khoản" (sweep) trước khi quay đầu
- Biên Daily MBA = vùng thanh khoản cao trong Monthly balance

---

## Usage

### Start the EA

```python
from EA.macro_balance_scalper.manager import run_ea

# Run with 60-minute intervals
run_ea(interval_minutes=60)
```

### Manual Signal Check

```python
from EA.macro_balance_scalper.strategy import MacroBalanceScalperStrategy

strategy = MacroBalanceScalperStrategy()
signal = strategy.evaluate("XAUUSDm", has_weekend=False, mt5_connected=True)

if signal:
    print(f"Direction: {signal.direction}")
    print(f"Entry: {signal.entry_price}")
    print(f"SL: {signal.stop_loss}")
    print(f"TP: {signal.take_profit}")
```

### Check Status

```python
from EA.macro_balance_scalper.manager import BalanceScalperManager

manager = BalanceScalperManager()
status = manager.get_status()
print(status)
```

---

## Files Structure

```
EA/macro_balance_scalper/
├── config.py       # Trading config & parameters
├── strategy.py     # Core strategy logic
├── manager.py      # EA orchestration & position sizing
└── docs/
    └── README.md   # This documentation
```

---

## Risk Warning

This EA is for educational purposes. Always:
- Test on demo account first
- Monitor positions regularly  
- Never risk more than you can afford to lose
- Understand the strategy before deploying

---

## Changelog

### v1.0.0 (2025-01-XX)
- Initial release
- Monthly MBA detection
- Daily MBA targeting (I→B→I rule)
- 2% risk position sizing
- Weekly compression filter
