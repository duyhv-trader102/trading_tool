"""
Top-Down MBA Alignment — Shared Module
=======================================

Single source of truth for multi-timeframe readiness alignment logic.
Used by:
  - ``market.base.scanner``  (2-TF: Monthly + Weekly)
  - ``EA.macro_trend_catcher.signals``  (3-TF: Monthly + Weekly + Daily)
  - ``EA.macro_trend_catcher.bot``  (3-TF live trading)

Core idea:
  Each timeframe produces an ``MBAMetadata`` (from ``build_mba_context``).
  ``build_alignment()`` extracts readiness state from each TF and packs
  it into an ``AlignmentState``.  The ``.is_aligned`` property checks
  that all active TFs are ready with matching ``ready_direction``.

2-TF vs 3-TF:
  When ``meta_d`` (Daily) is not provided, Daily is skipped and alignment
  only requires Monthly + Weekly to agree.
"""

from dataclasses import dataclass
from typing import Optional

from analytic.tpo_mba.schema import MBAMetadata
from analytic.tpo_mba.tracker import evaluate_session_readiness

# Sentinel: when meta_d is not passed at all → 2-TF mode (Daily skipped).
# Distinct from meta_d=None which means "Daily TF present but no data" → 3-TF with daily_ready=False.
_SKIP_DAILY = object()


# ──────────────────────────────────────────────────────────────
# AlignmentState
# ──────────────────────────────────────────────────────────────

@dataclass
class AlignmentState:
    """Snapshot of top-down readiness alignment.

    Supports 2-TF (M+W) or 3-TF (M+W+D) alignment.
    When ``daily_ready`` is ``None``, Daily is skipped entirely.

    V2.1: ``require_compression`` gate — each active TF must also be
    compressed (Normal / Neutral / 3-1-3) before alignment counts.
    """
    monthly_ready: bool = False
    monthly_direction: Optional[str] = None
    weekly_ready: bool = False
    weekly_direction: Optional[str] = None
    # Daily: None = skipped (2-TF mode), True/False = present (3-TF mode)
    daily_ready: Optional[bool] = None
    daily_direction: Optional[str] = None
    # V2.1 compression gate
    monthly_compressed: bool = True
    weekly_compressed: bool = True
    daily_compressed: bool = True
    require_compression: bool = False

    @property
    def _has_daily(self) -> bool:
        """True when Daily TF is present (3-TF mode)."""
        return self.daily_ready is not None

    @property
    def is_aligned(self) -> bool:
        """True when all active TFs are ready with matching direction.

        - Monthly + Weekly must both be ready.
        - Monthly direction must be bullish or bearish.
        - Weekly direction must match Monthly.
        - If Daily is present (3-TF), Daily must also be ready and match.
        - If ``require_compression``, every active TF must be compressed.
        """
        # Gate: M + W must be ready
        if not (self.monthly_ready and self.weekly_ready):
            return False
        # Compression gate for M + W
        if self.require_compression:
            if not (self.monthly_compressed and self.weekly_compressed):
                return False
        # Direction: M must have a direction
        if not self.monthly_direction:
            return False
        # Direction alignment: W must match M
        if self.weekly_direction != self.monthly_direction:
            return False
        # Daily (3-TF mode)
        if self._has_daily:
            if not self.daily_ready:
                return False
            if self.daily_direction != self.monthly_direction:
                return False
            if self.require_compression and not self.daily_compressed:
                return False
        return True

    @property
    def direction(self) -> Optional[str]:
        """Aligned direction, or None if not aligned."""
        if self.is_aligned:
            return self.monthly_direction
        return None

    def summary(self) -> str:
        """Human-readable one-line summary."""
        def _tf(ready, direction, compressed):
            if ready is None:
                return "-"
            r = '✓' if ready else '✗'
            c = '⊕' if compressed else '○'
            return f"{r}{c}({direction or '-'})"

        m = f"M:{_tf(self.monthly_ready, self.monthly_direction, self.monthly_compressed)}"
        w = f"W:{_tf(self.weekly_ready, self.weekly_direction, self.weekly_compressed)}"
        parts = [m, w]
        if self._has_daily:
            d = f"D:{_tf(self.daily_ready, self.daily_direction, self.daily_compressed)}"
            parts.append(d)
        status = "ALIGNED" if self.is_aligned else "WAITING"
        comp = " [compression-gate]" if self.require_compression else ""
        return f"[{status}] {' '.join(parts)}{comp}"


# ──────────────────────────────────────────────────────────────
# build_alignment
# ──────────────────────────────────────────────────────────────

def build_alignment(
    meta_m: Optional[MBAMetadata],
    meta_w: Optional[MBAMetadata],
    meta_d=_SKIP_DAILY,
    *,
    require_compression: bool = False,
) -> AlignmentState:
    """Build alignment state from MBAMetadata of each timeframe.

    Args:
        meta_m: Monthly MBAMetadata (from ``build_mba_context`` on closed W1 sessions).
        meta_w: Weekly  MBAMetadata (from ``build_mba_context`` on closed D1 sessions).
        meta_d: Daily   MBAMetadata (optional).
                - **Omitted** (default sentinel) → 2-TF scanner mode (Daily skipped).
                - ``None`` → 3-TF mode but Daily has no data (daily_ready=False).
                - ``MBAMetadata`` → 3-TF mode with Daily data.
        require_compression: V2.1 gate — each TF's last session must be
            compressed (Normal / Neutral / 3-1-3) for alignment to hold.

    Returns:
        AlignmentState with readiness/direction/compression populated.
    """
    def _extract(meta: Optional[MBAMetadata]):
        if meta is None:
            return False, None, False
        return meta.is_ready, meta.ready_direction, meta.is_compression

    m_ready, m_dir, m_comp = _extract(meta_m)
    w_ready, w_dir, w_comp = _extract(meta_w)

    if meta_d is _SKIP_DAILY:
        # 2-TF mode: Daily not present at all
        d_ready, d_dir, d_comp = None, None, True
    else:
        # 3-TF mode: Daily present (could be None = no data → ready=False)
        d_ready, d_dir, d_comp = _extract(meta_d)

    return AlignmentState(
        monthly_ready=m_ready,
        monthly_direction=m_dir,
        weekly_ready=w_ready,
        weekly_direction=w_dir,
        daily_ready=d_ready,
        daily_direction=d_dir,
        monthly_compressed=m_comp,
        weekly_compressed=w_comp,
        daily_compressed=d_comp,
        require_compression=require_compression,
    )


# ══════════════════════════════════════════════════════════════
# TFRegime — per-timeframe computed regime
# ══════════════════════════════════════════════════════════════

@dataclass
class TFRegime:
    """Per-timeframe regime state for signal evaluation.

    Computed from ``MBAMetadata`` + optional live session data.
    Used by ``evaluate_overall_signal()`` to determine multi-TF READY signal.

    Fields
    ------
    status : str
        ``"IN BALANCE"`` — price inside MBA outer edges.
        ``"BREAKOUT"``   — price exceeded 3-1-3 outer distribution.
        ``"WAITING FOR DATA"`` — no MBA detected yet.
    trend : str
        Expected direction: ``"bullish"`` / ``"bearish"`` / ``"neutral"``.
        Source priority: BREAKOUT direction > READY direction > imbalance
        direction.
    is_ready : bool
        Per-TF readiness.  Requires ``IN BALANCE`` + metadata ready +
        a valid ``ready_direction``.
    ready_direction : str | None
        ``"bullish"`` / ``"bearish"`` when ready; ``None`` otherwise.
    is_compressed : bool
        V2.1 compression gate — last session was Normal/Neutral/3-1-3.
    """
    status: str = "WAITING FOR DATA"
    trend: str = "neutral"
    is_ready: bool = False
    ready_direction: Optional[str] = None
    is_compressed: bool = False


def build_tf_regime(
    metadata: Optional[MBAMetadata],
    sessions: Optional[list] = None,
) -> TFRegime:
    """Compute per-timeframe regime from MBAMetadata + sessions.

    This is the **single source of truth** for per-TF status/trend/readiness
    computation.  Both ``market.base.scanner`` and ``EA`` strategies should
    call this instead of computing status inline.

    Args:
        metadata: Output of ``build_mba_context()``.  When ``None``,
            returns a default ``WAITING FOR DATA`` regime.
        sessions: Full TPO session list (including potentially open last
            session).  Required for BREAKOUT detection via MBA outer
            edges.  When ``None``, assumes ``IN BALANCE`` (backward compat
            for callers that only have metadata).

    Returns:
        Populated ``TFRegime``.
    """
    regime = TFRegime()

    if not metadata or not metadata.current_mba:
        return regime  # WAITING FOR DATA

    mba = metadata.current_mba

    # ── 1. Status: BREAKOUT vs IN BALANCE ──────────────────────
    is_above = False
    is_below = False

    if sessions and len(sessions) > 0:
        # BREAKOUT = a session *after* the MBA was established exceeded
        # the outer boundaries.  The mother session itself is excluded:
        # its raw session_high/low trivially spans the distribution edges
        # it defined (outer_high <= session_high by construction).
        # Using temporal ordering (> mother_start) rather than identity
        # makes this robust to future changes in how tracker picks mother.
        mother_start = mba.mother_session.session_start if mba.mother_session else None
        post_mother = (
            [s for s in sessions if s.session_start > mother_start]
            if mother_start is not None
            else sessions
        )
        if post_mother and (mba.outer_high is not None or mba.outer_low is not None):
            last_sess = post_mother[-1]
            upper = mba.outer_high if mba.outer_high is not None else mba.area_high
            lower = mba.outer_low if mba.outer_low is not None else mba.area_low
            is_above = last_sess.session_high > upper
            is_below = last_sess.session_low < lower

        regime.status = "BREAKOUT" if (is_above or is_below) else "IN BALANCE"
    else:
        # No sessions → can't detect breakout; assume IN BALANCE
        regime.status = "IN BALANCE"

    # ── 2. Trend (breakout dir > imbalance dir) ───────────────
    imb_dir = (mba.imbalance_direction or "").lower()
    if is_above:
        regime.trend = "bullish"
    elif is_below:
        regime.trend = "bearish"
    elif imb_dir in ("bullish", "bearish"):
        regime.trend = imb_dir
    else:
        regime.trend = "neutral"

    # ── 3. Per-TF readiness ────────────────────────────────────
    if regime.status == "IN BALANCE":
        # IN BALANCE readiness: from MBA metadata (build_mba_context)
        is_metadata_ready = metadata.is_ready
        ready_dir = metadata.ready_direction if is_metadata_ready else None
        regime.is_ready = is_metadata_ready and ready_dir is not None
        regime.ready_direction = ready_dir if regime.is_ready else None
    elif regime.status == "BREAKOUT":
        # BREAKOUT readiness — core principle:
        #   breakout from 3-1-3 distribution = new beginning = READY
        #   in the breakout direction.
        # Two sub-cases:
        #   a) Latest session still OPEN  → automatically READY
        #      (breakout in progress, direction is clear).
        #   b) Latest session CLOSED → evaluate that session's
        #      readiness using normal MBA readiness rules
        #      (session type, minus dev, conflicts …).
        breakout_dir = "bullish" if is_above else "bearish"
        if sessions:
            last_session = sessions[-1]
            if not last_session.is_closed:
                # (a) Open session → READY in breakout direction
                regime.is_ready = True
                regime.ready_direction = breakout_dir
            else:
                # (b) Closed session → evaluate session readiness
                sess_ready, _, _ = evaluate_session_readiness(last_session)
                regime.is_ready = sess_ready
                regime.ready_direction = breakout_dir if sess_ready else None
        else:
            regime.is_ready = False
            regime.ready_direction = None

    # When READY, trend reflects expected move direction
    if regime.is_ready and regime.ready_direction:
        regime.trend = regime.ready_direction

    # ── 4. Compression (V2.1) ─────────────────────────────────
    regime.is_compressed = metadata.is_compression

    return regime


# ══════════════════════════════════════════════════════════════
# SignalResult + evaluate_overall_signal
# ══════════════════════════════════════════════════════════════

@dataclass
class SignalResult:
    """Result of multi-TF signal evaluation."""
    signal: str = ""                    # e.g. "READY (BULLISH)" or ""
    direction: Optional[str] = None     # "bullish" / "bearish" / None
    path: str = ""                      # "balance_aligned" / "breakout_ready"


def evaluate_overall_signal(
    monthly: TFRegime,
    weekly: TFRegime,
    daily: Optional[TFRegime] = None,
    *,
    allow_breakout_ready: bool = True,
    require_compression: bool = False,
) -> SignalResult:
    """Evaluate multi-TF READY signal — **single source of truth**.

    Centralised signal logic for scanner (2-TF) and EA (3-TF).

    All active TFs must be ``is_ready`` with aligned ``ready_direction``.
    Both ``IN BALANCE`` and ``BREAKOUT`` TFs can be ready (breakout from
    3-1-3 distribution triggers readiness in the breakout direction).

    Path labels:
      - ``"balance_aligned"`` — all TFs IN BALANCE + ready + aligned.
      - ``"breakout_ready"``  — at least one TF is BREAKOUT + ready.

    Args:
        monthly: Monthly regime (from ``build_tf_regime``).
        weekly:  Weekly  regime.
        daily:   Daily   regime (``None`` for 2-TF scanner mode).
        allow_breakout_ready: When ``False``, BREAKOUT TFs are excluded
            from readiness (only IN BALANCE TFs count).  Default ``True``.
        require_compression: V2.1 gate — every active TF must be
            compressed for the signal to fire.

    Returns:
        ``SignalResult`` with signal text, direction, and path.
    """
    use_daily = daily is not None

    # ── Compression gate ───────────────────────────────────────
    if require_compression:
        compressed = monthly.is_compressed and weekly.is_compressed
        if use_daily:
            compressed = compressed and daily.is_compressed
        if not compressed:
            return SignalResult()

    # ── Unified readiness check ────────────────────────────────
    # After the breakout-readiness rule, both IN BALANCE and BREAKOUT
    # TFs can be is_ready=True.  A signal fires when ALL active TFs
    # are ready with aligned directions.
    #
    # When allow_breakout_ready=False, only IN BALANCE TFs count as
    # ready (BREAKOUT TFs are excluded).
    def _effective_ready(tf: TFRegime) -> bool:
        if tf.status == "BREAKOUT" and not allow_breakout_ready:
            return False
        return tf.is_ready

    all_ready = _effective_ready(monthly) and _effective_ready(weekly)
    if use_daily:
        all_ready = all_ready and _effective_ready(daily)

    if all_ready:
        dirs = [monthly.ready_direction, weekly.ready_direction]
        if use_daily:
            dirs.append(daily.ready_direction)
        if all(d is not None and d == dirs[0] and d in ("bullish", "bearish") for d in dirs):
            # Determine path label from TF statuses
            has_breakout = (
                monthly.status == "BREAKOUT"
                or weekly.status == "BREAKOUT"
                or (use_daily and daily.status == "BREAKOUT")
            )
            path = "breakout_ready" if has_breakout else "balance_aligned"
            return SignalResult(
                signal=f"READY ({dirs[0].upper()})",
                direction=dirs[0],
                path=path,
            )

    return SignalResult()
