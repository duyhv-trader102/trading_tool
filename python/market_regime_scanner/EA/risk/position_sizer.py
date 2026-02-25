"""
position_sizer.py — Risk-Based Position Sizing
================================================

Calculates position size based on:
1. Account risk budget (% of equity per trade)
2. Stop-loss distance (ATR-based or fixed pips)
3. Maximum position size (absolute cap)

Supports:
- Fixed fractional (Kelly-lite): risk X% per trade
- Volatility-adjusted: scale size by ATR
- Prop firm mode: hard cap on lot size / notional

Usage::

    sizer = PositionSizer(
        risk_pct=1.0,           # risk 1% per trade
        max_lot=5.0,            # hard cap
        prop_mode=True,         # conservative for funded account
    )

    lots = sizer.calculate(
        equity=10_000,
        stop_distance=50.0,     # pips or price distance
        pip_value=10.0,         # value per pip per lot
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PositionSizer:
    """
    Calculate position size from risk budget and stop distance.

    Parameters
    ----------
    risk_pct : float
        Percentage of equity to risk per trade (e.g. 1.0 = 1%).
    max_lot : float
        Absolute maximum lot size.
    min_lot : float
        Minimum lot size (broker constraint).
    lot_step : float
        Lot step granularity (e.g. 0.01).
    prop_mode : bool
        If True, apply extra conservative guardrails.
    max_risk_pct_prop : float
        Max risk % in prop mode (override risk_pct if exceeded).
    """

    risk_pct: float = 1.0
    max_lot: float = 10.0
    min_lot: float = 0.01
    lot_step: float = 0.01
    prop_mode: bool = False
    max_risk_pct_prop: float = 0.5

    def calculate(
        self,
        equity: float,
        stop_distance: float,
        pip_value: float = 1.0,
        atr: Optional[float] = None,
    ) -> float:
        """
        Compute lot size.

        Parameters
        ----------
        equity : float
            Current account equity.
        stop_distance : float
            Distance from entry to stop-loss (in price units or pips).
        pip_value : float
            Monetary value per pip per standard lot.
        atr : float, optional
            Current ATR for volatility-adjusted sizing.

        Returns
        -------
        float
            Lot size rounded to lot_step.
        """
        if stop_distance <= 0 or equity <= 0:
            return 0.0

        effective_risk = self.risk_pct
        if self.prop_mode:
            effective_risk = min(effective_risk, self.max_risk_pct_prop)

        risk_amount = equity * (effective_risk / 100.0)
        raw_lots = risk_amount / (stop_distance * pip_value)

        # Volatility adjustment: scale down when ATR is elevated
        if atr is not None and atr > 0:
            # Normalize: if ATR > 2x of stop_distance, reduce size
            vol_ratio = stop_distance / atr
            if vol_ratio < 1.0:
                raw_lots *= vol_ratio

        # Round to lot step
        lots = max(self.min_lot, min(raw_lots, self.max_lot))
        lots = round(lots / self.lot_step) * self.lot_step
        lots = round(lots, 8)  # avoid float artifacts

        return lots

    def max_position_value(self, equity: float) -> float:
        """Max notional value allowed (for portfolio guard integration)."""
        return equity * (self.risk_pct / 100.0) * 10  # rough 10:1 leverage cap
