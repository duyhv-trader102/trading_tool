"""
Batch Position Backtest
=======================
Runs V3 backtests for a predefined list of assets and generates data for the reports.

Usage:
    python -m scripts.research.batch_position_backtest
"""

import os
import sys
import logging
import json
from datetime import datetime

# Setup path
from core.path_manager import setup_path, get_output_path
setup_path()

from infra.data.mt5_provider import MT5Provider
from EA.macro_trend_catcher.v3.backtest import run_v3_backtest_from_tpo
from EA.macro_trend_catcher.v3.config import FOREX_CONFIG, US_STOCKS_CONFIG, TrendCatcherConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Assets to backtest (based on implementation plan)
ASSETS = [
    {"symbol": "XAUUSDm", "asset_class": "FOREX", "bars": 15000},
    {"symbol": "BTCUSDm", "asset_class": "CRYPTO", "bars": 20000},
    {"symbol": "EURUSDm", "asset_class": "FOREX", "bars": 15000},
    {"symbol": "GBPUSDm", "asset_class": "FOREX", "bars": 15000},
    {"symbol": "GBPJPYm", "asset_class": "FOREX", "bars": 15000},
    {"symbol": "USDJPYm", "asset_class": "FOREX", "bars": 15000},
]

def run_batch():
    provider = MT5Provider()
    if not provider.connect():
        logger.error("Failed to connect to MT5")
        return

    results_summary = []

    for item in ASSETS:
        symbol = item["symbol"]
        asset_class = item["asset_class"]
        bars = item["bars"]
        
        logger.info(f"\n>>> Starting Backtest for {symbol} ({bars} bars)...")
        
        # Determine config
        config = FOREX_CONFIG
        if asset_class == "US_STOCKS":
            config = US_STOCKS_CONFIG
        # Add more mappings as needed
        
        result = run_v3_backtest_from_tpo(
            symbol=symbol,
            asset_class=asset_class,
            provider=provider,
            config=config,
            bars=bars
        )
        
        if result.error:
            logger.error(f"Error backtesting {symbol}: {result.error}")
            continue

        # Save individual trade JSON for reports
        output_file = get_output_path(f"macro_trades_{symbol}.json")
        save_data = {
            "symbol": symbol,
            "asset_class": asset_class,
            "timestamp": datetime.now().isoformat(),
            "bars": bars,
            "trades": result.trades
        }
        
        with open(output_file, 'w') as f:
            json.dump(save_data, f, indent=4)
        
        logger.info(f"Results saved to: {output_file}")
        
        results_summary.append({
            "symbol": symbol,
            "trades": result.total_trades,
            "win_rate": f"{result.win_rate*100:.1f}%",
            "profit": f"{result.total_profit:.2f}%",
            "max_dd": f"{result.max_drawdown:.1f}%"
        })

    # Print Summary Table
    print("\n" + "="*80)
    print(f"{'Symbol':<10} | {'Trades':<8} | {'Win Rate':<10} | {'Profit':<10} | {'Max DD':<10}")
    print("-" * 80)
    for res in results_summary:
        print(f"{res['symbol']:<10} | {res['trades']:<8} | {res['win_rate']:<10} | {res['profit']:<10} | {res['max_dd']:<10}")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_batch()
