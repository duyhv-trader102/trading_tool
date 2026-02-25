
import pandas as pd
import numpy as np
from typing import Dict, Tuple

def calculate_mechanical_metrics(df: pd.DataFrame, window: int = 100) -> pd.DataFrame:
    """
    Calculates institutional mechanical markers for Balance and Expansion.
    Requires Daily (D1) or H4 OHLC data.
    """
    df = df.copy()
    
    # 1. BB Width Percentile (Compression)
    ma = df['close'].rolling(20).mean()
    std = df['close'].rolling(20).std()
    df['bbw'] = (std * 4) / ma
    
    def get_percentile(x):
        if len(x) < 2: return 0.5
        v = x[-1]
        return (v - x.min()) / (x.max() - x.min()) if x.max() != x.min() else 0.5

    df['bbw_p'] = df['bbw'].rolling(window).apply(get_percentile, raw=True)
    
    # 2. Average True Range (ATR)
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    # 3. Range Relative to ATR (Relative Volatility)
    df['range_pct'] = (df['high'] - df['low']) / df['close']
    df['range_rel_atr'] = (df['high'] - df['low']) / df['atr']
    
    # 4. ADX (Trend Strength) - Simplified
    plus_dm = (df['high'] - df['high'].shift()).apply(lambda x: x if x > 0 else 0)
    minus_dm = (df['low'].shift() - df['low']).apply(lambda x: x if x > 0 else 0)
    tr14 = tr.rolling(14).sum()
    plus_di = 100 * (plus_dm.rolling(14).sum() / tr14)
    minus_di = 100 * (minus_dm.rolling(14).sum() / tr14)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    df['adx'] = dx.rolling(14).mean()
    
    return df

def get_session_mechanical_state(df_row: pd.Series) -> Dict:
    """
    Classifies a single session based on mechanical metrics.
    """
    is_compressed = df_row['bbw_p'] < 0.30  # Bottom 30% of volatility history
    is_expanding = df_row['range_rel_atr'] > 1.3 # 30% larger than average
    
    return {
        "is_compressed": bool(is_compressed),
        "is_expanding": bool(is_expanding),
        "bbw_p": float(df_row['bbw_p']),
        "adx": float(df_row['adx']),
        "volatility_ratio": float(df_row['range_rel_atr'])
    }
