"""
portfolio_guard.py — Portfolio-Level Exposure Limits
=====================================================

Guards against over-concentration and correlated risk at portfolio level.

Rules:
- Max simultaneous positions (absolute count)
- Max exposure per sector / asset class
- Correlation guard: don't add position if highly correlated with existing
- Max total notional as % of equity

Usage::

    guard = PortfolioGuard(
        max_positions=5,
        max_sector_pct=40.0,
        max_total_exposure_pct=300.0,  # 3x leverage
    )

    if guard.can_add_position(symbol, sector, notional, current_portfolio):
        # proceed
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Position:
    """Represents an open position for portfolio tracking."""

    symbol: str
    sector: str
    notional: float
    direction: str  # "LONG" or "SHORT"
    entry_time: Optional[str] = None


@dataclass
class PortfolioGuard:
    """
    Portfolio-level risk constraints.

    Parameters
    ----------
    max_positions : int
        Maximum concurrent open positions.
    max_sector_pct : float
        Max % of total exposure allocated to one sector.
    max_total_exposure_pct : float
        Max total notional as % of equity.
    max_correlated : int
        Max positions in same sector.
    """

    max_positions: int = 5
    max_sector_pct: float = 40.0
    max_total_exposure_pct: float = 300.0
    max_correlated: int = 2

    _rejection_reason: Optional[str] = field(default=None, repr=False)

    @property
    def rejection_reason(self) -> Optional[str]:
        return self._rejection_reason

    def can_add_position(
        self,
        symbol: str,
        sector: str,
        notional: float,
        equity: float,
        current_positions: List[Position],
    ) -> bool:
        """
        Check if adding a new position violates portfolio constraints.

        Returns True if the new position is allowed.
        """
        self._rejection_reason = None

        # 1. Max positions check
        if len(current_positions) >= self.max_positions:
            self._rejection_reason = (
                f"Max positions reached ({self.max_positions})"
            )
            return False

        # 2. Duplicate symbol check
        existing_symbols = {p.symbol for p in current_positions}
        if symbol in existing_symbols:
            self._rejection_reason = f"Already have position in {symbol}"
            return False

        # 3. Sector concentration check
        sector_count = sum(1 for p in current_positions if p.sector == sector)
        if sector_count >= self.max_correlated:
            self._rejection_reason = (
                f"Sector '{sector}' already has {sector_count} positions "
                f"(max {self.max_correlated})"
            )
            return False

        # 4. Total exposure check
        total_notional = sum(p.notional for p in current_positions) + notional
        if equity > 0:
            exposure_pct = (total_notional / equity) * 100
            if exposure_pct > self.max_total_exposure_pct:
                self._rejection_reason = (
                    f"Total exposure {exposure_pct:.1f}% exceeds limit "
                    f"{self.max_total_exposure_pct:.1f}%"
                )
                return False

        # 5. Sector % of total exposure
        sector_notional = (
            sum(p.notional for p in current_positions if p.sector == sector)
            + notional
        )
        if total_notional > 0:
            sector_pct = (sector_notional / total_notional) * 100
            if sector_pct > self.max_sector_pct:
                self._rejection_reason = (
                    f"Sector '{sector}' would be {sector_pct:.1f}% of portfolio "
                    f"(max {self.max_sector_pct:.1f}%)"
                )
                return False

        return True

    def summary(self, current_positions: List[Position]) -> Dict[str, float]:
        """Return portfolio exposure summary."""
        by_sector: Dict[str, float] = {}
        for p in current_positions:
            by_sector[p.sector] = by_sector.get(p.sector, 0) + p.notional

        total = sum(p.notional for p in current_positions)
        return {
            "total_positions": len(current_positions),
            "total_notional": total,
            "by_sector": by_sector,
        }
