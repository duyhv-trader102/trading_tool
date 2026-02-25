"""
EA Configuration - Macro Balance Scalper

Strategy: Trade bounces within Monthly MBA range, targeting Daily MBA (nested balance).
Rule: Imbalance → Balance → Imbalance (I→B→I fractal)
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

DEFAULT_MAGIC = 123457  # Unique magic number for this EA

# ═══════════════════════════════════════════════════════════════════════
# ACCOUNT SETTINGS (2% Risk)
# ═══════════════════════════════════════════════════════════════════════
ACCOUNT_BALANCE = 535.58  # USD - Update this regularly
RISK_PERCENT = 0.02       # 2% risk per trade
MAX_RISK_USD = ACCOUNT_BALANCE * RISK_PERCENT  # $10.71

# ═══════════════════════════════════════════════════════════════════════
# STRATEGY PARAMETERS
# ═══════════════════════════════════════════════════════════════════════

# MBA Edge Detection - Price must be within edge_threshold of MBA boundary
# to qualify as "at edge" for entry
EDGE_THRESHOLD_PCT = 0.005  # 0.5% from MBA edge

# Stop Loss Buffer - Additional buffer outside MBA edge for stop loss
SL_BUFFER_PCT = 0.01  # 1.0% buffer beyond MBA edge

# Take Profit Target
# Primary: Nearest Daily MBA within 1M MBA range
# Fallback: 50% of MBA range if no Daily MBA found
TP_FALLBACK_PCT = 0.5  # 50% of 1M MBA range as fallback

# Maximum hold time (days) - Exit if target not reached
MAX_HOLD_DAYS = 21  # 3 weeks max for balance trades

# Re-entry cooldown after hitting SL (days)
COOLDOWN_DAYS = 3

# ═══════════════════════════════════════════════════════════════════════
# FILTERS
# ═══════════════════════════════════════════════════════════════════════

# Weekly compression filter - Wait for 1W to show compression before entry
REQUIRE_WEEKLY_COMPRESSION = True

# Minimum MBA age (sessions) - MBA should be established
MIN_MBA_AGE_SESSIONS = 3

# ═══════════════════════════════════════════════════════════════════════
# STATE PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════
STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "balance_scalper_state.json"
