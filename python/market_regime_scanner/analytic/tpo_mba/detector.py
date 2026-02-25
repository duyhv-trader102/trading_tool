import logging
from typing import List, Optional
from core.tpo import TPOResult, SessionType
from analytic.tpo_regime.schema import RegimeFeatures, RegimeResult

logger = logging.getLogger(__name__)


def _compute_va_overlap(r1: TPOResult, r2: TPOResult) -> float:
    """VA Overlap ratio between two sessions."""
    overlap_h = min(r1.vah, r2.vah)
    overlap_l = max(r1.val, r2.val)
    overlap = max(0, overlap_h - overlap_l)
    r1_va = r1.value_area_range
    return overlap / r1_va if r1_va > 0 else 0.0

# ------------------------------------------------------------------ #
#  Directional Move Detection                                         #
# ------------------------------------------------------------------ #

def _va_shift_direction(s_curr: TPOResult, s_prev: TPOResult) -> Optional[str]:
    """Determine VA shift direction: 'up', 'down', or None."""
    va_mid_curr = (s_curr.vah + s_curr.val) / 2
    va_mid_prev = (s_prev.vah + s_prev.val) / 2
    if va_mid_curr > va_mid_prev:
        return "up"
    elif va_mid_curr < va_mid_prev:
        return "down"
    return None

def _poc_shift_direction(s_curr: TPOResult, s_prev: TPOResult) -> Optional[str]:
    """Determine POC shift direction: 'up', 'down', or None."""
    if s_curr.poc > s_prev.poc:
        return "up"
    elif s_curr.poc < s_prev.poc:
        return "down"
    return None

def find_last_directional_move(
    sessions: List[TPOResult],
    end_index: Optional[int] = None,
) -> Optional[dict]:
    """
    Scan right-to-left to find the last directional move (imbalance origin).

    Imbalance = market leaves old balance to seek new balance, pushed by
    one or more directional moves.

    Directional move criteria:
      - A Trend session → immediate directional move.
      - VA overlap < 40% with previous session → definite directional move.
      - VA overlap 40-60% AND VA shift & POC shift in SAME direction
        → still directional move.

    Balancing (skip & keep scanning left):
      - VA overlap ≥ 60%  → clearly balancing.
      - VA overlap 40-60% but VA shift & POC shift in opposite
        directions → balancing.

    Returns:
        dict with:
          - index: index in the sessions list
          - session: the TPOResult
          - reason: 'trend_session' | 'low_va_overlap' | 'directional_va_poc_shift'
          - direction: 'bullish' | 'bearish' | None
          - va_overlap_pct: float
        or None if no directional move found.
    """
    if len(sessions) < 2:
        return None

    start = (end_index - 1) if end_index is not None else (len(sessions) - 1)
    for i in range(start, 0, -1):
        curr = sessions[i]
        if not curr.is_closed:
            continue

        prev = sessions[i - 1]
        if not prev.is_closed:
            continue

        # --- Fast path: Trend session → immediate directional move ---
        if curr.session_type == SessionType.TREND:
            va_dir = _va_shift_direction(curr, prev)
            direction = "bullish" if va_dir == "up" else ("bearish" if va_dir == "down" else None)
            return {
                "index": i,
                "session": curr,
                "reason": "trend_session",
                "direction": direction,
                "va_overlap_pct": _compute_va_overlap(curr, prev),
            }

        # --- Overlap-based evaluation ---
        overlap = _compute_va_overlap(curr, prev)

        if overlap >= 0.60:
            # High overlap → balancing, keep scanning left
            continue

        if overlap < 0.40:
            # Low overlap → definite directional move
            va_dir = _va_shift_direction(curr, prev)
            direction = "bullish" if va_dir == "up" else ("bearish" if va_dir == "down" else None)
            return {
                "index": i,
                "session": curr,
                "reason": "low_va_overlap",
                "direction": direction,
                "va_overlap_pct": overlap,
            }

        # --- Ambiguous zone: 40% <= overlap < 60% ---
        va_dir = _va_shift_direction(curr, prev)
        poc_dir = _poc_shift_direction(curr, prev)

        if va_dir and poc_dir and va_dir == poc_dir:
            # Same direction → still directional move
            direction = "bullish" if va_dir == "up" else "bearish"
            return {
                "index": i,
                "session": curr,
                "reason": "directional_va_poc_shift",
                "direction": direction,
                "va_overlap_pct": overlap,
            }
        else:
            # Opposite or unclear → balancing, keep scanning left
            continue

    return None


def _detect_responsive_activity(
    session: TPOResult,
    imbalance_direction: str,
) -> dict:
    """
    Detect responsive participant activity in a session given a known
    imbalance direction (from the last directional move).

    Since the VA shift direction is already known:
      - Bullish imbalance → buying = initiating, selling = responsive
      - Bearish imbalance → selling = initiating, buying = responsive

    Returns dict of boolean flags for each activity type.
    """
    poc = session.poc
    close = session.close_price
    h_limit = poc + (session.vah - poc) * 0.5
    l_limit = poc - (poc - session.val) * 0.5

    selling_tpos = session.tpo_counts_up    # above POC
    buying_tpos = session.tpo_counts_down   # below POC

    result = {
        # Initiating (trend-following)
        "initiating_buying_RE": False,
        "initiating_buying_in_VA": False,
        "initiating_buying_unfair_low": False,
        "initiating_selling_RE": False,
        "initiating_selling_in_VA": False,
        "initiating_selling_unfair_high": False,
        # Responsive (counter-trend)
        "responsive_buying_RE": False,
        "responsive_buying_in_VA": False,
        "responsive_buying_unfair_low": False,
        "responsive_selling_RE": False,
        "responsive_selling_in_VA": False,
        "responsive_selling_unfair_high": False,
    }

    if imbalance_direction == "bullish":
        # Buying = initiating (trend-following)
        if session.ib_extension_up > 0:
            result["initiating_buying_RE"] = True
        if buying_tpos > selling_tpos:
            result["initiating_buying_in_VA"] = True
        if session.unfair_low is not None and close > session.val:
            tail_len = round((session.unfair_low[1] - session.unfair_low[0]) / session.block_size) + 1
            if tail_len >= 2:
                result["initiating_buying_unfair_low"] = True

        # Selling = responsive (counter-trend)
        if session.ib_extension_down > 0:
            result["responsive_selling_RE"] = True
        if selling_tpos > buying_tpos and close > h_limit:
            result["responsive_selling_in_VA"] = True
        if session.unfair_high is not None and close < session.vah:
            tail_len = round((session.unfair_high[1] - session.unfair_high[0]) / session.block_size) + 1
            if tail_len >= 2:
                result["responsive_selling_unfair_high"] = True

    elif imbalance_direction == "bearish":
        # Selling = initiating (trend-following)
        if session.ib_extension_down > 0:
            result["initiating_selling_RE"] = True
        if selling_tpos > buying_tpos:
            result["initiating_selling_in_VA"] = True
        if session.unfair_high is not None and close < session.vah:
            tail_len = round((session.unfair_high[1] - session.unfair_high[0]) / session.block_size) + 1
            if tail_len >= 2:
                result["initiating_selling_unfair_high"] = True

        # Buying = responsive (counter-trend)
        if session.ib_extension_up > 0:
            result["responsive_buying_RE"] = True
        if buying_tpos > selling_tpos and close < l_limit:
            result["responsive_buying_in_VA"] = True
        if session.unfair_low is not None and close > session.val:
            tail_len = round((session.unfair_low[1] - session.unfair_low[0]) / session.block_size) + 1
            if tail_len >= 2:
                result["responsive_buying_unfair_low"] = True

    return result


def _has_any_responsive(activity: dict, imbalance_direction: str) -> bool:
    """Check if any responsive flag is True for the given imbalance direction."""
    if imbalance_direction == "bullish":
        return any([
            activity["responsive_selling_RE"],
            activity["responsive_selling_in_VA"],
            activity["responsive_selling_unfair_high"],
        ])
    elif imbalance_direction == "bearish":
        return any([
            activity["responsive_buying_RE"],
            activity["responsive_buying_in_VA"],
            activity["responsive_buying_unfair_low"],
        ])
    return False


def _has_any_initiating(activity: dict, imbalance_direction: str) -> bool:
    """Check if any initiating flag is True for the given imbalance direction."""
    if imbalance_direction == "bullish":
        return any([
            activity["initiating_buying_RE"],
            activity["initiating_buying_in_VA"],
            activity["initiating_buying_unfair_low"],
        ])
    elif imbalance_direction == "bearish":
        return any([
            activity["initiating_selling_RE"],
            activity["initiating_selling_in_VA"],
            activity["initiating_selling_unfair_high"],
        ])
    return False


def _build_regime_result(
    session: TPOResult,
    prev_session: Optional[TPOResult],
    regime: str,
    direction: Optional[str],
    rules: List[str],
    activity: dict,
    imbalance_direction: Optional[str] = None,
) -> RegimeResult:
    """
    Build a RegimeResult from session data + responsive activity analysis.
    Confidence is computed internally from responsive/initiating signals.
    """
    # Compute basic features
    session_range = session.session_high - session.session_low
    poc_prev = prev_session.poc if prev_session else None
    poc_shift = abs(session.poc - poc_prev) if poc_prev else 0
    poc_shift_pct = poc_shift / session_range if session_range > 0 else 0

    va_overlap_pct = 0.0
    va_expanding = False
    if prev_session:
        va_overlap_pct = _compute_va_overlap(session, prev_session)
        va_expanding = session.value_area_range > prev_session.value_area_range

    # Collect initiating/responsive signal names
    initiating_signals = [k for k, v in activity.items() if v and k.startswith("initiating_")]
    responsive_signals = [k for k, v in activity.items() if v and k.startswith("responsive_")]

    features = RegimeFeatures(
        poc=session.poc,
        poc_prev=poc_prev,
        poc_shift=poc_shift,
        poc_shift_pct=poc_shift_pct,
        va_high=session.vah,
        va_low=session.val,
        va_range=session.value_area_range,
        va_overlap_pct=va_overlap_pct,
        va_expanding=va_expanding,
        single_print_count=len(session.single_prints),
        single_print_pct=len(session.single_prints) * session.block_size / session_range if session_range > 0 else 0,
        minus_dev_count=len(session.minus_development),
        has_unfair_high=session.unfair_high is not None,
        has_unfair_low=session.unfair_low is not None,
        ib_range=session.ib_range,
        ib_extension_up=session.ib_extension_up,
        ib_extension_down=session.ib_extension_down,
        day_type=session.session_type,
        responsive_high=activity.get("responsive_selling_unfair_high", False),
        responsive_low=activity.get("responsive_buying_unfair_low", False),
        responsive_buying_in_VA=activity.get("responsive_buying_in_VA", False),
        responsive_selling_in_VA=activity.get("responsive_selling_in_VA", False),
        has_range_extension=(session.ib_extension_up > 0 and session.ib_extension_down > 0),
        session_range=session_range,
        close_in_va=(session.val <= session.close_price <= session.vah),
        total_tpo=session.total_tpo,
        tpo_above_poc=session.tpo_balance[0],
        tpo_below_poc=session.tpo_balance[1],
        close_price=session.close_price,
        distribution=session.distribution,
        prior_direction=imbalance_direction,
        initiating_signals=initiating_signals,
        responsive_signals=responsive_signals,
    )

    ready = False
    if session.distribution and session.distribution.ready_to_move:
        ready = True

    # Auto-compute confidence from signals
    n_responsive = len(responsive_signals)
    n_initiating = len(initiating_signals)
    if regime == "BALANCE":
        confidence = min(0.95, 0.70 + n_responsive * 0.05)
    else:
        confidence = min(0.90, 0.60 + n_initiating * 0.05)

    return RegimeResult(
        regime=regime,
        confidence=confidence,
        direction=direction,
        control_price=session.poc,
        range_high=session.vah if regime == "BALANCE" else session.session_high,
        range_low=session.val if regime == "BALANCE" else session.session_low,
        features=features,
        rules_triggered=rules,
        ready_to_move=ready,
    )


def find_first_balance_move(
    sessions: List[TPOResult],
    directional_move: Optional[dict] = None,
) -> Optional[RegimeResult]:
    """
    Starting from the last directional move, scan forward (left-to-right)
    to find the first balance session (= 1st MBA).

    Logic:
      1. Find last directional move (imbalance origin).
      2. If the imbalance session is NOT closed → search further left
         for another closed directional move.
      3. Scan forward from that session for responsive participation.
      4. If responsive found → BALANCE (1st MBA confirmed).
         If no responsive found → return None (no MBA yet).

    Args:
        sessions: Full list of TPOResult sessions.
        directional_move: Output from find_last_directional_move().
            If None, will call find_last_directional_move() internally.

    Returns:
        RegimeResult with regime='BALANCE' if 1st balance found.
        None if: no directional move or no responsive found.
    """
    if directional_move is None:
        directional_move = find_last_directional_move(sessions)
    if directional_move is None:
        return None

    # If the imbalance session is not closed, keep searching further left
    while True:
        dm_index = directional_move["index"]
        imbalance_dir = directional_move["direction"]
        if imbalance_dir is None:
            return None

        dm_session = directional_move["session"]
        if dm_session.is_closed:
            break  # found a valid closed directional move

        logger.debug(
            "Imbalance session #%d is not closed — searching further left",
            dm_index,
        )
        directional_move = find_last_directional_move(sessions, end_index=dm_index)
        if directional_move is None:
            return None

    # Find the first CLOSED session with responsive activity
    first_balance_idx = None
    first_balance_activity = None

    for i in range(dm_index, len(sessions)):
        sess = sessions[i]
        if not sess.is_closed:
            continue

        activity = _detect_responsive_activity(sess, imbalance_dir)
        if _has_any_responsive(activity, imbalance_dir):
            first_balance_idx = i
            first_balance_activity = activity
            break

    # No responsive found → no MBA yet
    if first_balance_idx is None:
        logger.debug("No responsive activity found after imbalance #%d — no MBA", dm_index)
        return None

    # Use the last closed session as the "current" for the result
    last_closed_idx = None
    for j in range(len(sessions) - 1, -1, -1):
        if sessions[j].is_closed:
            last_closed_idx = j
            break
    if last_closed_idx is None:
        return None

    current = sessions[last_closed_idx]
    prev = sessions[last_closed_idx - 1] if last_closed_idx > 0 else None
    current_activity = _detect_responsive_activity(current, imbalance_dir)

    # Responsive found → BALANCE (1st MBA)
    rules = [f"directional_move_{directional_move['reason']}"]
    responsive_keys = [k for k, v in first_balance_activity.items() if v and k.startswith("responsive_")]
    for rk in responsive_keys:
        rules.append(f"first_balance_at_{first_balance_idx}_{rk}")

    return _build_regime_result(
        session=current,
        prev_session=prev,
        regime="BALANCE",
        direction=imbalance_dir,
        rules=rules,
        activity=current_activity,
        imbalance_direction=imbalance_dir,
    )


def is_session_closed(session: TPOResult, period: Optional[str] = None) -> bool:
    """Check if session is closed."""
    return session.is_closed
