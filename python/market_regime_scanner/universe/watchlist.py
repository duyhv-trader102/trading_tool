"""
universe.watchlist — Watchlist I/O & Query
===========================================

Manages reading/writing the ``watchlist.json`` output file and
provides convenience helpers for consumers (daily_scan, bot, etc.).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from universe.config import WATCHLIST_FILE

log = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────

@dataclass
class WatchlistSymbol:
    """Single scored symbol in the watchlist."""
    symbol: str
    tier: str                  # "Tier 1", "Tier 2", "Tier 3", "Rejected"
    score: float
    return_pct: float
    return_per_year: float
    profit_factor: float
    sharpe_ratio: float
    win_rate: float            # 0-1
    trades: int
    max_drawdown: float
    data_years: float
    avg_duration_days: float


@dataclass
class WatchlistResult:
    """Full output of one universe screening run."""
    generated_at: str = ""
    total_screened: int = 0
    total_pre_screen_passed: int = 0
    total_backtest_ran: int = 0
    total_passed: int = 0      # tradeable (T1+T2+T3)
    tiers: Dict[str, List[str]] = field(default_factory=lambda: {
        "tier_1": [], "tier_2": [], "tier_3": [], "tier_4": [],
    })
    symbols: List[WatchlistSymbol] = field(default_factory=list)


# ── Save ─────────────────────────────────────────────────────

def save_watchlist(result: WatchlistResult, path: str | Path | None = None) -> Path:
    """Serialise WatchlistResult to JSON.  Returns the path written."""
    out = Path(path) if path else WATCHLIST_FILE
    out.parent.mkdir(parents=True, exist_ok=True)

    payload: Dict[str, Any] = {
        "generated_at": result.generated_at or datetime.now().isoformat(),
        "total_screened": result.total_screened,
        "total_pre_screen_passed": result.total_pre_screen_passed,
        "total_backtest_ran": result.total_backtest_ran,
        "total_passed": result.total_passed,
        "tiers": result.tiers,
        "symbols": [asdict(s) for s in result.symbols],
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    log.info("Watchlist saved -> %s  (%d tradeable)", out, result.total_passed)
    return out


# ── Load ─────────────────────────────────────────────────────

def load_watchlist(path: str | Path | None = None) -> Optional[WatchlistResult]:
    """Load WatchlistResult from JSON.  Returns None if file missing."""
    src = Path(path) if path else WATCHLIST_FILE
    if not src.exists():
        log.warning("Watchlist not found: %s", src)
        return None

    try:
        with open(src, encoding="utf-8") as f:
            data = json.load(f)

        result = WatchlistResult(
            generated_at=data.get("generated_at", ""),
            total_screened=data.get("total_screened", 0),
            total_pre_screen_passed=data.get("total_pre_screen_passed", 0),
            total_backtest_ran=data.get("total_backtest_ran", 0),
            total_passed=data.get("total_passed", 0),
            tiers=data.get("tiers", {}),
            symbols=[WatchlistSymbol(**s) for s in data.get("symbols", [])],
        )
        return result
    except Exception as exc:
        log.error("Failed to load watchlist from %s: %s", src, exc)
        return None


# ── Query helpers ─────────────────────────────────────────────

def get_tradeable_symbols(
    path: str | Path | None = None,
    tiers: List[str] | None = None,
) -> List[str]:
    """
    Return symbol list for the given tiers (default Tier 1 + Tier 2).

    Example::

        symbols = get_tradeable_symbols(tiers=["Tier 1"])
        # → ["BTC/USDT", "ETH/USDT", ...]
    """
    result = load_watchlist(path)
    if result is None:
        return []

    active_tiers = tiers or ["Tier 1", "Tier 2"]
    key_map = {
        "Tier 1": "tier_1",
        "Tier 2": "tier_2",
        "Tier 3": "tier_3",
        "Tier 4": "tier_4",
    }

    symbols: List[str] = []
    for tier_label in active_tiers:
        key = key_map.get(tier_label, "")
        symbols.extend(result.tiers.get(key, []))

    return symbols


def print_watchlist_summary(result: WatchlistResult) -> None:
    """Print a compact summary table to stdout."""
    print()
    print("=" * 70)
    print("  COIN UNIVERSE WATCHLIST")
    print("=" * 70)
    print(f"  Generated  : {result.generated_at[:19]}")
    print(f"  Screened   : {result.total_screened}")
    print(f"  Pre-screen : {result.total_pre_screen_passed} passed")
    print(f"  Backtested : {result.total_backtest_ran}")
    print(f"  Tier 1     : {len(result.tiers.get('tier_1', []))} symbols")
    print(f"  Tier 2     : {len(result.tiers.get('tier_2', []))} symbols")
    print(f"  Tier 3     : {len(result.tiers.get('tier_3', []))} symbols")
    print(f"  Tier 4     : {len(result.tiers.get('tier_4', []))} symbols  (watch only)")
    print(f"  Tradeable  : {result.total_passed} total")
    print()

    if not result.symbols:
        return

    header = f"  {'#':>3}  {'Symbol':<14} {'Tier':<8} {'Score':>5}  {'Ret/Yr':>7}  {'PF':>5}  {'WR%':>5}  {'MaxDD%':>7}"
    print(header)
    print("  " + "-" * 67)

    tradeable = [s for s in result.symbols if s.tier in ("Tier 1", "Tier 2", "Tier 3")]
    watch = [s for s in result.symbols if s.tier == "Tier 4"]
    for rank, sym in enumerate(tradeable, 1):
        print(
            f"  {rank:>3}  {sym.symbol:<14} {sym.tier:<8} {sym.score:>5.1f}"
            f"  {sym.return_per_year:>+7.1f}  {sym.profit_factor:>5.2f}"
            f"  {sym.win_rate * 100:>5.0f}  {sym.max_drawdown:>7.1f}"
        )
    if watch:
        print(f"\n  {'─'*67}")
        print(f"  Tier 4 (watch only): {', '.join(s.symbol for s in watch)}")
    print()
