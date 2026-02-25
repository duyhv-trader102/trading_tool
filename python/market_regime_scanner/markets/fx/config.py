import os

# FX Symbols (Exness MT5 naming — suffix 'm')
# 7 Majors
FX_MAJORS = [
    "EURUSDm", "GBPUSDm", "USDJPYm", "USDCHFm", "AUDUSDm", "USDCADm", "NZDUSDm",
]

# Major Crosses
FX_CROSSES = [
    # EUR crosses
    "EURGBPm", "EURJPYm", "EURAUDm", "EURNZDm", "EURCADm", "EURCHFm",
    # GBP crosses
    "GBPJPYm", "GBPAUDm", "GBPNZDm", "GBPCADm", "GBPCHFm",
    # JPY crosses
    "AUDJPYm", "NZDJPYm", "CADJPYm", "CHFJPYm",
    # AUD/NZD/CAD crosses
    "AUDCADm", "AUDNZDm", "AUDCHFm", "NZDCADm", "NZDCHFm",
]

FX_SYMBOLS = FX_MAJORS + FX_CROSSES

# Output Directories (created on demand, not at import time)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Scan Settings
LOOKBACK_BARS = 2000 
