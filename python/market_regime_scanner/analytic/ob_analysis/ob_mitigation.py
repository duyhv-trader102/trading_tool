"""
OB Mitigation type classification.
"""
from core.candle import get_ohlc_full


def check_mitigation_type(ob, ohlc_data, start_idx):
    """
    Analyzes candles following an OB to determine if and how it was mitigated.
    ob: dict with 'high', 'low', 'open', 'close', 'time'
    ohlc_data: list of dicts or tuples
    start_idx: index of the candle immediately FOLLOWING the OB candle
    
    Returns: {
        'status': 'Mitigated' | 'Unmitigated (Acceptance)',
        'type': 1 | 2 | 3 | None,
        'time': timestamp | None
    }
    """
    is_bullish_ob = ob['close'] < ob['open']  # Bullish OB is usually the last down candle
    range_high = ob['high']
    range_low = ob['low']
    midpoint = (range_high + range_low) / 2
    
    # Type 2 check: Next candle only
    if start_idx < len(ohlc_data):
        next_c = ohlc_data[start_idx]
        n_time, _, n_high, n_low, n_close = get_ohlc_full(next_c)
        
        # Bullish OB manipulation: sweeps below range_low and retracts
        if is_bullish_ob:
            if n_low < range_low and n_close > range_low:
                return {'status': 'Mitigated', 'type': 2, 'time': n_time}
        else:  # Bearish OB manipulation: sweeps above range_high and retracts
            if n_high > range_high and n_close < range_high:
                return {'status': 'Mitigated', 'type': 2, 'time': n_time}

    # Iterate further for Type 1 and Type 3
    has_confirmed_breakout = False
    for i in range(start_idx, len(ohlc_data)):
        c_time, _, c_high, c_low, c_close = get_ohlc_full(ohlc_data[i])
        
        # If breakout already confirmed, only check for Type 3 (boundary retest)
        if has_confirmed_breakout:
            if is_bullish_ob:
                if c_low <= range_high:
                    return {'status': 'Mitigated', 'type': 3, 'time': c_time}
            else:
                if c_high >= range_low:
                    return {'status': 'Mitigated', 'type': 3, 'time': c_time}
            continue
        
        # Type 1: 50% Retest (Midpoint) - only check if NO breakout yet
        if is_bullish_ob:
            if c_low <= midpoint and c_high >= range_low:
                return {'status': 'Mitigated', 'type': 1, 'time': c_time}
        else:
            if c_high >= midpoint and c_low <= range_high:
                return {'status': 'Mitigated', 'type': 1, 'time': c_time}

        # Check for confirmed breakout (Type 3 precondition)
        if is_bullish_ob:
            if c_close > range_high:
                has_confirmed_breakout = True
        else:
            if c_close < range_low:
                has_confirmed_breakout = True
                    
    return {'status': 'Unmitigated (Acceptance)', 'type': None, 'time': None}
