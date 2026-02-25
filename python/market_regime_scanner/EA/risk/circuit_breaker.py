"""
circuit_breaker.py — Daily/Weekly Loss Circuit Breaker
=======================================================

Monitors cumulative P&L and halts trading when drawdown thresholds
are breached. Essential for prop firm compliance.

Rules (from Prop_Firm_Upgrade_Roadmap.md):
- Daily loss limit: -X% of account balance → halt all new entries
- Weekly loss limit: -Y% of account balance → halt until next week
- Trailing drawdown: Track max equity, halt if equity drops Z% from peak
- Cool-off period: After halt, wait N minutes before re-enabling

Usage::

    breaker = CircuitBreaker(
        daily_limit_pct=4.0,
        weekly_limit_pct=8.0,
        trailing_dd_pct=10.0,
        cool_off_minutes=30,
    )

    if breaker.can_trade(current_equity, daily_pnl, weekly_pnl):
        # proceed with entry
        ...
    else:
        reason = breaker.halt_reason
        logger.warning(f"Trading halted: {reason}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CircuitBreaker:
    """
    Monitors P&L thresholds and decides whether trading is allowed.

    Parameters
    ----------
    daily_limit_pct : float
        Max daily loss as % of account balance (e.g. 4.0 = -4%).
    weekly_limit_pct : float
        Max weekly loss as % of account balance.
    trailing_dd_pct : float
        Max drawdown from equity peak as % (e.g. 10.0 = -10% from peak).
    cool_off_minutes : int
        Minutes to wait after halt before re-enabling.
    """

    daily_limit_pct: float = 4.0
    weekly_limit_pct: float = 8.0
    trailing_dd_pct: float = 10.0
    cool_off_minutes: int = 30

    # ── Internal state ───────────────────────────────────────────
    _equity_peak: float = field(default=0.0, repr=False)
    _halt_reason: Optional[str] = field(default=None, repr=False)
    _halt_time: Optional[datetime] = field(default=None, repr=False)

    @property
    def halt_reason(self) -> Optional[str]:
        """Return the reason trading was halted, or None if active."""
        return self._halt_reason

    @property
    def is_halted(self) -> bool:
        return self._halt_reason is not None

    def update_equity_peak(self, current_equity: float) -> None:
        """Track equity HWM for trailing drawdown."""
        if current_equity > self._equity_peak:
            self._equity_peak = current_equity

    def can_trade(
        self,
        current_equity: float,
        daily_pnl_pct: float,
        weekly_pnl_pct: float,
    ) -> bool:
        """
        Check if trading is allowed given current P&L state.

        Parameters
        ----------
        current_equity : float
            Current account equity.
        daily_pnl_pct : float
            Today's cumulative P&L as %.
        weekly_pnl_pct : float
            This week's cumulative P&L as %.

        Returns
        -------
        bool
            True if trading is permitted.
        """
        self._halt_reason = None
        self.update_equity_peak(current_equity)

        # Check daily limit
        if daily_pnl_pct <= -self.daily_limit_pct:
            self._halt_reason = f"Daily loss limit breached: {daily_pnl_pct:.2f}%"
            self._halt_time = datetime.now()
            return False

        # Check weekly limit
        if weekly_pnl_pct <= -self.weekly_limit_pct:
            self._halt_reason = f"Weekly loss limit breached: {weekly_pnl_pct:.2f}%"
            self._halt_time = datetime.now()
            return False

        # Check trailing drawdown from peak
        if self._equity_peak > 0:
            dd_pct = (self._equity_peak - current_equity) / self._equity_peak * 100
            if dd_pct >= self.trailing_dd_pct:
                self._halt_reason = (
                    f"Trailing DD breached: -{dd_pct:.2f}% from peak "
                    f"({self._equity_peak:.2f})"
                )
                self._halt_time = datetime.now()
                return False

        return True

    def reset(self) -> None:
        """Reset all state (e.g. start of new week)."""
        self._halt_reason = None
        self._halt_time = None
        self._equity_peak = 0.0
