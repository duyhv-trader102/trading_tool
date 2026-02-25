# Setup Guide - Market Regime Scanner

> Last Updated: 2026-02-25

## Cài đặt lần đầu

```powershell
cd D:\code\trading_tool\python\market_regime_scanner

# 1. Activate venv
& D:\code\trading_tool\.venv\Scripts\Activate.ps1

# 2. Cài package ở chế độ editable (BẮT BUỘC)
pip install -e .
```

> **Tại sao cần `pip install -e .`?**
> Project dùng `pyproject.toml` để khai báo package. Lệnh này đăng ký các module (`core`, `analytic`, `infra`, `viz`, `markets`, `scripts`, v.v.) vào Python path, giúp import hoạt động từ bất kỳ đâu.

---

## Cấu hình MT5

Tạo/sửa file `infra/settings.yaml`:
```yaml
mt5:
  username: YOUR_ACCOUNT
  password: YOUR_PASSWORD
  server: YOUR_SERVER
  mt5Pathway: 'C:\Program Files\...\terminal64.exe'

tpo:
  weekly:
    data_tf: "D1"
    target_rows: 40
  monthly:
    data_tf: "W1"
    target_rows: 40
```

---

## Cấu hình S3

Tất cả dữ liệu parquet và báo cáo HTML được lưu trên **AWS S3**. Không có file nào được giữ lại trên local sau khi scan.

Tạo file `.env` từ `.env.example`:
```dotenv
S3_ACCESS_KEY_ID=AKIA...
S3_SECRET_ACCESS_KEY=...
S3_BUCKET=achitek-investment-application-layer
S3_REGION=ap-northeast-1
S3_PREFIX=market_regime_scanner/data
```

**Layout S3:**
```
{bucket}/
└── market_regime_scanner/
    ├── data/
    │   ├── mt5/       ← parquet files (MT5 symbols)
    │   ├── binance/   ← parquet files (Binance spot)
    │   └── vnstock/   ← parquet files (VN stocks)
    └── reports/
        ├── markets/output/   ← HTML dashboards + charts (presigned URLs)
        └── markets/logs/     ← Signal CSVs + tracker snapshots
```

**Quản lý S3 thủ công:**
```powershell
python -m infra.s3_storage upload              # local → S3 (bỏ qua file đã có)
python -m infra.s3_storage upload --force      # force re-upload tất cả
python -m infra.s3_storage download            # S3 → local (chỉ file missing)
python -m infra.s3_storage sync                # bi-directional newest-wins
python -m infra.s3_storage ls                  # liệt kê tất cả
python -m infra.s3_storage ls binance          # liệt kê subdir binance
```

> **Lưu ý:** `client.upload_file()` của boto3 bị lỗi `stream not seekable` khi dùng custom endpoint + SigV4. Toàn bộ upload trong codebase đều dùng `put_object(Body=bytes)`.

---

## Lỗi thường gặp

### 1. `ModuleNotFoundError: No module named 'infra'`

**Fix:**
```powershell
cd D:\code\trading_tool\python\market_regime_scanner
pip install -e .
```

### 2. `ModuleNotFoundError: No module named 'EA'`

`EA/` không nằm trong setuptools packages. Phải chạy từ project root bằng `python -m`.

```powershell
# ĐÚNG — chạy từ project root
cd D:\code\trading_tool\python\market_regime_scanner
python -m EA.macro_trend_catcher.backtest --symbol XAUUSDm

# SAI
python -c "from EA.macro_trend_catcher.bot import TrendCatcherV2Bot"
```

### 3. `No module named 'boto3'`

```powershell
pip install boto3
```

### 4. S3 upload lỗi "stream not seekable"

Đã được fix — tất cả upload dùng `put_object(Body=bytes)` thay vì `upload_file()`. Nếu gặp lại hãy kiểm tra code chưa được update.

### 5. Thêm package mới

`pyproject.toml` **không tự cập nhật** khi `pip install <package>`. Phải thêm thủ công vào `[project] dependencies`.

---

## Dependencies hiện tại

```toml
requires-python = ">=3.11"
dependencies = [
    "numpy>=1.24",
    "pyarrow>=14.0",
    "polars>=1.0",
    "MetaTrader5>=5.0",
    "plotly>=5.0",
    "PyYAML>=6.0",
    "vnstock>=3.0",
    "ccxt>=4.0",
    "boto3>=1.28",
]
```

---

## Chạy scripts

```powershell
# Luôn chạy từ thư mục project root
cd D:\code\trading_tool\python\market_regime_scanner

# === Daily Scan (main) ===
python -m markets.daily_scan                  # tất cả markets
python -m markets.daily_scan --markets FX COMM
python -m markets.daily_scan --skip-update    # bỏ qua data refresh
python -m markets.daily_scan --universe-only  # chỉ Binance watchlist

# === Signal Tracker ===
python -m markets.pnl_tracker
python -m markets.pnl_tracker --markets BINANCE FX

# === Observer (single symbol) ===
python -m scripts.observer --symbol XAUUSDm

# === EA Trading ===
python -m EA.macro_trend_catcher.backtest --symbol XAUUSDm --years 3
python -m EA.macro_trend_catcher.bot --dry-run --once
```

---

## Checklist nhanh khi gặp lỗi import

1. `.venv` đã activate? → Thấy `(.venv)` ở đầu dòng lệnh
2. `pip show market-regime-scanner` có kết quả?
3. Đang ở đúng thư mục project? → `D:\code\trading_tool\python\market_regime_scanner`
4. Chạy EA bằng `python -m` từ project root?
5. Nếu thiếu bất kỳ bước nào → `pip install -e .`

```powershell
# Luon chay tu thu muc project root
cd D:\code\trading_tool\python\market_regime_scanner

# === Analysis ===
python -m scripts.mt5.observer                    # MT5 dashboard
python market/cli.py scan --market COIN --all     # Market CLI

# === V2 Trading ===
python -m EA.macro_trend_catcher.backtest --symbol XAUUSDm --years 3
python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0
python -m EA.shared.market_filter
python -m EA.macro_trend_catcher.bot --dry-run --once

# === VNStock ===
python market/cli.py scan --market VNSTOCK --symbol VNM
python market/cli.py scan --market VNSTOCK --group VN30
```

---

## Checklist nhanh khi gap loi import

1. `.venv` da activate? -> Thay `(.venv)` o prompt
2. `pip show market-regime-scanner` co ket qua?
3. Dang o dung thu muc project? -> `D:\code\trading_tool\python\market_regime_scanner`
4. Chay EA bang `python -m` tu project root?
5. Neu thieu bat ky buoc nao -> `pip install -e .`
