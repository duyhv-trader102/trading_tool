"""
reconciler.py — Position Reconciliation
=========================================

Ensures EA internal state matches actual broker positions.
Detects and handles:
- Phantom positions (EA thinks open, broker closed)
- Orphan positions (broker open, EA doesn't know)
- Size mismatches
- State drift after reconnection

Usage::

    recon = Reconciler()
    diffs = recon.compare(ea_positions, broker_positions)
    if diffs:
        for d in diffs:
            logger.warning(f"Reconciliation issue: {d}")
        recon.auto_resolve(diffs)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class DiffType(Enum):
    """Types of reconciliation differences."""

    PHANTOM = "phantom"      # EA has position, broker doesn't
    ORPHAN = "orphan"        # Broker has position, EA doesn't
    SIZE_MISMATCH = "size"   # Both have it but different size
    PRICE_MISMATCH = "price" # Entry price differs


@dataclass
class PositionRecord:
    """Standardized position representation for reconciliation."""

    symbol: str
    direction: str  # "LONG" or "SHORT"
    size: float
    entry_price: float
    ticket: Optional[int] = None


@dataclass
class ReconciliationDiff:
    """A single discrepancy between EA and broker state."""

    diff_type: DiffType
    symbol: str
    ea_record: Optional[PositionRecord] = None
    broker_record: Optional[PositionRecord] = None
    detail: str = ""

    def __str__(self) -> str:
        return f"[{self.diff_type.value}] {self.symbol}: {self.detail}"


class Reconciler:
    """
    Compare EA state vs broker state and identify discrepancies.

    Parameters
    ----------
    size_tolerance : float
        Acceptable relative size difference (e.g. 0.01 = 1%).
    """

    def __init__(self, size_tolerance: float = 0.01):
        self.size_tolerance = size_tolerance

    def compare(
        self,
        ea_positions: List[PositionRecord],
        broker_positions: List[PositionRecord],
    ) -> List[ReconciliationDiff]:
        """
        Find all discrepancies between EA and broker positions.

        Returns list of ReconciliationDiff objects.
        """
        diffs: List[ReconciliationDiff] = []

        ea_map: Dict[str, PositionRecord] = {p.symbol: p for p in ea_positions}
        broker_map: Dict[str, PositionRecord] = {
            p.symbol: p for p in broker_positions
        }

        # Phantom: in EA but not in broker
        for sym, ea_pos in ea_map.items():
            if sym not in broker_map:
                diffs.append(
                    ReconciliationDiff(
                        diff_type=DiffType.PHANTOM,
                        symbol=sym,
                        ea_record=ea_pos,
                        detail=f"EA has {ea_pos.direction} {ea_pos.size}, broker has nothing",
                    )
                )
            else:
                broker_pos = broker_map[sym]
                # Size mismatch
                if ea_pos.size > 0:
                    rel_diff = abs(ea_pos.size - broker_pos.size) / ea_pos.size
                    if rel_diff > self.size_tolerance:
                        diffs.append(
                            ReconciliationDiff(
                                diff_type=DiffType.SIZE_MISMATCH,
                                symbol=sym,
                                ea_record=ea_pos,
                                broker_record=broker_pos,
                                detail=(
                                    f"EA size={ea_pos.size}, "
                                    f"broker size={broker_pos.size}"
                                ),
                            )
                        )

        # Orphan: in broker but not in EA
        for sym, broker_pos in broker_map.items():
            if sym not in ea_map:
                diffs.append(
                    ReconciliationDiff(
                        diff_type=DiffType.ORPHAN,
                        symbol=sym,
                        broker_record=broker_pos,
                        detail=(
                            f"Broker has {broker_pos.direction} {broker_pos.size}, "
                            f"EA has nothing"
                        ),
                    )
                )

        return diffs

    def auto_resolve(self, diffs: List[ReconciliationDiff]) -> List[str]:
        """
        Generate resolution actions for each diff.

        Returns list of action descriptions (actual execution is TODO).
        """
        actions: List[str] = []
        for d in diffs:
            if d.diff_type == DiffType.PHANTOM:
                actions.append(f"REMOVE from EA state: {d.symbol}")
            elif d.diff_type == DiffType.ORPHAN:
                actions.append(f"ADD to EA state: {d.symbol} (or close at broker)")
            elif d.diff_type == DiffType.SIZE_MISMATCH:
                actions.append(f"SYNC size for {d.symbol}: {d.detail}")
        return actions
