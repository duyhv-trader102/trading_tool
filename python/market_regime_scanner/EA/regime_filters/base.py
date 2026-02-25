"""
Base class and gate for regime filters.

Every regime filter:
  1. ``build()``  — pre-compute a date→state lookup (called once)
  2. ``check()``  — query the lookup for a specific date
  3. Returns ``RegimeVerdict`` with ``blocked`` flag + reason
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Verdict ──────────────────────────────────────────────────────────────────

@dataclass
class RegimeVerdict:
    """Result of a regime filter check."""
    blocked: bool = False
    reason: str = ""
    filter_name: str = ""
    details: Dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        """True when NOT blocked (i.e. trade is allowed)."""
        return not self.blocked


# ─── Base class ───────────────────────────────────────────────────────────────

class BaseRegimeFilter(ABC):
    """Abstract base for all regime filters.

    Subclasses must implement:
      - ``name``   : human-readable filter name
      - ``build()`` : pre-compute internal lookup
      - ``check()`` : query the lookup for a given date
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. 'btc_regime', 'broad_market'."""
        ...

    @abstractmethod
    def build(self) -> None:
        """Pre-compute the internal lookup (called once before backtest)."""
        ...

    @abstractmethod
    def check(
        self,
        date_str: str,
        *,
        direction: str = "bullish",
        symbol: str = "",
    ) -> RegimeVerdict:
        """Check whether a trade is allowed on *date_str*.

        Parameters
        ----------
        date_str  : ISO date ``"YYYY-MM-DD"``
        direction : ``"bullish"`` or ``"bearish"``
        symbol    : the symbol being traded (some filters may skip self-ref)

        Returns
        -------
        RegimeVerdict
            ``.blocked = True`` means **do not trade**.
        """
        ...

    def get_state(self, date_str: str) -> str:
        """Optional: return human-readable state for logging."""
        return ""


# ─── Gate (chains multiple filters) ──────────────────────────────────────────

class RegimeGate:
    """Chains multiple regime filters; blocks if ANY filter says no.

    Usage::

        gate = RegimeGate([BtcRegimeFilter(...), BroadMarketFilter(...)])
        gate.build()          # pre-compute all lookups
        v = gate.check("2025-06-15", direction="bullish", symbol="ETH/USDT")
        if v.blocked:
            skip_trade(v.reason)
    """

    def __init__(self, filters: List[BaseRegimeFilter] | None = None):
        self.filters: List[BaseRegimeFilter] = filters or []

    def add(self, f: BaseRegimeFilter) -> "RegimeGate":
        """Fluent API: ``gate.add(BtcFilter()).add(BroadFilter())``."""
        self.filters.append(f)
        return self

    def build(self) -> None:
        """Build all filters (pre-compute lookups)."""
        for f in self.filters:
            logger.info("Building regime filter: %s", f.name)
            f.build()
            logger.info("  %s ready", f.name)

    def check(
        self,
        date_str: str,
        *,
        direction: str = "bullish",
        symbol: str = "",
    ) -> RegimeVerdict:
        """Run all filters; return first blocking verdict (short-circuit)."""
        for f in self.filters:
            v = f.check(date_str, direction=direction, symbol=symbol)
            if v.blocked:
                return v
        return RegimeVerdict(blocked=False)

    def check_all(
        self,
        date_str: str,
        *,
        direction: str = "bullish",
        symbol: str = "",
    ) -> List[RegimeVerdict]:
        """Run ALL filters and return every verdict (for diagnostics)."""
        return [
            f.check(date_str, direction=direction, symbol=symbol)
            for f in self.filters
        ]

    @property
    def filter_names(self) -> List[str]:
        return [f.name for f in self.filters]
