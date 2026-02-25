"""
EA Configuration - Macro Balance Scalper V2
============================================
V2 Improvements (Scalping Mode):
1. ADX Filter (22-40) - Need momentum for scalping
2. Smart Trailing Stop (1x ATR, activate after 0.5% profit)
3. Time-based Exit (4 HOURS MAX - scalping strategy)
4. Tight Stop Loss: 1.5x ATR or MBA edge + 0.5% buffer

Note: For balance scalper, we want LOW ADX (ranging) not HIGH ADX (trending)
"""
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════
# TRADING SYMBOLS & PARAMETERS
# ═══════════════════════════════════════════════════════════════════════
TRADING_CONFIG = {
    "XAUUSDm": {"lot": 0.01, "has_weekend": False},
    "EURUSDm": {"lot": 0.1, "has_weekend": False},
    "GBPUSDm": {"lot": 0.1, "has_weekend": False},
    "USDJPYm": {"lot": 0.1, "has_weekend": False},
    "BTCUSDm": {"lot": 0.01, "has_weekend": True},
    "GBPJPYm": {"lot": 0.1, "has_weekend": False},
}

DEFAULT_MAGIC = 123458  # Unique magic number for V2

# ═══════════════════════════════════════════════════════════════════════
# ACCOUNT SETTINGS (2% Risk)
# ═══════════════════════════════════════════════════════════════════════
ACCOUNT_BALANCE = 535.58  # USD - Update this regularly
RISK_PERCENT = 0.02       # 2% risk per trade
MAX_RISK_USD = ACCOUNT_BALANCE * RISK_PERCENT  # $10.71

# ═══════════════════════════════════════════════════════════════════════
# V2 RISK MANAGEMENT SETTINGS
# ═══════════════════════════════════════════════════════════════════════

# ATR/ADX Calculation
ATR_PERIOD = 14
ADX_PERIOD = 14

# ADX Filter - SCALPING MODE (need strong momentum)
MAX_ADX_FOR_ENTRY = 40   # Skip if ADX > 40 (too trendy)
MIN_ADX_FOR_ENTRY = 25   # Skip if ADX < 25 (optimal for Gold scalp)

# Initial Stop Loss - SCALPING (tight stops)
INITIAL_STOP_ATR_MULT = 1.5  # Scalp: 1.5x ATR

# Smart Trailing Stop - SCALPING
TRAILING_STOP_ATR_MULT = 1.0      # Scalp: tight trail at 1x ATR
PROFIT_THRESHOLD_TO_TRAIL = 0.005  # Activate trailing after 0.5% profit

# ═══════════════════════════════════════════════════════════════════════
# STRATEGY PARAMETERS (Balance-specific)
# ═══════════════════════════════════════════════════════════════════════

# MBA Edge Detection - SCALPING (tighter)
EDGE_THRESHOLD_PCT = 0.003  # 0.3% from MBA edge (tighter for scalp)

# Stop Loss Buffer - SCALPING
SL_BUFFER_PCT = 0.005  # 0.5% beyond MBA edge for SL (tighter)

# Take Profit Target - SCALPING
TP_FALLBACK_PCT = 0.3  # 30% of MBA range as fallback (smaller target)

# Time-based Exit (scalping - max 1 day)
MAX_HOLD_HOURS = 72  # Scalping: tối đa 3 ngày cho price revert về mean
MIN_PROFIT_PCT_FOR_HOLD = 0.3  # Min profit % to avoid early exit

# Re-entry cooldown after hitting SL
COOLDOWN_DAYS = 3

# ═══════════════════════════════════════════════════════════════════════
# FILTERS
# ═══════════════════════════════════════════════════════════════════════

# Weekly compression filter
REQUIRE_WEEKLY_COMPRESSION = True

# Minimum MBA age (sessions)
MIN_MBA_AGE_SESSIONS = 3

# ═══════════════════════════════════════════════════════════════════════
# STATE PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════
STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "balance_scalper_state_v2.json"
