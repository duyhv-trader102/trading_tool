"""
Direction detection & cross-timeframe alignment.

Analyses TPO profiles to determine dominant participant direction (buying vs
selling) and checks whether all timeframes agree on direction + readiness
for a new trend (a.k.a. "new beginning").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict

from core.tpo import TPOResult

if TYPE_CHECKING:
    from analytic.tpo_mba.schema import MBAMetadata

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Thresholds
# ─────────────────────────────────────────────────────────────────────

# TPO balance: above-POC ratio must exceed this to count as directional.
# ratio > 0.55 → bullish, < 0.45 → bearish, else neutral.
_TPO_BULLISH_THRESHOLD = 0.55
_TPO_BEARISH_THRESHOLD = 0.45

# IB extension is "meaningful" when it exceeds this fraction of IB range.
_EXT_MEANINGFUL_RATIO = 0.20


# ─────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────

@dataclass
class DirectionSignal:
    """
    Dominant participant direction from a session's TPO profile.

    Combines:
    - TPO balance in VA (buying vs selling pressure)
    - IB extension direction
    - Alignment between the two
    """

    # TPO imbalance in VA
    tpo_above_poc: int = 0   # buying pressure
    tpo_below_poc: int = 0   # selling pressure
    tpo_direction: str = "neutral"  # "bullish" | "bearish" | "neutral"

    # Extension
    ext_up: float = 0.0
    ext_down: float = 0.0
    ext_direction: str = "none"  # "bullish" | "bearish" | "both" | "none"

    # Alignment
    aligned: bool = False  # TPO direction == extension direction
    direction: str = "neutral"  # final dominant direction
    conflict: str = ""  # description if conflict exists

    def summary(self) -> str:
        arrow = {"bullish": "^", "bearish": "v", "neutral": "-"}.get(self.direction, "?")
        align_str = "Y" if self.aligned else f"N({self.conflict})"
        return (
            f"{arrow}{self.direction} "
            f"tpo={self.tpo_above_poc}^{self.tpo_below_poc}v "
            f"ext={self.ext_direction} {align_str}"
        )


@dataclass
class TimeframeSummary:
    """Condensed per-timeframe status used by TopDownConclusion."""

    tf_label: str
    has_mba: bool = False
    ready: bool = False
    ready_reason: str = ""
    direction: str = "neutral"   # from DirectionSignal
    mba_source: str = ""         # "distribution" / "unfair_extremes" / "value_area"
    compression_count: int = 0
    last_closed_compression: bool = False

    def one_line(self) -> str:
        mba_str = f"MBA({self.mba_source})" if self.has_mba else "no-MBA"
        rdy = "Y" if self.ready else "N"
        arrow = {"bullish": "^", "bearish": "v"}.get(self.direction, "-")
        parts = [f"{self.tf_label}: {mba_str}", f"ready={rdy}",
                 f"dir={arrow}{self.direction}"]
        if self.ready_reason:
            parts.append(f"({self.ready_reason})")
        if self.compression_count:
            parts.append(f"comp={self.compression_count}")
        return "  ".join(parts)


@dataclass
class TopDownConclusion:
    """
    Cross-timeframe alignment conclusion (Nested Gating).

    Hierarchy: Macro (Monthly) > Immediate (Weekly) > Micro (Daily).

    - Rule 1: Macro must be READY and has no next session
    - Rule 2: Macro must NOT have internal CONFLICT.
    - Rule 3: Immediate must be READY & Aligned for STRONG signal.
    """

    # Per-timeframe metadata: {"Monthly": MBAMetadata, ...}
    tf_metas: Dict[str, MBAMetadata] = field(default_factory=dict)

    # Per-timeframe condensed summaries
    tf_summaries: Dict[str, TimeframeSummary] = field(default_factory=dict)

    # Conclusion
    new_beginning: bool = False
    signal_strength: str = "NONE"  # STRONG, MODERATE, WEAK, NONE
    dominant_direction: str = "neutral"
    reason: str = ""

    def summary(self) -> str:
        icon = {"STRONG": "[S]", "MODERATE": "[M]", "WEAK": "[W]", "NONE": "[-]"}.get(self.signal_strength, "[-]")
        if self.new_beginning:
            return f"{icon} READY | {self.dominant_direction.upper()} ({self.signal_strength}) - {self.reason}"
        return f"{icon} {self.reason}"

    def detailed_summary(self) -> str:
        """Multi-line report mapping internal TFs to user terms (Macro/Immediate/Micro)."""
        lines = [self.summary()]
        
        # Mapping for display
        mapping = {
            "Monthly": "Macro",
            "Weekly": "Immediate",
            "Daily": "Micro"
        }
        
        for internal_tf, user_label in mapping.items():
            if internal_tf in self.tf_summaries:
                summary = self.tf_summaries[internal_tf]
                # Temporary override label for display
                original_label = summary.tf_label
                summary.tf_label = user_label
                lines.append(f"    {summary.one_line()}")
                summary.tf_label = original_label
                
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

def detect_direction(session: TPOResult) -> DirectionSignal:
    """
    Detect dominant participant direction from a session's TPO profile.

    Logic:
    1. TPO balance in VA → buying (above > below) or selling (below > above)
    2. Extension direction → bullish (up) or bearish (down) or both or none
    3. Alignment: if TPO direction matches extension direction → aligned.
       Conflict = e.g., buying dominates but extension is downward (failed buying).
    """
    sig = DirectionSignal()

    # ── TPO balance (buying vs selling) ──────────────────────────
    above, below = session.tpo_balance
    sig.tpo_above_poc = above
    sig.tpo_below_poc = below

    total = above + below
    if total > 0:
        ratio = above / total
        if ratio > _TPO_BULLISH_THRESHOLD:
            sig.tpo_direction = "bullish"
        elif ratio < _TPO_BEARISH_THRESHOLD:
            sig.tpo_direction = "bearish"
        else:
            sig.tpo_direction = "neutral"

    # ── Extension direction ──────────────────────────────────────
    sig.ext_up = session.ib_extension_up
    sig.ext_down = session.ib_extension_down

    ib = session.ib_range
    ext_threshold = ib * _EXT_MEANINGFUL_RATIO if ib > 0 else 0
    has_up = sig.ext_up > ext_threshold
    has_down = sig.ext_down > ext_threshold

    if has_up and has_down:
        sig.ext_direction = "both"
    elif has_up:
        sig.ext_direction = "bullish"
    elif has_down:
        sig.ext_direction = "bearish"
    else:
        sig.ext_direction = "none"

    # ── Alignment ────────────────────────────────────────────────
    _resolve_alignment(sig)

    return sig


def _build_tf_summary(tf: str, meta: MBAMetadata) -> TimeframeSummary:
    """Distil one MBAMetadata into a compact TimeframeSummary."""
    s = TimeframeSummary(tf_label=tf)
    s.has_mba = meta.has_mba
    s.ready = meta.has_mba and meta.ready_for_new_beginning
    s.ready_reason = meta.ready_reason
    s.compression_count = meta.compression_count
    s.last_closed_compression = meta.last_closed_is_compression
    if meta.mba:
        s.mba_source = meta.mba.source
    
    # Direction: prefer ready_direction when ready
    # If not ready, use direction_signal as "Bias" (for partial confluence)
    if s.ready and meta.ready_direction != "neutral":
        s.direction = meta.ready_direction
    elif meta.direction_signal:
        s.direction = meta.direction_signal.direction
        
    return s


def build_topdown_conclusion(
    tf_metas: Dict[str, MBAMetadata],
) -> TopDownConclusion:
    """
    Cross-timeframe alignment analysis (Nested Gating).

    Hierarchy: Macro (Monthly) > Immediate (Weekly) > Micro (Daily).
    """
    conclusion = TopDownConclusion(tf_metas=tf_metas)

    if not tf_metas:
        conclusion.reason = "no timeframes"
        return conclusion

    # Build per-TF summaries
    summaries = {}
    for tf, meta in tf_metas.items():
        summaries[tf] = _build_tf_summary(tf, meta)
    conclusion.tf_summaries = summaries

    # ── 1. Gate 1: Macro Readiness & Conflict ───────────────────
    macro = summaries.get("Monthly")
    if not macro or not macro.has_mba:
        conclusion.signal_strength = "NONE"
        conclusion.reason = "Macro: No MBA detected"
        return conclusion
        
    # Check for internal conflict in Macro (Monthly)
    macro_meta = tf_metas.get("Monthly")
    has_macro_conflict = macro_meta and macro_meta.direction_signal and not macro_meta.direction_signal.aligned
    
    if has_macro_conflict:
        conclusion.signal_strength = "NONE"
        conclusion.reason = f"Macro: Conflict detected ({macro_meta.direction_signal.conflict})"
        return conclusion

    if not macro.ready:
        conclusion.signal_strength = "NONE"
        conclusion.reason = "Macro: NOT READY (Waiting for distribution/compression)"
        return conclusion

    # Macro is READY and CLEAN
    conclusion.dominant_direction = macro.direction
    if conclusion.dominant_direction == "neutral":
        conclusion.signal_strength = "NONE"
        conclusion.reason = "Macro: Neutral (Indecision)"
        return conclusion

    # ── 2. Gate 2: Immediate Confirmation (Only if Macro READY) ──
    immediate = summaries.get("Weekly")
    immediate_status = "missing"
    
    if immediate:
        # Check for conflict in Immediate
        immediate_meta = tf_metas.get("Weekly")
        has_imm_conflict = immediate_meta and immediate_meta.direction_signal and not immediate_meta.direction_signal.aligned
        
        if has_imm_conflict:
            immediate_status = "conflict"
        elif immediate.ready and immediate.direction == conclusion.dominant_direction:
            immediate_status = "aligned_ready"
        elif immediate.direction == conclusion.dominant_direction:
            immediate_status = "aligned_bias"  # Not ready yet, but direction matches
        elif immediate.direction == "neutral":
            immediate_status = "neutral"
        else:
            immediate_status = "conflict"

    # ── 3. Gate 3: Micro Confirmation (Optional boost) ──────────
    micro = summaries.get("Daily")
    micro_aligned = False
    if micro and micro.direction == conclusion.dominant_direction:
        micro_aligned = True

    # ── 4. Determine Final Grade ────────────────────────────────
    
    # Nested results:
    if immediate_status == "aligned_ready":
        # Macro READY + Immediate READY -> STRONG
        strength = "STRONG"
        reason_suffix = "Full Confluence (Macro + Immediate READY)"
    elif immediate_status == "aligned_bias":
        # Macro READY + Immediate BIAS -> MODERATE
        strength = "MODERATE"
        reason_suffix = "Macro READY + Immediate Bias"
    elif immediate_status == "neutral" or immediate_status == "missing":
        # Macro READY but Immediate is unclear -> WEAK
        strength = "WEAK"
        reason_suffix = "Macro Lead (Immediate Neutral/Missing)"
    else: # conflict
        # Conflict on Immediate level kills the setup
        strength = "NONE" 
        reason_suffix = "Immediate Conflict"

    # Micro boost
    if strength == "MODERATE" and micro_aligned:
         reason_suffix += " + Micro Confirm"
    
    # Upgrade Weak to Moderate if Micro confirms strongly
    if strength == "WEAK" and micro_aligned:
        strength = "MODERATE"
        reason_suffix = "Macro Lead + Micro Confirm"

    conclusion.signal_strength = strength
    conclusion.new_beginning = strength in ("STRONG", "MODERATE")
    conclusion.reason = reason_suffix

    return conclusion


# ─────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────

def _resolve_alignment(sig: DirectionSignal) -> None:
    """Resolve final direction + alignment between TPO and extension signals."""
    if sig.tpo_direction == "neutral":
        # Neutral TPO → direction comes from extension (if unambiguous)
        if sig.ext_direction in ("both", "none"):
            sig.direction = "neutral"
            sig.aligned = sig.ext_direction != "both"
            if sig.ext_direction == "both":
                sig.conflict = "neutral_tpo+both_ext"
        else:
            sig.direction = sig.ext_direction
            sig.aligned = True
    elif sig.ext_direction in ("none", sig.tpo_direction):
        # No extension or same direction → aligned
        sig.direction = sig.tpo_direction
        sig.aligned = True
    elif sig.ext_direction == "both":
        # Bidirectional extension + directional TPO → use TPO but flag
        sig.direction = sig.tpo_direction
        sig.aligned = False
        sig.conflict = f"{sig.tpo_direction}_tpo+both_ext"
    else:
        # TPO says one way, extension the other → conflict (failed attempt)
        sig.direction = sig.tpo_direction  # TPO in VA is primary
        sig.aligned = False
        sig.conflict = f"{sig.tpo_direction}_tpo+{sig.ext_direction}_ext"
