"""
markets.utils.formatters — Shared formatting helpers.

Extracted from pnl_tracker.py and reporting.py to avoid duplication
and make them reusable across the markets package.
"""
from __future__ import annotations

from typing import Dict, List

from markets.utils.constants import MARKET_ORDER


def fmt_price(v) -> str:
    """Smart price formatter — adapts decimal places to magnitude."""
    if v is None:
        return "-"
    v = float(v)
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 100:
        return f"{v:,.2f}"
    if a >= 1:
        return f"{v:.4f}"
    if a >= 0.001:
        return f"{v:.6g}"
    return f"{v:.3e}"


def fmt_pct(v) -> str:
    """Format a percentage value with +/- sign."""
    if v is None:
        return "-"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def fmt_range(val) -> str:
    """Format a range boundary value (4 decimal places)."""
    try:
        return f"{val:.4f}" if val is not None else "-"
    except Exception:
        return "-"


def compact_regime(status: str, trend: str, is_ready: bool) -> str:
    """Compact regime badge: e.g. 'IB^*' = In-Balance, Bullish, Ready."""
    abbr = {"IN BALANCE": "IB", "BREAKOUT": "BO", "NO DATA": "ND",
            "WAITING FOR DATA": "WD"}
    s = abbr.get(status, status[:2] if status else "?")
    arrow = {"bullish": "^", "bearish": "v", "neutral": "-", "conflict": "~"}
    a = arrow.get(trend, "?")
    r = "*" if is_ready else ""
    return f"{s}{a}{r}"


def sorted_markets(rows: List[Dict]) -> List[str]:
    """Return market keys from *rows* in canonical display order."""
    present = set(r["market"] for r in rows)
    ordered = [m for m in MARKET_ORDER if m in present]
    extras = sorted(present - set(MARKET_ORDER))
    return ordered + extras
