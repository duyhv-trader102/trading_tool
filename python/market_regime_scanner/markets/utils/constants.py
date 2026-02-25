"""
markets.utils.constants — Shared market constants.

Single source of truth for market metadata previously duplicated
across daily_scan.py, pnl_tracker.py and sync.py.
"""
from __future__ import annotations

from typing import Dict

# Markets backed by MetaTrader 5
MT5_MARKETS: set[str] = {"FX", "COMM", "US_STOCK", "COIN"}

# Markets that trade on weekends (crypto)
WEEKEND_MARKETS: set[str] = {"COIN", "BINANCE"}

# Canonical display ordering for markets
MARKET_ORDER: list[str] = ["FX", "COMM", "US_STOCK", "COIN", "BINANCE", "VNSTOCK", "VN30"]

# Same as MARKET_ORDER — alias used by daily_scan CLI default
DEFAULT_MARKETS: list[str] = MARKET_ORDER

# Market metadata: label for display + colour for HTML styling
MARKET_META: Dict[str, Dict[str, str]] = {
    "FX":       {"label": "FX",          "color": "#569cd6"},
    "COMM":     {"label": "Commodities", "color": "#ce9178"},
    "US_STOCK": {"label": "US Stocks",   "color": "#4ec9b0"},
    "COIN":     {"label": "Crypto",      "color": "#dcdcaa"},
    "BINANCE":  {"label": "Binance",     "color": "#c586c0"},
    "VNSTOCK":  {"label": "VN Stock",    "color": "#6a9955"},
    "VN30":     {"label": "VN30",        "color": "#4fc1ff"},
}
