"""
Macro Trend Catcher — Top-Down MBA Alignment Strategy
======================================================

Core trend-following strategy using 3-timeframe MBA readiness alignment.

Entry:  M/W/D all ready in same direction + compression gate
Exit:   Monthly direction flip or stop-loss (3x ATR)

Modules
-------
- ``config``    : Strategy parameters, asset configs, skip-lists
- ``signals``   : Alignment detection + signal generation
- ``bot``       : Live MT5 trading bot
- ``backtest``  : Unified backtest engine (Binance SPOT, long-only, BTC filter)
- ``portfolio_backtest`` : Portfolio simulation + Monte Carlo

Usage::

    # Backtest
    python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0
    python -m EA.macro_trend_catcher.backtest --btc-filter --no-rank

    # Portfolio simulation
    python -m EA.macro_trend_catcher.portfolio_backtest

    # Live bot
    python -m EA.macro_trend_catcher.bot
"""

from EA.macro_trend_catcher.config import TrendCatcherV2Config
from EA.macro_trend_catcher.signals import SignalGeneratorV2, AlignmentState

__all__ = [
    "TrendCatcherV2Config",
    "SignalGeneratorV2",
    "AlignmentState",
]
