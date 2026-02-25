# Backtest Guide

> Last Updated: 2026-02-17

Hướng dẫn chạy backtest cho Macro Trend Catcher V2/V2.1.

---

## Backtest Variants

| Script | Source | Mode | Output |
|--------|--------|------|--------|
| `backtest.py` | MT5 | Single symbol | Console metrics |
| `backtest_binance.py` | Binance H4 | Batch (long+short) | JSON results |
| `backtest_spot.py` | Binance H4 | Batch (LONG-only) | JSON results |
| `backtest_spot_v21.py` | Binance H4 | V2.1 LONG-only | JSON results |
| `backtest_v21_detailed.py` | Binance H4 | V2.1 LONG + trade log | CSV/JSON/Report |

---

## 1. Single Symbol Backtest (MT5)

Backtest trên dữ liệu MT5 H4 parquet (tự resample lên D1/W1).

```powershell
cd D:\code\trading_tool\python\market_regime_scanner

# Default: XAUUSDm, 3 years, SL=3x ATR
python -m EA.macro_trend_catcher.backtest --symbol XAUUSDm --years 3

# Custom
python -m EA.macro_trend_catcher.backtest --symbol BTCUSDm --sl-mult 2.5 --cooldown 15
```

**Output:** Console — PF, Sharpe, Win Rate, Drawdown, equity curve.

---

## 2. Batch Backtest — Binance Spot V2

Chạy trên tất cả Binance spot symbols có ≥3 năm dữ liệu H4 (~259 symbols).
Hỗ trợ cả LONG và SHORT signals.

```powershell
python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0
```

**Output:**
- Console: TOP 30, BOTTOM 10, aggregate stats
- `reports/binance_batch_results.json`

---

## 3. LONG-Only Spot Backtest

Giống nhưng chỉ lấy LONG signals (phù hợp Binance spot không short).

```powershell
python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0
```

---

## 4. V2.1 Detailed Backtest (Recommended)

V2.1 thêm **Compression Gate** + per-trade logging 35 fields.

```powershell
python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0
```

### Compression Gate

Mỗi TF (Monthly/Weekly/Daily) phải có session cuối ở trạng thái **compressed**:
- Normal — range hẹp, không IB extension
- Neutral — sweep hai hướng
- 3-1-3 — distribution cycle hoàn tất (không có minus dev)

Nếu bất kỳ TF nào **không** compressed → entry bị block.

### Trade Log Fields (35 per trade)

| # | Field | Type | Description |
|---|---|---|---|
| 1 | `symbol` | str | Trading symbol |
| 2 | `trade_id` | int | Sequential trade number |
| 3 | `entry_time` | datetime | Entry timestamp |
| 4 | `exit_time` | datetime | Exit timestamp |
| 5 | `duration_days` | int | Trade duration |
| 6 | `entry_price` | float | Entry price |
| 7 | `exit_price` | float | Exit price |
| 8 | `stop_loss` | float | Stop-loss level |
| 9 | `sl_distance_pct` | float | SL distance as % of entry |
| 10 | `atr_at_entry` | float | ATR at entry time |
| 11 | `direction` | str | "long" (spot always long) |
| 12 | `exit_reason` | str | direction_flip / stop_loss / end_of_backtest |
| 13 | `gross_return_pct` | float | Return before fees |
| 14 | `net_return_pct` | float | Return after fees (0.2% RT) |
| 15 | `is_win` | bool | True if net_return > 0 |
| 16 | `m_ready` | bool | Monthly MBA ready at entry |
| 17 | `m_direction` | str | Monthly MBA direction |
| 18 | `m_compressed` | bool | Monthly session compressed |
| 19 | `m_mba_low` | float | Monthly MBA low boundary |
| 20 | `m_mba_high` | float | Monthly MBA high boundary |
| 21 | `m_continuity` | int | Sessions since monthly mother bar |
| 22 | `w_ready` | bool | Weekly MBA ready |
| 23 | `w_direction` | str | Weekly direction |
| 24 | `w_compressed` | bool | Weekly compressed |
| 25 | `w_mba_low` | float | Weekly MBA low |
| 26 | `w_mba_high` | float | Weekly MBA high |
| 27 | `w_continuity` | int | Weekly continuity |
| 28 | `d_ready` | bool | Daily MBA ready |
| 29 | `d_direction` | str | Daily direction |
| 30 | `d_compressed` | bool | Daily compressed |
| 31 | `d_mba_low` | float | Daily MBA low |
| 32 | `d_mba_high` | float | Daily MBA high |
| 33 | `d_continuity` | int | Daily continuity |
| 34 | `alignment_summary` | str | Human-readable alignment state |
| 35 | `equity_before` | float | Equity before this trade |
| 36 | `equity_after` | float | Equity after this trade |

### Output Files

| File | Size (typical) | Content |
|---|---|---|
| `v21_trade_log.csv` | ~550 KB | 1,800+ trades, 35 fields each |
| `v21_trade_log.json` | ~1.9 MB | Same data in JSON |
| `v21_summary_report.txt` | ~11 KB | Aggregate report |
| `spot_v21_backtest_results.json` | varies | Per-symbol metrics |
| `spot_v21_watchlist.json` | varies | Tiered watchlist |
| `spot_v21_ranked_top50.json` | varies | HealthyTrendScore ranking |
| `spot_v21_ranked_top50.csv` | varies | Same as CSV |

All outputs go to `EA/macro_trend_catcher/reports/`.

---

## CLI Options

| Option | Scripts | Default | Description |
|--------|---------|---------|-------------|
| `--sl-mult` | all backtest | 3.0 | Stop-loss ATR multiplier |
| `--cooldown` | all backtest | 20 | Cooldown days after SL hit |
| `--symbol` | backtest.py | XAUUSDm | MT5 symbol |
| `--years` | backtest.py | 3 | Years of history |

---

## Configuration

Tất cả backtest config được define trong `v2/config.py`:

```python
@dataclass
class TrendCatcherV2Config:
    initial_stop_atr_mult: float = 3.0    # SL = 3x ATR
    atr_period: int = 14                   # ATR period
    cooldown_days: int = 20                # Block after SL
    min_mba_continuity: int = 0            # Min sessions since mother
    risk_per_trade_pct: float = 2.0        # Per-trade risk
    max_positions: int = 10                # Max concurrent
```

**Fee:** 0.1% per side (0.2% round-trip) for Binance spot.

**Min Data:** 4,536 H4 bars (~3 years equivalent).

---

## Interpreting Results

### Key Metrics

| Metric | Healthy Range | Notes |
|---|---|---|
| Win Rate | 25-40% | Strategy is low-WR, high-RR |
| Profit Factor | >1.5 | Gross profit / gross loss |
| Sharpe Ratio | >0.3 | Risk-adjusted return |
| Max Drawdown | <60% | Peak-to-trough equity drop |
| Avg Duration | 30-90 days | Swing trade timeframe |

### Exit Reasons

| Reason | Typical Win% | Meaning |
|---|---|---|
| `direction_flip` | ~58% | Monthly MBA flipped — position closed with profit |
| `stop_loss` | 0% | Price hit SL — always a loss |
| `end_of_backtest` | ~100% | Data ended while in position — forced close |

### Tier Classification (Market Filter)

| Tier | Score | Recommended Action |
|---|---|---|
| Elite (≥70) | Top 2% | Full conviction, full size |
| Strong (≥50) | Top 5-10% | Normal position size |
| Watch (≥35) | Top 10-20% | Small size, monitor |
| Rejected (<35) | Bottom 80% | Do not trade |
