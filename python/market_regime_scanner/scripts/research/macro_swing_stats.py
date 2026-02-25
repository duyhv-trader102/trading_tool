"""
Macro Swing Stats - Backtest Runner
===================================
Standalone script to run V3 backtests for a specific symbol.

Usage:
    python -m scripts.research.macro_swing_stats --symbol XAUUSDm --bars 15000
"""

import os
import sys
import argparse
import logging
import json
from datetime import datetime

# Setup path
from core.path_manager import setup_path, get_output_path
setup_path()

from infra.data.mt5_provider import MT5Provider
from EA.macro_trend_catcher.v3.backtest import run_v3_backtest_from_tpo
from EA.macro_trend_catcher.v3.config import FOREX_CONFIG, TrendCatcherConfig

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def run_stats(symbol: str, bars: int = 15000, asset_class: str = "FOREX"):
    provider = MT5Provider()
    
    # Select config based on asset class
    config = FOREX_CONFIG
    # Add more logic here if needed for different configs
    
    result = run_v3_backtest_from_tpo(
        symbol=symbol,
        asset_class=asset_class,
        provider=provider,
        config=config,
        bars=bars
    )
    
    if result.error:
        logger.error(f"Error backtesting {symbol}: {result.error}")
        return
    
    # Print summary
    print("\n" + "="*60)
    print(f"BACKTEST RESULTS: {symbol} (Last {bars} bars)")
    print("="*60)
    print(f"Total Trades:    {result.total_trades}")
    print(f"Win Rate:        {result.win_rate*100:.1f}%")
    print(f"Total Profit:    {result.total_profit:.2f}%")
    print(f"Avg Profit:      {result.avg_profit:.2f}%")
    print(f"Max Drawdown:    {result.max_drawdown:.1f}%")
    print(f"Sharpe Ratio:    {result.sharpe_ratio:.2f}")
    print(f"Avg Duration:    {result.avg_duration_days:.1f} days")
    print("-" * 60)
    print(f"ADX Filters:     {result.filtered_by_adx}")
    print(f"Trailing Exits:  {result.stopped_by_trailing}")
    print(f"Time Exits:      {result.stopped_by_time}")
    print(f"Flip Exits:      {result.direction_flip_exits}")
    print("="*60 + "\n")
    
    # Save trades to JSON for reporting
    output_file = get_output_path(f"macro_trades_{symbol}.json")
    save_data = {
        "symbol": symbol,
        "asset_class": asset_class,
        "timestamp": datetime.now().isoformat(),
        "bars": bars,
        "metrics": {
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
            "total_profit": result.total_profit,
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio
        },
        "trades": result.trades
    }
    
    with open(output_file, 'w') as f:
        json.dump(save_data, f, indent=4)
    
    logger.info(f"Trades saved to: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Macro Trend Catcher V3 Backtest")
    parser.add_argument("--symbol", type=str, required=True, help="Symbol to backtest")
    parser.add_argument("--bars", type=int, default=15000, help="Number of bars for lookback")
    parser.add_argument("--asset-class", type=str, default="FOREX", help="Asset class for config")
    
    args = parser.parse_args()
    
    run_stats(args.symbol, args.bars, args.asset_class)
