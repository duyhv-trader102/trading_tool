"""
Order Block analysis functions.
Higher-level analysis that builds on core OB detection.
"""
from typing import List, Dict, Any
from core.ob import find_all_ob
from analytic.ob_analysis.ob_mitigation import check_mitigation_type


def attach_mitigation_status(ob_list: List[Dict], ohlc_data: List) -> List[Dict]:
    """
    Append mitigation information to each OB in the list.
    
    Args:
        ob_list: List of OB dicts with 'time', 'high', 'low', etc.
        ohlc_data: OHLC data (list of dicts or tuples)
    
    Returns:
        Same ob_list with added 'mitigation_status', 'mitigation_type', 'mitigation_time'
    """
    for ob in ob_list:
        ob_time = ob['time']
        ob_idx = next((i for i, c in enumerate(ohlc_data) 
                      if (c['time'] if isinstance(c, dict) else c[0]) == ob_time), None)
        if ob_idx is not None and ob_idx < len(ohlc_data) - 1:
            mit_res = check_mitigation_type(ob, ohlc_data, ob_idx + 1)
            ob['mitigation_status'] = mit_res['status']
            ob['mitigation_type'] = mit_res['type']
            ob['mitigation_time'] = mit_res['time']
    return ob_list


def find_obs_with_mitigation(ohlc_data, tolerance=0.05, swing_window=3, trend_window=3,
                              filter_breakouts=True, max_consolidation=5) -> List[Dict]:
    """
    Find all OBs and attach mitigation status.
    
    Convenience function that combines core OB detection with mitigation analysis.
    """
    obs = find_all_ob(
        ohlc_data, 
        tolerance=tolerance, 
        swing_window=swing_window, 
        trend_window=trend_window,
        filter_breakouts=filter_breakouts,
        max_consolidation=max_consolidation
    )
    return attach_mitigation_status(obs, ohlc_data)
