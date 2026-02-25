"""
universe — Coin Universe Selection
====================================

Builds a quality-filtered, evidence-based watchlist of Binance coins
by running a 3-stage pipeline:

    1. Pre-screen  : volume / listing age / price sanity checks
    2. Backtest    : run EA signals on historical D1 data
    3. Score       : reuse EA/shared/market_filter scoring engine

Typical usage::

    python -m universe.cli screen               # full pipeline (~30 min)
    python -m universe.cli screen --no-backtest # pre-screen only (fast)
    python -m universe.cli report               # print last result
    python -m universe.cli list --tier 1        # list Tier 1 symbols

Output: ``universe/watchlist.json`` — consumed by ``markets/daily_scan.py``.
"""

from universe.watchlist import load_watchlist, save_watchlist, get_tradeable_symbols
from universe.screener import run_universe_screening

__all__ = [
    "run_universe_screening",
    "load_watchlist",
    "save_watchlist",
    "get_tradeable_symbols",
]
