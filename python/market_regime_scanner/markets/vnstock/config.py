import os
from pathlib import Path

# VNStock API Key
VNSTOCK_API_KEY = "vnstock_7218d4ab8d176bb09eb720cec4df5958"

# Resolve paths relative to this file — no hardcoded machine paths
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Data Directories (created on demand, not at import time)
DATA_DIR = str(_PROJECT_ROOT / "data" / "vnstock")
OUTPUT_DIR = str(Path(__file__).resolve().parent / "output")

# Scanner Settings
DEFAULT_START_DATE = "2000-01-01"

VN30_SYMBOLS = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"
]

# Official VN100 basket (100 symbols, fetched from VCI API 2026-02-23)
VN100_SYMBOLS = [
    "ACB", "ANV", "BCM", "BID", "BMP", "BSI", "BSR", "BVH", "BWE", "CII",
    "CMG", "CTD", "CTG", "CTR", "CTS", "DBC", "DCM", "DGC", "DGW", "DIG",
    "DPM", "DSE", "DXG", "DXS", "EIB", "EVF", "FPT", "FRT", "FTS", "GAS",
    "GEE", "GEX", "GMD", "GVR", "HAG", "HCM", "HDB", "HDC", "HDG", "HHV",
    "HPG", "HSG", "HT1", "IMP", "KBC", "KDC", "KDH", "KOS", "LPB", "MBB",
    "MSB", "MSN", "MWG", "NAB", "NKG", "NLG", "NT2", "NVL", "OCB", "PAN",
    "PC1", "PDR", "PHR", "PLX", "PNJ", "POW", "PVD", "PVT", "REE", "SAB",
    "SBT", "SCS", "SHB", "SIP", "SJS", "SSB", "SSI", "STB", "SZC", "TCB",
    "TCH", "TPB", "VCB", "VCG", "VCI", "VGC", "VHC", "VHM", "VIB", "VIC",
    "VIX", "VJC", "VND", "VNM", "VPB", "VPI", "VPL", "VRE", "VSC", "VTP",
]
