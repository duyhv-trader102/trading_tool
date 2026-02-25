# Binance Market Module

This module provides data fetching and analysis capabilities for the Binance cryptocurrency market.

## Features
- **Data Fetching**: Download OHLCV data for all Binance Spot (USDT) symbols using `ccxt`.
- **Regime Analysis**: Analyze market regimes (Balance, Breakout) across multiple timeframes.
- **TPO Visualization**: Generate interactive Time Price Opportunity (TPO) charts.

## Configuration
The `config.py` file contains:
- `DATA_DIR`: Where parquet files are saved.
- `DEFAULT_SYMBOLS`: A list of over 400 USDT spot symbols used for batch operations.

## Usage

### 1. Data Downloading
You must download data before running analysis or visualization.

**Download specific symbols:**
```powershell
python -m market.binance.downloader BTC/USDT,ETH/USDT,SOL/USDT
```

**Download all default symbols:**
```powershell
python -m market.binance.downloader all
```

**List all available spot symbols:**
```powershell
python -m market.binance.downloader list_spot
```

### 2. Market Scanning
Run the scanner to see the regime status of symbols.

**Scan a specific symbol:**
```powershell
python market/cli.py scan --market binance --symbol BTC/USDT
```

**Scan all default symbols:**
```powershell
python market/cli.py scan --market binance --all
```

### 3. Visualization
Generate TPO charts for detailed analysis.

```powershell
python market/cli.py tpo --market binance --symbol BTC/USDT
```
The output will be saved in `market/binance/output/`.

## Dependencies
- `ccxt`: Handles exchange API connections.
- `polars`: High-performance data processing.
- `plotly`: Interactive visualizations.
