"""
Top-Down Observer — Result data classes.

Typed containers for per-timeframe and per-symbol analysis results.
Replaces the ad-hoc ``dict`` previously returned by ``_analyze_single_tf``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import copy

from core.tpo import TPOResult
from analytic.tpo_mba.schema import MacroBalanceArea, MBAUnit, MBAMetadata
from analytic.tpo_confluence.tpo_alignment import TopDownConclusion
from analytic.tpo_mba.alignment import TFRegime, SignalResult


# ─────────────────────────────────────────────────────────────────────
# Per-timeframe
# ─────────────────────────────────────────────────────────────────────

@dataclass
class TimeframeResult:
    """Analysis output for a single timeframe of one symbol."""

    tf_label: str                          # "Monthly" / "Weekly" / "Daily"
    sessions: List[TPOResult]              # kept sessions (viz-pass block)
    period: str                            # data_tf, e.g. "W1", "D1", "H4"
    block_size: float                      # viz-pass block size
    regimes: List = field(default_factory=list)  # kept for backward compat (may be empty)
    meta: Optional[MBAMetadata] = None     # MBA + compression + readiness
    session_offset: int = 0                # sessions were trimmed from all_sessions[offset:]
    tf_regime: Optional[TFRegime] = None   # BREAKOUT/IN BALANCE/WAITING + trend

    @property
    def mba(self) -> Optional[MacroBalanceArea]:
        return self.meta.mba if self.meta else None

    def _remap_mba(self) -> Optional[MacroBalanceArea]:
        """Return MBA with indices remapped to the trimmed session window.

        MBA indices are absolute (relative to the full session list).
        The visualizer needs them relative to ``self.sessions``.
        Units entirely before the visible window are dropped to avoid
        overlapping bands at chart position 0.
        """
        if self.mba is None or self.session_offset == 0:
            return self.mba

        off = self.session_offset
        m = copy.copy(self.mba)
        m.mother_index = max(0, m.mother_index - off)
        if m.imbalance_index is not None:
            m.imbalance_index = max(0, m.imbalance_index - off)

        if m.all_units:
            remapped = []
            for i, u in enumerate(m.all_units):
                # A unit spans from its mother_index to the next unit's
                # mother_index.  Drop the unit if its *end* is still
                # before the visible window (i.e. next unit is also
                # before the window).  Always keep the last unit.
                is_last = (i == len(m.all_units) - 1)
                if not is_last:
                    next_idx = m.all_units[i + 1].mother_index
                    if next_idx < off:
                        continue  # entirely before visible window
                u2 = copy.copy(u)
                u2.mother_index = max(0, u2.mother_index - off)
                remapped.append(u2)
            m.all_units = remapped

        return m

    # ── dict interface for backward-compat with visualizer ───────
    def to_viz_dict(self) -> dict:
        """Return the dict that ``visualize_tpo_topdown`` expects."""
        return {
            "results": self.sessions,
            "period": self.period,
            "block_size": self.block_size,
            "regimes": self.regimes,
            "macro_balance": self._remap_mba(),
            "mba_metadata": self.meta,
            "tf_regime": self.tf_regime,
        }


# ─────────────────────────────────────────────────────────────────────
# Per-symbol
# ─────────────────────────────────────────────────────────────────────

@dataclass
class SymbolResult:
    """Aggregated analysis output for one symbol across all timeframes."""

    symbol: str
    has_weekend: bool = False
    tick_size: float = 0.0

    timeframes: Dict[str, TimeframeResult] = field(default_factory=dict)
    conclusion: Optional[TopDownConclusion] = None

    # V3 signal logic
    tf_regimes: Dict[str, TFRegime] = field(default_factory=dict)
    signal: Optional[SignalResult] = None

    @property
    def tf_metas(self) -> Dict[str, MBAMetadata]:
        """Convenience: {tf_label: MBAMetadata} for direction/conclusion."""
        return {
            tf: r.meta
            for tf, r in self.timeframes.items()
            if r.meta is not None
        }

    def viz_dict(self) -> Dict[str, dict]:
        """Return the multi-tf dict that ``visualize_tpo_topdown`` expects."""
        return {tf: r.to_viz_dict() for tf, r in self.timeframes.items()}
