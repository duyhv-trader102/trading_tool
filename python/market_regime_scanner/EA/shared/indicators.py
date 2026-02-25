"""
Technical Indicators
====================
Reusable technical indicators for EA strategies.
"""

from typing import List
import numpy as np


def calculate_atr(
    highs: List[float], 
    lows: List[float], 
    closes: List[float], 
    period: int = 14
) -> float:
    """
    Calculate Average True Range (ATR).
    
    ATR measures market volatility by decomposing the entire range 
    of an asset price for that period.
    
    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of close prices
        period: ATR period (default 14)
    
    Returns:
        ATR value, or 0.0 if insufficient data
    """
    if len(highs) < period + 1:
        return 0.0
    
    true_ranges = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        true_ranges.append(tr)
    
    if len(true_ranges) >= period:
        return sum(true_ranges[-period:]) / period
    return 0.0


def calculate_adx(
    highs: List[float], 
    lows: List[float], 
    closes: List[float], 
    period: int = 14
) -> float:
    """
    Calculate Average Directional Index (ADX).
    
    ADX measures trend strength without regard to trend direction.
    - < 20: Weak/No trend
    - 20-25: Trend developing
    - 25-50: Strong trend
    - > 50: Very strong trend
    
    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of close prices
        period: ADX period (default 14)
    
    Returns:
        ADX value (0-100), or 0.0 if insufficient data
    """
    if len(highs) < period * 2:
        return 0.0
    
    # Calculate +DM and -DM
    plus_dm = []
    minus_dm = []
    tr_list = []
    
    for i in range(1, len(highs)):
        high_diff = highs[i] - highs[i-1]
        low_diff = lows[i-1] - lows[i]
        
        plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
        minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
        
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
    
    if len(tr_list) < period:
        return 0.0
    
    # Wilder's smoothing
    def smooth(data: List[float], period: int) -> List[float]:
        if len(data) < period:
            return []
        smoothed = [sum(data[:period])]
        for i in range(period, len(data)):
            smoothed.append(smoothed[-1] - smoothed[-1]/period + data[i])
        return smoothed
    
    smooth_tr = smooth(tr_list, period)
    smooth_plus_dm = smooth(plus_dm, period)
    smooth_minus_dm = smooth(minus_dm, period)
    
    if not smooth_tr or smooth_tr[-1] == 0:
        return 0.0
    
    # Calculate +DI and -DI
    plus_di = 100 * smooth_plus_dm[-1] / smooth_tr[-1] if smooth_tr[-1] > 0 else 0
    minus_di = 100 * smooth_minus_dm[-1] / smooth_tr[-1] if smooth_tr[-1] > 0 else 0
    
    # Calculate DX
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0.0
    
    dx = 100 * abs(plus_di - minus_di) / di_sum
    
    # For simplicity, return DX as ADX approximation
    # Full ADX requires smoothing DX over period
    return dx


def calculate_rsi(closes: List[float], period: int = 14) -> float:
    """
    Calculate Relative Strength Index (RSI).
    
    RSI measures momentum on a scale of 0-100.
    - < 30: Oversold
    - 30-70: Neutral
    - > 70: Overbought
    
    Args:
        closes: List of close prices
        period: RSI period (default 14)
    
    Returns:
        RSI value (0-100), or 50.0 if insufficient data
    """
    if len(closes) < period + 1:
        return 50.0
    
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_ema(values: List[float], period: int) -> List[float]:
    """
    Calculate Exponential Moving Average (EMA).
    
    Args:
        values: List of prices
        period: EMA period
    
    Returns:
        List of EMA values
    """
    if len(values) < period:
        return []
    
    multiplier = 2 / (period + 1)
    ema = [sum(values[:period]) / period]  # SMA for first value
    
    for i in range(period, len(values)):
        ema.append((values[i] - ema[-1]) * multiplier + ema[-1])
    
    return ema


def calculate_sma(values: List[float], period: int) -> List[float]:
    """
    Calculate Simple Moving Average (SMA).
    
    Args:
        values: List of prices
        period: SMA period
    
    Returns:
        List of SMA values
    """
    if len(values) < period:
        return []
    
    sma = []
    for i in range(period - 1, len(values)):
        sma.append(sum(values[i - period + 1:i + 1]) / period)
    
    return sma


def calculate_bollinger_bands(
    closes: List[float], 
    period: int = 20, 
    std_dev: float = 2.0
) -> tuple:
    """
    Calculate Bollinger Bands.
    
    Args:
        closes: List of close prices
        period: BB period (default 20)
        std_dev: Standard deviation multiplier (default 2.0)
    
    Returns:
        Tuple of (upper_band, middle_band, lower_band) as last values
    """
    if len(closes) < period:
        return (0.0, 0.0, 0.0)
    
    recent = closes[-period:]
    middle = sum(recent) / period
    std = np.std(recent)
    
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    
    return (upper, middle, lower)
