# Timeframe Confluence Logic (Nested Gating)

> Last Updated: 2026-02-17

This document defines the nested gating logic for cross-timeframe alignment used by the Macro Trend Catcher V2 strategy.

---

## 1. Analysis Levels

| Term | Session Type | Bar TF | Bars/Session | Role |
| :--- | :--- | :--- | :--- | :--- |
| **Monthly (M)** | MN1 | W1 | ~4-5 | Master Filter. Defines direction and readiness. |
| **Weekly (W)** | W1 | D1 | ~5 | Flow Confirmation. Confirms the Macro move. |
| **Daily (D)** | D1 | H4 | ~6 | Entry Execution. Fine-tuning the setup. |

> **V2 TF Mapping Change:** Previously used D1/H4/H1 bars. Changed to W1/D1/H4 to reduce noise and improve signal quality. This dramatically improved results (e.g. US30: -46% -> +35.53%).

---

## 2. MBA Readiness (per Timeframe)

Each timeframe's readiness is determined by `build_mba_context()` from `analytic.tpo_mba.tracker`, which returns `MBAMetadata` containing:

- `is_ready` -- whether the MBA has completed distribution
- `ready_direction` -- bullish or bearish, based on:
  - **VA dominance**: buying vs selling TPO counts within Value Area
  - **Close confirmation**: close price relative to h_limit/l_limit

### Ready Conditions (3-1-3 evaluation)

| Condition | Ready? | Reason Code |
|---|---|---|
| 3-1-3 distribution (no minus dev) | Yes | STRUCTURAL_313 |
| Neutral session (bidirectional sweep) | Yes | SWEEP |
| Normal session (compression, no extension) | Yes | COMPRESSION |
| Normal Variation (>20% IB extension) | No | -- |
| Imbalance (strong directional move) | No | -- |

---

## 3. Nested Confluence Rules (V2)

### Entry Logic (ALL must be true)

```
Step 1: Monthly MBA is READY              -> anchor direction
Step 2: Weekly MBA is READY               -> same direction as Monthly
Step 3: Daily MBA is READY                -> same direction as Weekly
                                           => ENTER at daily close
```

### Entry Filters (additional gates)

| Filter | Logic |
|--------|-------|
| **Price-direction consistency** | Entry price must be inside MBA range on all TFs |
| **MBA continuity** | Configurable min sessions since mother (default: 0) |
| **Cooldown** | After stop-loss hit, block same-direction re-entry for N days (default: 20) |

### Exit Logic

| Condition | Action |
|-----------|--------|
| Monthly direction flips (ready in opposite direction) | Close position |
| Stop-loss hit (checked with intraday H/L in backtest, server-side in live) | Close position |

---

## 4. Signal Strength (Simplified for V2)

| Signal | Monthly | Weekly | Daily | Action |
| :--- | :--- | :--- | :--- | :--- |
| **ENTER** | READY | READY + Aligned | READY + Aligned | Open position |
| **WAIT** | Any NOT READY | -- | -- | No trade |

> V2 uses binary entry logic (all 3 aligned = enter, otherwise wait). The graduated signal strength (STRONG/MODERATE/WEAK) from V1 has been removed for clarity.

---

## 5. Implementation

### Key Classes (in `EA/macro_trend_catcher/signals.py`)

| Class | Purpose |
|-------|---------|
| `AlignmentState` | Snapshot of M/W/D readiness & direction |
| `TrendSignalV2` | Entry signal dataclass (symbol, direction, price, SL, timestamp) |
| `SignalGeneratorV2` | Evaluates alignment, generates entry signals, checks exit conditions |

### Signal Generation Flow

```python
from EA.macro_trend_catcher.signals import SignalGeneratorV2

gen = SignalGeneratorV2(config)
alignment = gen.evaluate_alignment(m_meta, w_meta, d_meta)
# alignment.is_aligned = True if all 3 ready + same direction

signal = gen.generate_signal(alignment, symbol, price, atr)
# Returns TrendSignalV2 if aligned, None otherwise

should_exit = gen.check_exit(m_meta, current_direction)
# True if monthly flipped direction
```

---

## 6. Conflict Handling

- **Monthly not ready**: No trade. Wait for MBA to complete distribution.
- **Direction mismatch**: If Weekly/Daily direction differs from Monthly, no entry.
- **Cooldown active**: If same-direction stop-loss was hit within N days, skip entry even if aligned.

---

## 7. V2 vs V1 Changes

| Aspect | V1 | V2 |
|--------|----|----|
| TF Mapping | D1/H4/H1 bars | W1/D1/H4 bars (less noise) |
| Signal grading | STRONG/MODERATE/WEAK/WAIT | Binary (ENTER or WAIT) |
| Entry filters | None | Price validation + cooldown + continuity |
| Exit | Monthly flip only | Monthly flip + stop-loss |
| 3-1-3 direction | Fixed rule | VA dominance + close confirmation |
| Data sources | MT5 only | MT5 + Binance spot parquets |

---

## 8. V2.1 — Compression Gate

**Introduced:** February 2026

### Concept

V2 only checks MBA readiness (is the structure **ready**?). V2.1 adds a second check: is the current session **compressed** enough?

The compression gate ensures entry only when each TF's latest session shows genuine consolidation — not during directional moves or extensions.

### Allowed Session Types (Compression Gate)

| Session Type | Allowed? | Reasoning |
|---|---|---|
| Normal | Yes | Tight range, no IB extension — classic compression |
| Neutral | Yes | Bidirectional sweep — price explored both sides, settling |
| 3-1-3 | Yes (if no minus dev) | Full distribution cycle completed |
| Normal Variation | No | >20% IB extension — still expanding |
| Trend Day | No | Strong directional move — not compressed |
| Other / Imbalance | No | Not yet stabilized |

### Implementation

```python
alignment = SignalGeneratorV2.build_alignment(
    meta_m, meta_w, meta_d,
    require_compression=True  # V2.1 flag
)

# AlignmentState now includes:
# - monthly_compressed, weekly_compressed, daily_compressed: bool
# - require_compression: bool
# - is_aligned checks ALL 3 compressed when require_compression=True
```

### Backtest Impact (259 Binance Spot Symbols)

| Metric | V2 | V2.1 |
|---|---|---|
| Compression gate blocked | — | 1,313 signals |
| Total trades | ~3,100 | 1,802 |
| Strong Candidates (PF≥1.5) | 113 | 66 |
| Quality per trade | Lower | Higher (fewer but better) |

The gate reduced trade count ~42% by filtering out entries during non-compressed sessions, improving signal quality.
