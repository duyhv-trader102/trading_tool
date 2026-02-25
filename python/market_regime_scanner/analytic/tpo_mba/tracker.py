"""
MBA Tracker — Track balance area evolution from 1st MBA to current state.

Responsibilities:
  - track_mba_evolution(): Scan from 1st MBA forward, build MBAUnit chain
  - get_current_mba(): Return the last valid MBA (may differ from 1st)
  - detect_mba_break(): Detect when price leaves MBA

Uses detector.py for finding the imbalance origin + 1st balance session.
"""

import logging
from typing import List, Optional, Tuple

from core.tpo import TPOResult, SessionType
from analytic.tpo_mba.schema import MBAUnit, MacroBalanceArea, MBAReadiness, MBAMetadata
from analytic.tpo_mba.detector import (
    find_last_directional_move,
    find_first_balance_move,
    _compute_va_overlap,
    _detect_responsive_activity,
    _has_any_responsive,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  Constants                                                          #
# ------------------------------------------------------------------ #
_VA_OVERLAP_BALANCE_THRESHOLD = 0.40   # >= 40% overlap → still in MBA
_VA_OVERLAP_SHIFT_THRESHOLD = 0.50     # < 50% overlap with MBA → MBA shift/reset
_BREAKOUT_MARGIN = 0.0                 # price must exceed edge by this much


# ------------------------------------------------------------------ #
#  Internal helpers                                                   #
# ------------------------------------------------------------------ #

def _session_to_unit(
    session: TPOResult,
    index: int,
    source: str = "value_area",
) -> Optional[MBAUnit]:
    """Create an MBAUnit from a session's VA.  Returns None if session is not closed."""
    if not session.is_closed:
        return None
    return MBAUnit(
        area_high=session.vah,
        area_low=session.val,
        mother_index=index,
        mother_start=session.session_start,
        source=source,
        is_closed=True,
    )


def _structural_unit_from_session(session: TPOResult, index: int) -> Optional[MBAUnit]:
    """
    Try to build a structural MBAUnit from distribution (3-1-3).
    
    If the session has a complete distribution (3-1-3), use unfair extremes
    as MBA boundaries (the structural box).
    
    Returns MBAUnit with source='distribution' or None.
    """
    if not session.is_closed:
        return None
    dist = session.distribution
    if dist is None or not dist.is_complete:
        return None

    uf_h = session.unfair_high
    uf_l = session.unfair_low
    if uf_h is None or uf_l is None:
        return None

    # Use unfair extremes as structural boundaries:
    # unfair_high[1] (absolute top), unfair_low[0] (absolute bottom)
    area_high = uf_h[1]
    area_low = uf_l[0]
    if area_high <= area_low:
        return None

    return MBAUnit(
        area_high=area_high,
        area_low=area_low,
        mother_index=index,
        mother_start=session.session_start,
        source="distribution",
        is_closed=True,
    )


def _overlap_with_mba(session: TPOResult, mba_high: float, mba_low: float) -> float:
    """Compute how much of a session's VA overlaps with the MBA area."""
    overlap_h = min(session.vah, mba_high)
    overlap_l = max(session.val, mba_low)
    overlap = max(0.0, overlap_h - overlap_l)
    va_range = session.vah - session.val
    return overlap / va_range if va_range > 0 else 0.0


def _is_breakout(
    session: TPOResult,
    mba_high: float,
    mba_low: float,
    outer_high: Optional[float] = None,
    outer_low: Optional[float] = None,
) -> Optional[str]:
    """
    Detect MBA breakout.
    
    Breakout only applies when 3-1-3 structural outer edges (unfair high/low)
    exist. If no outer edges, no breakout is detected — the MBA chain
    continues and relies on overlap/shift logic instead.
    
    Returns:
        'bullish' if price breaks above 3-1-3 unfair high
        'bearish' if price breaks below 3-1-3 unfair low
        None if no breakout (including when no outer edges exist)
    """
    # No 3-1-3 unfair edges → no breakout concept applies
    if outer_high is None and outer_low is None:
        return None

    upper = outer_high if outer_high is not None else mba_high
    lower = outer_low if outer_low is not None else mba_low

    # Strict check: breakout only if price EXCEEDS the boundary
    # Use a tiny epsilon to ignore floating point noise but respect the edge
    if session.session_high > upper + 1e-9:
        return "bullish"
    if session.session_low < lower - 1e-9:
        return "bearish"
    return None


# ------------------------------------------------------------------ #
#  Core: Track MBA evolution                                          #
# ------------------------------------------------------------------ #

def track_mba_evolution(
    sessions: List[TPOResult],
    directional_move: Optional[dict] = None,
) -> Optional[MacroBalanceArea]:
    """
    Track MBA from 1st balance move through all subsequent sessions.
    
    Algorithm:
      1. Find directional move (imbalance) + 1st balance session
      2. Create initial MBAUnit from 1st balance session
      3. Scan forward session by session:
         a. Check for structural distribution (3-1-3) → strong unit
         b. Check VA overlap with current MBA:
            - High overlap → session stays in MBA, potentially expand/contract
            - Low overlap → MBA shift → reset with new anchor
         c. Check for breakout (price exceeds outer edges) → MBA broken
      4. Return final MacroBalanceArea with all units
    
    Args:
        sessions: Full list of TPOResult sessions.
        directional_move: Output from find_last_directional_move().
    
    Returns:
        MacroBalanceArea with complete evolution history, or None.
    """
    # Step 1: Find imbalance + 1st balance
    if directional_move is None:
        directional_move = find_last_directional_move(sessions)
    if directional_move is None:
        return None

    dm_index = directional_move["index"]
    imbalance_dir = directional_move["direction"]
    if imbalance_dir is None:
        return None

    dm_session = directional_move["session"]

    # Find first balance (session with responsive activity)
    first_bal_idx = _find_first_balance_idx(sessions, dm_index, imbalance_dir)
    if first_bal_idx is None:
        return None

    # Step 2: Create initial MBA from 1st balance session
    mother = sessions[first_bal_idx]
    units: List[MBAUnit] = []

    # Try structural first, fallback to VA
    unit = _structural_unit_from_session(mother, first_bal_idx)
    if unit is None:
        unit = _session_to_unit(mother, first_bal_idx)
    if unit is None:
        return None
    units.append(unit)

    # Track current MBA boundaries
    mba_high = unit.area_high
    mba_low = unit.area_low
    outer_high: Optional[float] = None
    outer_low: Optional[float] = None

    if unit.source == "distribution" and mother.unfair_high and mother.unfair_low:
        outer_high = mother.unfair_high[1]  # outer edge up
        outer_low = mother.unfair_low[0]    # outer edge down

    is_structural = unit.source == "distribution"
    last_unit_idx = first_bal_idx

    # Step 3: Scan forward from 1st balance to track evolution
    for i in range(first_bal_idx + 1, len(sessions)):
        sess = sessions[i]
        if not sess.is_closed:
            continue

        # 3a. Check breakout
        breakout = _is_breakout(sess, mba_high, mba_low, outer_high, outer_low)
        if breakout is not None:
            logger.debug(
                "MBA breakout %s at session #%d (%s)",
                breakout, i, sess.session_start,
            )
            # Breakout → current MBA is broken
            # Check if breakout session itself forms a new balance
            struct_unit = _structural_unit_from_session(sess, i)
            if struct_unit is not None:
                # New structural anchor after breakout
                units.append(struct_unit)
                mba_high = struct_unit.area_high
                mba_low = struct_unit.area_low
                if sess.unfair_high and sess.unfair_low:
                    outer_high = sess.unfair_high[1]
                    outer_low = sess.unfair_low[0]
                else:
                    outer_high = None
                    outer_low = None
                is_structural = True
                last_unit_idx = i
            else:
                # Breakout without new distribution → MBA chain ends
                # Mark end of last unit
                units[-1].end_index = i
                units[-1].end_start = sess.session_start
                # Try to seed new unit from VA if there's responsive activity
                activity = _detect_responsive_activity(sess, imbalance_dir)
                has_next = (i + 1 < len(sessions))
                
                # Rule: Breakout without 3-1-3 can still start a new balance unit if:
                # 1. It has internal responsive activity
                # 2. It's confirmed by the next session balancing with it (VA overlap)
                is_confirmed_by_next = False
                if has_next:
                    next_sess = sessions[i+1]
                    # Check if next session overlaps significantly with this breakout's VA (expansion/settlement)
                    next_overlap = _overlap_with_mba(next_sess, sess.vah, sess.val)
                    if next_overlap >= _VA_OVERLAP_BALANCE_THRESHOLD:
                        is_confirmed_by_next = True
                        logger.debug("Breakout confirmed by next session balance at #%d", i+1)

                if _has_any_responsive(activity, imbalance_dir) or is_confirmed_by_next:
                    new_unit = _session_to_unit(sess, i)
                    if new_unit is None:
                        break
                    units.append(new_unit)
                    mba_high = new_unit.area_high
                    mba_low = new_unit.area_low
                    outer_high = None
                    outer_low = None
                    is_structural = False
                    last_unit_idx = i
                else:
                    # True breakout without re-balance and no confirmation -> stop tracking
                    break
            continue

        # 3b. Check for structural distribution
        struct_unit = _structural_unit_from_session(sess, i)
        if struct_unit is not None:
            # New 3-1-3 within MBA → update/replace MBA with stronger anchor
            # Both evolution (high overlap) and shift (low overlap) result in
            # the same action: close current unit and anchor a new one.
            overlap_with_current = _overlap_with_mba(sess, mba_high, mba_low)
            if overlap_with_current < _VA_OVERLAP_SHIFT_THRESHOLD:
                logger.debug(
                    "MBA shift at session #%d (overlap=%.1f%%) → new anchor",
                    i, overlap_with_current * 100,
                )
            units[-1].end_index = i
            units[-1].end_start = sess.session_start
            units.append(struct_unit)
            mba_high = struct_unit.area_high
            mba_low = struct_unit.area_low
            if sess.unfair_high and sess.unfair_low:
                outer_high = sess.unfair_high[1]
                outer_low = sess.unfair_low[0]
            is_structural = True
            last_unit_idx = i
            continue

        # 3c. VA overlap check — is session still "in" MBA?
        overlap = _overlap_with_mba(sess, mba_high, mba_low)
        if overlap >= _VA_OVERLAP_BALANCE_THRESHOLD:
            # Still balancing within MBA — optionally expand boundaries
            # Expand MBA to encompass session's VA if it overlaps
            if sess.vah > mba_high:
                mba_high = sess.vah
            if sess.val < mba_low:
                mba_low = sess.val
            continue

        # 3d. Low overlap → potential MBA shift
        # Check if there's responsive activity (counter-trend)
        activity = _detect_responsive_activity(sess, imbalance_dir)
        if _has_any_responsive(activity, imbalance_dir):
            # Responsive at new level → MBA shift to new anchor
            logger.debug(
                "MBA shift (responsive) at session #%d (overlap=%.1f%%)",
                i, overlap * 100,
            )
            units[-1].end_index = i
            units[-1].end_start = sess.session_start
            new_unit = _session_to_unit(sess, i)
            if new_unit is not None:
                units.append(new_unit)
                mba_high = new_unit.area_high
                mba_low = new_unit.area_low
                outer_high = None
                outer_low = None
                is_structural = False
                last_unit_idx = i
        # else: low overlap, no responsive → directional continuation, skip

    # Step 4: Build result
    if not units:
        return None

    # Last unit = current MBA
    current_unit = units[-1]
    imbalance_sess = dm_session if dm_session.is_closed else None

    return MacroBalanceArea(
        area_high=mba_high,
        area_low=mba_low,
        source=current_unit.source,
        mother_session=sessions[current_unit.mother_index],
        mother_index=current_unit.mother_index,
        imbalance_session=imbalance_sess,
        imbalance_index=dm_index,
        imbalance_direction=imbalance_dir,
        is_structural=is_structural,
        outer_high=outer_high,
        outer_low=outer_low,
        all_units=units,
    )


def _find_first_balance_idx(
    sessions: List[TPOResult],
    dm_index: int,
    imbalance_dir: str,
) -> Optional[int]:
    """Find the first closed session with balance evidence from dm_index.
    
    Balance evidence (any one is sufficient):
      1. Responsive activity signals (RE, TPO balance, unfair tails)
      2. Complete distribution (3-1-3) — rejection on both sides
    """
    for i in range(dm_index, len(sessions)):
        sess = sessions[i]
        if not sess.is_closed:
            continue

        # 3-1-3 distribution = strongest balance evidence
        if _structural_unit_from_session(sess, i) is not None:
            return i

        # Responsive activity signals
        activity = _detect_responsive_activity(sess, imbalance_dir)
        if _has_any_responsive(activity, imbalance_dir):
            return i
    return None


# ------------------------------------------------------------------ #
#  Convenience: get current MBA                                       #
# ------------------------------------------------------------------ #

def get_current_mba(
    sessions: List[TPOResult],
    directional_move: Optional[dict] = None,
) -> Optional[MacroBalanceArea]:
    """
    One-call API: find imbalance → track MBA → return current MBA.
    
    This is the main entry point for consumers who just want
    the current macro balance area.
    
    Returns:
        MacroBalanceArea with area_high/area_low = current MBA boundaries,
        all_units = full history of MBA units in the chain.
        None if no MBA found.
    """
    return track_mba_evolution(sessions, directional_move)


# ------------------------------------------------------------------ #
#  MBA break status                                                   #
# ------------------------------------------------------------------ #

def detect_mba_break(
    sessions: List[TPOResult],
    mba: MacroBalanceArea,
) -> Optional[dict]:
    """
    Check if the latest **closed** session breaks the MBA.
    
    Only closed sessions are considered — an unclosed session's
    high/low is not finalised and cannot confirm a breakout.
    
    Args:
        sessions: Full list of TPOResult sessions.
        mba: Current MacroBalanceArea from track_mba_evolution().
    
    Returns:
        dict with:
          - direction: 'bullish' | 'bearish'
          - session_index: index of the breaking session
          - break_price: the price that exceeded MBA edge
          - edge_price: the MBA edge that was broken
        or None if MBA is intact.
    """
    if not sessions:
        return None

    # Breakout only when 3-1-3 unfair edges exist
    if mba.outer_high is None and mba.outer_low is None:
        return None

    # Only closed sessions can confirm a breakout
    last = sessions[-1]
    if not last.is_closed:
        return None

    upper = mba.outer_high if mba.outer_high is not None else mba.area_high
    lower = mba.outer_low if mba.outer_low is not None else mba.area_low

    if last.session_high > upper + _BREAKOUT_MARGIN:
        return {
            "direction": "bullish",
            "session_index": len(sessions) - 1,
            "break_price": last.session_high,
            "edge_price": upper,
        }

    if last.session_low < lower - _BREAKOUT_MARGIN:
        return {
            "direction": "bearish",
            "session_index": len(sessions) - 1,
            "break_price": last.session_low,
            "edge_price": lower,
        }

    return None


# ------------------------------------------------------------------ #
#  MBA Readiness for New Beginning                                    #
# ------------------------------------------------------------------ #

def _evaluate_session_bias(session: TPOResult) -> Tuple[bool, Optional[str]]:
    """
    Detect internal directional bias or conflict.
    
    Conflict = both bullish AND bearish initiating signals fire simultaneously.
    Bias = only one side fires.

    Returns:
        (has_conflict, bias)
    """
    poc = session.poc
    selling_tpos = session.tpo_counts_up    # above POC
    buying_tpos = session.tpo_counts_down   # below POC
    close = session.close_price
    h_limit = poc + (session.vah - poc) * 0.5
    l_limit = poc - (poc - session.val) * 0.5

    # ── Buy-side initiating signals ──
    buy_re = session.ib_extension_up > 0
    buy_va = buying_tpos > selling_tpos and close >= l_limit
    buy_uf = False
    if session.unfair_low is not None:
        tail_len = round(
            (session.unfair_low[1] - session.unfair_low[0]) / session.block_size
        ) + 1
        if tail_len >= 2:
            buy_uf = True

    # ── Sell-side initiating signals ──
    sell_re = session.ib_extension_down > 0
    sell_va = selling_tpos > buying_tpos and close <= h_limit
    sell_uf = False
    if session.unfair_high is not None:
        tail_len = round(
            (session.unfair_high[1] - session.unfair_high[0]) / session.block_size
        ) + 1
        if tail_len >= 2:
            sell_uf = True

    # ── For Neutral sessions, exclude RE AND unfair tails ─────────────
    # Neutral sessions by definition explore both sides; unfair tails
    # (excess at session extremes) are *expected* and should not trigger
    # conflict.  Only VA-based balance (TPO dominance + close position)
    # determines the directional bias of a neutral session.
    if session.session_type == SessionType.NEUTRAL:
        has_buy = buy_va
        has_sell = sell_va
    else:
        has_buy = buy_re or buy_va or buy_uf
        has_sell = sell_re or sell_va or sell_uf

    has_conflict = has_buy and has_sell
    bias = None
    if not has_conflict:
        if has_buy:
            bias = "bullish"
        elif has_sell:
            bias = "bearish"

    return has_conflict, bias


def evaluate_session_readiness(
    sess: TPOResult,
) -> Tuple[bool, List[str], Optional[str]]:
    """
    Evaluate if a single session is 'Ready' for a directional move.
    Encapsulates rules for 3-1-3, Normal, and Neutral sessions with conflict filtering.

    Prerequisite gate: if the session still has minus development zones the
    market has not fully explored its range → NOT READY regardless of type.

    Returns:
        (is_ready, signals, direction)
    """
    if not sess.is_closed:
        return False, [], None

    # ── Minus development gate (hard prerequisite) ──────────────────────────
    # Any single-print zone inside the body means the market "skipped" price
    # levels.  Until those gaps are filled or resolved, the session is not
    # structurally complete and cannot be READY for a new directional move.
    if sess.minus_development:
        return False, [], None

    signals: List[str] = []

    # ── Signal 1: 3-1-3 ready_to_move (strongest, bypasses conflict check) ──
    if (
        sess.distribution is not None
        and sess.distribution.ready_to_move
    ):
        signals.append("3-1-3_ready")

    # ── Conflict check for non-structural signals ──
    has_conflict, bias = _evaluate_session_bias(sess)

    if not has_conflict:
        # ── Signal 2: Normal session (not Normal Variation) ──
        if sess.session_type == SessionType.NORMAL:
            signals.append("normal_session")

        # ── Signal 3: Neutral session (failed extend both ways) ──
        if sess.session_type == SessionType.NEUTRAL:
            signals.append("neutral_session")

    if signals:
        if "3-1-3_ready" in signals:
            # 3-1-3 direction: VA dominance + close price confirmation.
            # Same logic as _evaluate_session_bias: TPO count must agree
            # with close position relative to h_limit / l_limit.
            buying = sess.tpo_counts_down   # TPOs below POC = buying
            selling = sess.tpo_counts_up    # TPOs above POC = selling
            close = sess.close_price
            poc = sess.poc
            h_limit = poc + (sess.vah - poc) * 0.5
            l_limit = poc - (poc - sess.val) * 0.5

            # buying dominates AND close not too low → bullish
            # selling dominates AND close not too high → bearish
            buy_confirmed = buying > selling and close >= l_limit
            sell_confirmed = selling > buying and close <= h_limit

            if buy_confirmed and not sell_confirmed:
                final_direction = "bullish"
            elif sell_confirmed and not buy_confirmed:
                final_direction = "bearish"
            else:
                # Conflict or equal → fallback to close vs open
                final_direction = "bullish" if close >= sess.open_price else "bearish"
        else:
            # Non-structural signals: use bias from conflict logic.
            # Fallback to close-vs-open only if bias is unclear.
            final_direction = bias
            if final_direction is None:
                final_direction = "bullish" if sess.close_price >= sess.open_price else "bearish"

        return True, signals, final_direction

    return False, [], None


def evaluate_mba_readiness(
    sessions: List[TPOResult],
    mba: MacroBalanceArea,
) -> MBAReadiness:
    """
    Evaluate whether an MBA is ready for a "new beginning" (Imbalance transition).
    
    Readiness signals (any one from a clean session triggers ready):
      1. Normal session (NOT Normal Variation) — balance settled, no IB extension
      2. Neutral session — failed extend both ways → saturation
      3. 3-1-3 distribution with ready_to_move — structural completion
    
    Filter: session must NOT have internal conflict (both responsive AND
    initiating signals active simultaneously). Exception: 3-1-3 ready_to_move
    bypasses the conflict check (structural completion is the strongest signal).
    
    Direction = close vs open of the last session that triggered readiness.
    
    Args:
        sessions: Full list of TPOResult sessions.
        mba: Current MacroBalanceArea from track_mba_evolution().
    
    Returns:
        MBAReadiness with is_ready, ready_direction, signals, etc.
    """
    result = MBAReadiness()

    if mba is None or mba.imbalance_direction is None:
        return result

    imb_dir = mba.imbalance_direction
    n_sessions = len(sessions)
    mother_idx = mba.mother_index
    conflict_count = 0

    # If MBA only has 1 session (mother), allow mother to trigger READY
    if mother_idx == n_sessions - 1:
        sess = sessions[mother_idx]
        is_ready, session_signals, direction = evaluate_session_readiness(sess)
        if is_ready:
            result.is_ready = True
            result.signals = session_signals
            result.trigger_session_index = mother_idx
            if "3-1-3_ready" in session_signals:
                result.ready_direction = direction
            else:
                close = sess.close_price
                if close > mba.area_high:
                    result.ready_direction = "bullish"
                elif close < mba.area_low:
                    result.ready_direction = "bearish"
                elif direction is not None:
                    # Inside MBA: use session's own bias
                    result.ready_direction = direction
                else:
                    result.ready_direction = imb_dir
        # Compression ratio
        if mba.area_range > 0:
            result.compression_ratio = sess.value_area_range / mba.area_range
        result.conflict_sessions = conflict_count
        return result

    # Else, scan sessions after mother
    start_idx = mother_idx + 1
    for i in range(start_idx, n_sessions):
        sess = sessions[i]
        is_closed = sess.is_closed
        has_conflict = False
        if is_closed:
            has_conflict, _ = _evaluate_session_bias(sess)
            if has_conflict:
                conflict_count += 1
        is_ready, session_signals, direction = evaluate_session_readiness(sess)
        if is_ready:
            result.is_ready = True
            result.signals = session_signals
            result.trigger_session_index = i
            if "3-1-3_ready" in session_signals:
                result.ready_direction = direction
            else:
                close = sess.close_price
                if close > mba.area_high:
                    result.ready_direction = "bullish"
                elif close < mba.area_low:
                    result.ready_direction = "bearish"
                elif direction is not None:
                    # Inside MBA: use session's own bias (latest ready
                    # session's direction overrides earlier readiness)
                    result.ready_direction = direction
                else:
                    result.ready_direction = imb_dir
    # Compression ratio
    if result.trigger_session_index is not None and mba.area_range > 0:
        trigger_sess = sessions[result.trigger_session_index]
        result.compression_ratio = trigger_sess.value_area_range / mba.area_range
    result.conflict_sessions = conflict_count
    return result


# ------------------------------------------------------------------ #
#  Summary helper                                                     #
# ------------------------------------------------------------------ #

def mba_summary(mba: MacroBalanceArea) -> str:
    """One-line summary string for logging/display."""
    n = len(mba.all_units)
    src = mba.source
    dr = mba.imbalance_direction or "?"
    return (
        f"MBA [{mba.area_low:.5g} - {mba.area_high:.5g}] "
        f"({src}, {dr}) "
        f"units={n} "
        f"mother=#{mba.mother_index}"
    )


# ------------------------------------------------------------------ #
#  Bridge: build_mba_context  (replaces deleted build_mba_metadata)   #
# ------------------------------------------------------------------ #

def build_mba_context(
    sessions: List[TPOResult],
    *,
    timeframe: str = "",
    symbol: str = "",
) -> MBAMetadata:
    """Build MBAMetadata using the new tracker workflow.

    This is a drop-in replacement for the old ``build_mba_metadata()``
    that was removed from detector.py.  It runs:

      1. find_last_directional_move  → imbalance origin
      2. track_mba_evolution         → MacroBalanceArea chain
      3. evaluate_mba_readiness      → readiness signals

    and packs the results into an :class:`MBAMetadata` for backward
    compatibility with scanner / observer / visualizer code.

    Parameters
    ----------
    sessions : list[TPOResult]
        **Closed** sessions only (caller should slice off open sessions).
    timeframe : str
        Label like ``"Monthly"`` or ``"W"`` (informational).
    symbol : str
        Trading symbol (informational).

    Returns
    -------
    MBAMetadata
    """
    # Enforce: strip any unclosed sessions at the tail
    while sessions and not sessions[-1].is_closed:
        sessions = sessions[:-1]

    meta = MBAMetadata(
        symbol=symbol,
        timeframe=timeframe,
        last_session_time=sessions[-1].session_start if sessions else None,
    )

    if len(sessions) < 3:
        return meta

    # 1. Find imbalance origin
    imb = find_last_directional_move(sessions)
    if imb is None:
        return meta


    # 2. Track MBA evolution
    mba = track_mba_evolution(sessions, imb)
    if mba is None:
        return meta

    meta.current_mba = mba
    meta.mba_continuity_count = len(mba.all_units)

    # 3. Evaluate readiness
    readiness = evaluate_mba_readiness(sessions, mba)
    meta.is_ready = readiness.is_ready
    meta.ready_direction = readiness.ready_direction
    meta.ready_for_new_beginning = readiness.is_ready
    meta.ready_reason = readiness.summary()
    meta.trigger_session_index = readiness.trigger_session_index

    # 3b. Direction override using the LATEST session's close vs MBA.
    #     The readiness may have triggered sessions ago; since then, price
    #     can have drifted above/below the MBA boundaries.  Re-derive
    #     direction from the most recent evidence.
    if meta.is_ready and sessions:
        last_close = sessions[-1].close_price
        if last_close is not None:
            trigger_signals = readiness.signals or []
            if "3-1-3_ready" not in trigger_signals:
                if last_close > mba.area_high:
                    meta.ready_direction = "bullish"
                elif last_close < mba.area_low:
                    meta.ready_direction = "bearish"
                # else: close inside MBA → preserve readiness.ready_direction
                # which already reflects the trigger session's bias
            # Update reason string to reflect final direction
            readiness.ready_direction = meta.ready_direction
            meta.ready_reason = readiness.summary()

    # V2.1 Compression gate: last closed session must show balance (nén).
    # MBA only READY if last session is_closed and compression=True
    if sessions:
        last = sessions[-1]
        is_compressed = False
        if last.session_type == SessionType.NORMAL:
            is_compressed = True
        elif last.session_type == SessionType.NEUTRAL:
            is_compressed = True
        elif (last.distribution is not None and last.distribution.ready_to_move):
            is_compressed = True
        meta.is_compression = is_compressed
        if is_compressed:
            meta.compression_count += 1
        meta.last_closed_session = last
        # If last session is not closed, MBA cannot be READY
        if not last.is_closed:
            meta.is_ready = False
            meta.ready_for_new_beginning = False
            meta.ready_reason = "NOT READY: last session not closed"
    else:
        meta.last_closed_session = None
    return meta
