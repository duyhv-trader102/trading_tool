from typing import Optional, List, Tuple
from core.tpo import TPOResult
from analytic.tpo_context.schema import MarketContext, VAContext, ActivityType, Control

def _classify_va_relationship(curr: TPOResult, prev: TPOResult) -> Tuple[VAContext, float]:
    """
    Classify relationship between two Value Areas.
    Returns (VAContext, overlap_pct)
    """
    overlap_high = min(curr.vah, prev.vah)
    overlap_low = max(curr.val, prev.val)
    overlap = max(0, overlap_high - overlap_low)
    prev_range = prev.value_area_range
    overlap_pct = overlap / prev_range if prev_range > 0 else 0.0
    
    curr_mid = (curr.vah + curr.val) / 2
    prev_mid = (prev.vah + prev.val) / 2
    
    SIGNIFICANT_OVERLAP = 0.7
    
    is_inside = (curr.vah <= prev.vah) and (curr.val >= prev.val)
    is_outside = (curr.vah >= prev.vah) and (curr.val <= prev.val)
    
    if is_inside:
        return VAContext.INSIDE, overlap_pct
    if is_outside and overlap_pct > 0.8:
        return VAContext.OUTSIDE, overlap_pct
    if overlap_pct >= SIGNIFICANT_OVERLAP:
        if curr_mid > prev_mid:
            return VAContext.OVERLAP_HIGHER, overlap_pct
        elif curr_mid < prev_mid:
            return VAContext.OVERLAP_LOWER, overlap_pct
        else:
            return VAContext.UNCHANGED, overlap_pct

    if curr.val >= prev.vah:
        return VAContext.HIGHER, overlap_pct
    if curr.vah <= prev.val:
        return VAContext.LOWER, overlap_pct
    
    if curr_mid > prev_mid:
        return VAContext.HIGHER if overlap_pct < 0.3 else VAContext.OVERLAP_HIGHER, overlap_pct
    else:
        return VAContext.LOWER if overlap_pct < 0.3 else VAContext.OVERLAP_LOWER, overlap_pct

def _analyze_activity(curr: TPOResult, prev: TPOResult, context: VAContext) -> Tuple[ActivityType, Control, List[str]]:
    """Determine Activity Type and Control."""
    signals = []
    p_vah = prev.vah
    p_val = prev.val
    
    tpo_above = curr.tpo_balance[0]
    tpo_below = curr.tpo_balance[1]
    close = curr.close_price
    
    ext_up = curr.ib_extension_up > 0
    ext_down = curr.ib_extension_down > 0
    
    buyer_strength = 0
    seller_strength = 0
    
    # Buyers
    if curr.val >= p_vah or (curr.poc > p_vah):
        if ext_up:
            signals.append("initiating_buying_ext")
            buyer_strength += 2
        if close > p_vah:
            signals.append("close_above_prev_va")
            buyer_strength += 1
        if tpo_above > tpo_below:
            buyer_strength += 1
    elif curr.vah <= p_val or (curr.poc < p_val):
        if curr.unfair_low and close > curr.val:
            signals.append("responsive_buying_unfair_low")
            buyer_strength += 2
        if ext_down and close > curr.val:
            signals.append("failed_ext_down")
            buyer_strength += 1
        if ext_up:
            signals.append("responsive_buying_ext")
            buyer_strength += 2
        if close > p_val:
            signals.append("responsive_return_to_value")
            buyer_strength += 1
    else:
        if ext_up: 
            signals.append("buying_extension_in_value")
            buyer_strength += 1
        if close > curr.poc and tpo_above > tpo_below:
            buyer_strength += 1

    # Sellers
    if curr.vah <= p_val or (curr.poc < p_val):
        if ext_down:
            signals.append("initiating_selling_ext")
            seller_strength += 2
        if close < p_val:
            signals.append("close_below_prev_va")
            seller_strength += 1
        if tpo_below > tpo_above:
            seller_strength += 1
    elif curr.val >= p_vah or (curr.poc > p_vah):
        if curr.unfair_high and close < curr.vah:
            signals.append("responsive_selling_unfair_high")
            seller_strength += 2
        if ext_up and close < curr.vah:
            signals.append("failed_ext_up")
            seller_strength += 1
        if ext_down:
            signals.append("responsive_selling_ext")
            seller_strength += 2
        if close < p_vah:
            signals.append("responsive_return_to_value")
            seller_strength += 1
    else:
        if ext_down:
            signals.append("selling_extension_in_value")
            seller_strength += 1
        if close < curr.poc and tpo_below > tpo_above:
            seller_strength += 1

    activity = ActivityType.ROTATIONAL
    control = Control.NEUTRAL
    
    if buyer_strength >= 2 and seller_strength >= 2:
        control = Control.CONFLICT
        activity = ActivityType.ROTATIONAL
        signals.append("buyer_seller_conflict")
    elif buyer_strength > seller_strength:
        control = Control.BUYERS
        if curr.val >= p_vah:
            activity = ActivityType.INITIATING_BUYING
        elif curr.vah <= p_val:
            activity = ActivityType.RESPONSIVE_BUYING
        else:
            if (ext_up and not ext_down) and (curr.vah > p_vah):
                activity = ActivityType.INITIATING_BUYING
            else:
                activity = ActivityType.ROTATIONAL
    elif seller_strength > buyer_strength:
        control = Control.SELLERS
        if curr.vah <= p_val:
            activity = ActivityType.INITIATING_SELLING
        elif curr.val >= p_vah:
            activity = ActivityType.RESPONSIVE_SELLING
        else:
            if (ext_down and not ext_up) and (curr.val < p_val):
                activity = ActivityType.INITIATING_SELLING
            else:
                activity = ActivityType.ROTATIONAL
            
    return activity, control, signals

def analyze_context(current: TPOResult, previous: Optional[TPOResult]) -> MarketContext:
    """Analyze market context by comparing current session with previous."""
    if not previous:
        return MarketContext(
            va_relationship=VAContext.UNCHANGED,
            overlap_pct=0.0,
            va_expanding=False,
            trend_context="neutral",
            activity=ActivityType.UNCLEAR,
            control=Control.NEUTRAL,
            confidence=0.5
        )
    
    va_rel, overlap = _classify_va_relationship(current, previous)
    
    if va_rel in (VAContext.HIGHER, VAContext.OVERLAP_HIGHER):
        trend = "up"
    elif va_rel in (VAContext.LOWER, VAContext.OVERLAP_LOWER):
        trend = "down"
    else:
        trend = "neutral"
        
    activity, control, signals = _analyze_activity(current, previous, va_rel)
    va_expanding = current.value_area_range > previous.value_area_range
    
    return MarketContext(
        va_relationship=va_rel,
        overlap_pct=overlap,
        va_expanding=va_expanding,
        trend_context=trend,
        activity=activity,
        control=control,
        signals=signals,
        confidence=1.0
    )
