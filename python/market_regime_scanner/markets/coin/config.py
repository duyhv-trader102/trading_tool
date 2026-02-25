import os

# Coin Symbols (MT5 names)
# Note: Only BTCUSDm has historical parquet data.
# Others are live-scannable via MT5 but require manual data download first.
COIN_SYMBOLS = [
    # Tier 1 (highest volume on Exness)
    "BTCUSDm",  "ETHUSDm",   "SOLUSDm",  "XRPUSDm",  "BNBUSDm",
    # Tier 2
    "ADAUSDm",  "AVAXUSDm",  "DOGEUSDm", "LINKUSDm", "DOTUSDm",
    # Tier 3
    "LTCUSDm",  "MATICUSDm", "ATOMUSDm", "UNIUSDm",  "BCHUSDm",
]

# Output Directories (created on demand, not at import time)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Scan Settings
# For Crypto, we use higher bars for long history if available
LOOKBACK_BARS = 2000 
