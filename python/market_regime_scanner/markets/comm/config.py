import os

# Commodity Symbols (Exness MT5 naming — suffix 'm')
# Precious Metals
METALS = [
    "XAUUSDm",   # Gold
    "XAGUSDm",   # Silver
    "XPTUSDm",   # Platinum
    "XPDUSDm",   # Palladium
]

# Energy
ENERGY = [
    "USOILm",    # WTI Crude Oil
    "UKOILm",    # Brent Crude Oil
]

COMMODITY_SYMBOLS = METALS + ENERGY

# Output Directories (created on demand, not at import time)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Scan Settings
LOOKBACK_BARS = 2000
