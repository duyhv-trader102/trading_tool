# Huong dan chay Tests & Scripts

> Last Updated: 2026-02-17

## Yeu cau

### 1. Python Environment
```powershell
cd D:\code\trading_tool\python\market_regime_scanner
& D:\code\trading_tool\.venv\Scripts\Activate.ps1
pip install -e .
```

### 2. MetaTrader 5 (cho MT5 scripts)
- MT5 phai dang chay va dang nhap
- Cau hinh trong `infra/settings.yaml`:
```yaml
mt5:
  username: YOUR_ACCOUNT
  password: YOUR_PASSWORD
  server: YOUR_SERVER
  mt5Pathway: 'C:\Program Files\...\terminal64.exe'
```

---

## Tests

### `tests/visual_verify_xauusd.py`

**Muc dich:** Visual verification cho XAUUSD TPO analysis.

```powershell
python tests/visual_verify_xauusd.py
```

### EA Tests — `EA/tests/test_risk.py`

**Muc dich:** Unit tests cho risk management modules.

```powershell
python -m pytest EA/tests/test_risk.py -v
```

**Coverage (12 tests):**
| Class | Tests | Covers |
|---|---|---|
| `TestCircuitBreaker` | 5 | Daily/weekly limits, trailing DD, reset |
| `TestPositionSizer` | 4 | Basic sizing, zero stop, prop mode, max lot cap |
| `TestPortfolioGuard` | 3 | Max positions, duplicate, valid position |
| `TestReconciler` | 4 | No diffs, phantom, orphan, size mismatch |

---

## MT5 Scripts

### 1. Top-down Observer - `scripts/observer.py`

**Muc dich:** Dashboard chinh cho MT5 multi-TF analysis.

```powershell
# All configured symbols
python -m scripts.mt5.observer

# Specific symbols
python -m scripts.mt5.observer --symbol XAUUSDm BTCUSDm

# Crypto (with weekend data)
python -m scripts.mt5.observer --symbol BTCUSDm --has-weekend
```

**Output:** `scripts/output/{SYMBOL}_topdown.html`

### 2. Review CLI - `scripts/mt5/review_cli.py`

**Muc dich:** Review va hieu chinh regime detections.

```powershell
python -m scripts.mt5.review_cli
```

### 3. Data Fetch - `scripts/mt5/fetch_history.py`

**Muc dich:** Download historical H4 data to parquet.

```powershell
python scripts/mt5/fetch_history.py
```

### 4. MBA Test Scripts

```powershell
python scripts/mt5/test_mba_tracker.py
python scripts/mt5/test_mba_topdown.py
python scripts/mt5/test_imbalance_balance.py
```

---

## EA Backtest & Trading

### V2 Single Symbol Backtest (MT5)

```powershell
python -m EA.macro_trend_catcher.backtest --symbol XAUUSDm --years 3
python -m EA.macro_trend_catcher.backtest --symbol BTCUSDm --sl-mult 2.5 --cooldown 15
```

**Output:** Console metrics (PF, Sharpe, Win Rate, Drawdown).

### V2 Batch Backtest (Binance Spot)

```powershell
python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0
```

**Output:**
- Console: TOP 30, BOTTOM 10, aggregate stats
- JSON: `EA/macro_trend_catcher/reports/binance_batch_results.json`

### V2 Market Filter

```powershell
python -m EA.shared.market_filter
python -m EA.shared.market_filter --min-trades 8 --min-pf 1.5
```

**Output:** `EA/shared/reports/watchlist.json`

### V2 Live Bot (MT5)

```powershell
python -m EA.macro_trend_catcher.bot --dry-run --once   # Test
python -m EA.macro_trend_catcher.bot                     # Live
python -m EA.macro_trend_catcher.bot --assets FOREX_MAJORS COMMODITIES
```

---

## Market Scanners

### VNStock Scanner

```powershell
python market/cli.py scan --market VNSTOCK --symbol VNM
python market/cli.py scan --market VNSTOCK --group VN30
```

### Multi-Market CLI

```powershell
python market/cli.py scan --market COIN --all
python market/cli.py viz --market COIN --symbol BTCUSDm
```

### Macro Scanner

```powershell
python -m scripts.macro_scanner
```

---

## Quick Start

1. Mo terminal va activate venv:
```powershell
cd D:\code\trading_tool\python\market_regime_scanner
& D:\code\trading_tool\.venv\Scripts\Activate.ps1
```

2. Chay analysis:
```powershell
# Top-down MT5
python -m scripts.mt5.observer

# Backtest
python -m EA.macro_trend_catcher.backtest --symbol XAUUSDm

# VNStock Scanner
python market/cli.py scan --market VNSTOCK --symbol VNM
```

---

## Troubleshooting

### MT5 connection failed
- Dam bao MT5 dang chay
- Check credentials trong `infra/settings.yaml`
- Kiem tra `mt5Pathway` dung duong dan

### Module not found
```powershell
# LUON chay tu project root
cd D:\code\trading_tool\python\market_regime_scanner
pip install -e .

# Sau do chay bang python -m
python -m scripts.mt5.observer        # OK
python -m EA.macro_trend_catcher.backtest  # OK
```

### Chart khong mo
```powershell
# Mo thu cong
Start-Process "scripts\output\XAUUSDm_topdown.html"
```

---

## Output Files

| Script | Output Location |
|--------|-----------------|
| MT5 Observer | `scripts/output/{SYMBOL}_topdown.html` |
| V2 Backtest | Console only |
| Batch Backtest | `EA/macro_trend_catcher/reports/binance_batch_results.json` |
| Market Filter | `EA/shared/reports/watchlist.json` |
| Market CLI | `market/{market}/output/` |
