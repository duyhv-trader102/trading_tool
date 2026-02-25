import os

# US Stock Symbols (MT5 names)
# Note: Exness uses #AAPL, #MSFT etc. suffixing can vary. 
# We'll use a standard list and let MT5Provider handle them.
# Indices (US + Global)
INDICES = [
    "US500m", "US30m", "USTECm",       # US
    "DE30m", "JP225m", "HK50m",        # Global
]

# Tech / Growth
TECH_STOCKS = [
    "NVDAm", "AAPLm", "MSFTm", "GOOGLm",
    "AMZNm", "TSLAm", "METAm", "AMDm",
    "NFLXm", "ADBEm", "INTCm",
]

# Other equities with MT5 data
OTHER_STOCKS = [
    "PYPLm", "Vm",
]

US_STOCK_SYMBOLS = INDICES + TECH_STOCKS + OTHER_STOCKS

# Output Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Scan Settings
LOOKBACK_BARS = 2000 
