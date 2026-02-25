"""
Top-Down Observer — Configuration.

All constants, symbol definitions, timeframe mappings, and paths
used by the top-down analysis pipeline live here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from markets.vnstock.config import VN30_SYMBOLS, VN100_SYMBOLS


# =============================================================================
# Paths
# =============================================================================

_ROOT = Path(__file__).resolve().parent.parent.parent   # market_regime_scanner/
OUTPUT_DIR: Path = _ROOT / "scripts" / "output"
DATA_DIR: Path = _ROOT / "data" / "mt5"
TICK_SIZE_CACHE: Path = DATA_DIR / "tick_sizes.json"


# =============================================================================
# Symbols
# =============================================================================

SYMBOLS: List[Dict] = [
    # ── FX Majors ─────────────────────────────────────────────
    {"symbol": "EURUSDm",  "has_weekend": False},
    {"symbol": "GBPUSDm",  "has_weekend": False},
    {"symbol": "USDJPYm",  "has_weekend": False},
    {"symbol": "USDCHFm",  "has_weekend": False},
    {"symbol": "AUDUSDm",  "has_weekend": False},
    {"symbol": "USDCADm",  "has_weekend": False},
    {"symbol": "NZDUSDm",  "has_weekend": False},
    # ── FX Crosses ────────────────────────────────────────────
    {"symbol": "GBPJPYm",  "has_weekend": False},
    {"symbol": "EURJPYm",  "has_weekend": False},
    {"symbol": "EURGBPm",  "has_weekend": False},
    {"symbol": "EURAUDm",  "has_weekend": False},
    {"symbol": "AUDJPYm",  "has_weekend": False},
    {"symbol": "CADJPYm",  "has_weekend": False},
    {"symbol": "CHFJPYm",  "has_weekend": False},
    {"symbol": "GBPAUDm",  "has_weekend": False},
    {"symbol": "GBPCADm",  "has_weekend": False},
    {"symbol": "AUDCADm",  "has_weekend": False},
    # ── Commodities ───────────────────────────────────────────
    {"symbol": "XAUUSDm",  "has_weekend": False},
    {"symbol": "XAGUSDm",  "has_weekend": False},
    {"symbol": "XPTUSDm",  "has_weekend": False},
    {"symbol": "XPDUSDm",  "has_weekend": False},
    {"symbol": "USOILm",   "has_weekend": False},
    {"symbol": "UKOILm",   "has_weekend": False},
    # ── US Indices ────────────────────────────────────────────
    {"symbol": "US500m",   "has_weekend": False},
    {"symbol": "US30m",    "has_weekend": False},
    {"symbol": "USTECm",   "has_weekend": False},
    {"symbol": "DE30m",    "has_weekend": False},
    {"symbol": "HK50m",    "has_weekend": False},
    {"symbol": "JP225m",   "has_weekend": False},
    # ── US Stocks ─────────────────────────────────────────────
    {"symbol": "NVDAm",    "has_weekend": False},
    {"symbol": "AAPLm",    "has_weekend": False},
    {"symbol": "MSFTm",    "has_weekend": False},
    {"symbol": "GOOGLm",   "has_weekend": False},
    {"symbol": "AMZNm",    "has_weekend": False},
    {"symbol": "TSLAm",    "has_weekend": False},
    {"symbol": "METAm",    "has_weekend": False},
    {"symbol": "AMDm",     "has_weekend": False},
    {"symbol": "INTCm",    "has_weekend": False},
    {"symbol": "NFLXm",    "has_weekend": False},
    {"symbol": "ADBEm",    "has_weekend": False},
    {"symbol": "Vm",       "has_weekend": False},
    # ── Crypto ────────────────────────────────────────────────
    {"symbol": "BTCUSDm",  "has_weekend": True},
    {"symbol": "ETHUSDm",  "has_weekend": True},
    {"symbol": "SOLUSDm",  "has_weekend": True},
    {"symbol": "XRPUSDm",  "has_weekend": True},
    {"symbol": "BNBUSDm",  "has_weekend": True},
    {"symbol": "ADAUSDm",  "has_weekend": True},
]


# =============================================================================
# Timeframes
# =============================================================================

# Full set: M + W + D (for trading symbols)
# bars=None means load all available parquet data
TIMEFRAMES: Dict[str, Dict] = {
    # Monthly: native W1 bars (canonical broker bars)
    "Monthly": {"data_tf": "W1", "session_type": "M", "bars": None, "target_rows": 25},
    # Weekly: native D1 bars (canonical broker bars)
    "Weekly":  {"data_tf": "D1", "session_type": "W", "bars": None, "target_rows": 25},
    # Daily: H4 bars
    "Daily":   {"data_tf": "H4", "session_type": "D", "bars": None, "target_rows": 20},
}

# Macro set: M + W only (for broad regime scanning)
TIMEFRAMES_MACRO: Dict[str, Dict] = {
    "Monthly": TIMEFRAMES["Monthly"],
    "Weekly":  TIMEFRAMES["Weekly"],
}

# VNStock set: M + W + D using H1 bars for Daily sessions.
# VN market opens ~5 hours/day (09-11:30, 13-14:45) → 5 H1 bars/day.
# This is analogous to H4 bars for 24h markets (6 bars/day).
TIMEFRAMES_VN: Dict[str, Dict] = {
    "Monthly": TIMEFRAMES["Monthly"],
    "Weekly":  TIMEFRAMES["Weekly"],
    "Daily":   {"data_tf": "H1", "session_type": "D", "bars": None, "target_rows": 20},
}

# Symbols that get the full M+W+D chart (the rest get macro M+W only)
FULL_SYMBOLS: List[str] = ["XAUUSDm", "GBPJPYm", "EURUSDm", "BTCUSDm", "USDJPYm", "GBPUSDm"]


# Number of closed sessions to keep per timeframe (sliding window)
KEEP_SESSIONS: Dict[str, int] = {"Monthly": 12, "Weekly": 15, "Daily": 15}


# Analysis pass uses finer block size for accurate TPO balance/extremes.
ANALYSIS_TARGET_ROWS: int = 50


# =============================================================================
# Per-symbol overrides
# =============================================================================

# Minimum block sizes.  Without this, very small ranges can produce
# a block size of ~0 which breaks the TPO profile.
MIN_BLOCKS: Dict[str, Dict[str, float]] = {
    "XAUUSDm": {"Daily": 5},
    "BTCUSDm": {"Daily": 50},
    "EURUSDm": {"Monthly": 0.0025, "Weekly": 0.001, "Daily": 0.0005},
    "USDJPYm": {"Monthly": 0.25, "Weekly": 0.1, "Daily": 0.05},
    "GBPJPYm": {"Monthly": 0.5, "Weekly": 0.25, "Daily": 0.1},
    "GBPUSDm": {"Monthly": 0.0025, "Weekly": 0.001, "Daily": 0.0005},
}

# Fallback tick sizes for known symbols (used when MT5 is not connected)
TICK_SIZE_DEFAULTS: Dict[str, float] = {
    "XAUUSDm": 0.01,
    "EURUSDm": 0.00001,
    "USDJPYm": 0.001,
    "BTCUSDm": 0.01,
    "GBPJPYm": 0.001,
    "GBPUSDm": 0.00001,
    # Binance pairs (approximate tick sizes)
    "BTC/USDT":  0.01,
    "ETH/USDT":  0.01,
    "SOL/USDT":  0.01,
    "BNB/USDT":  0.01,
    "XRP/USDT":  0.0001,
    "ADA/USDT":  0.0001,
    "AVAX/USDT": 0.01,
    "DOGE/USDT": 0.00001,
    "DOT/USDT":  0.001,
    "LINK/USDT": 0.001,
    "UNI/USDT":  0.001,
    "ATOM/USDT": 0.001,
    "LTC/USDT":  0.01,
    "BCH/USDT":  0.01,
    "NEAR/USDT": 0.001,
    "INJ/USDT":  0.001,
    "SUI/USDT":  0.0001,
    "TIA/USDT":  0.001,
    "ARB/USDT":  0.0001,
    "OP/USDT":   0.0001,
    # VN100 stocks (VND, tick = 10đ for prices < 50k, but 10 is safe default)
    **{s: 10 for s in VN100_SYMBOLS},
}


# =============================================================================
# Binance symbols for observer (liquid &  well-known pairs with ≥3y H4 data)
# =============================================================================

BINANCE_SYMBOLS_OBSERVER: List[Dict] = [
    # Tier-1 majors
    {"symbol": "BTC/USDT",  "has_weekend": True},
    {"symbol": "ETH/USDT",  "has_weekend": True},
    {"symbol": "BNB/USDT",  "has_weekend": True},
    {"symbol": "SOL/USDT",  "has_weekend": True},
    {"symbol": "XRP/USDT",  "has_weekend": True},
    # Tier-2 alts
    {"symbol": "ADA/USDT",  "has_weekend": True},
    {"symbol": "AVAX/USDT", "has_weekend": True},
    {"symbol": "DOGE/USDT", "has_weekend": True},
    {"symbol": "DOT/USDT",  "has_weekend": True},
    {"symbol": "LINK/USDT", "has_weekend": True},
    {"symbol": "ATOM/USDT", "has_weekend": True},
    {"symbol": "LTC/USDT",  "has_weekend": True},
    {"symbol": "BCH/USDT",  "has_weekend": True},
    {"symbol": "NEAR/USDT", "has_weekend": True},
    {"symbol": "INJ/USDT",  "has_weekend": True},
    {"symbol": "SUI/USDT",  "has_weekend": True},
    {"symbol": "ARB/USDT",  "has_weekend": True},
    {"symbol": "OP/USDT",   "has_weekend": True},
    {"symbol": "TIA/USDT",  "has_weekend": True},
    {"symbol": "UNI/USDT",  "has_weekend": True},
]


# =============================================================================
# VN30 / VN100 symbols for observer
# Derived from single source: markets.vnstock.config
# =============================================================================

VN30_SYMBOLS_OBSERVER:  List[Dict] = [{"symbol": s, "has_weekend": False} for s in VN30_SYMBOLS]
VN100_SYMBOLS_OBSERVER: List[Dict] = [{"symbol": s, "has_weekend": False} for s in VN100_SYMBOLS]


# =============================================================================
# Tick-size cache helpers
# =============================================================================

def load_tick_cache() -> Dict[str, float]:
    """Load tick-size cache from JSON file."""
    if TICK_SIZE_CACHE.exists():
        with open(TICK_SIZE_CACHE, "r") as f:
            return json.load(f)
    return {}


def save_tick_cache(cache: Dict[str, float]) -> None:
    """Persist tick-size cache to JSON file."""
    TICK_SIZE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(TICK_SIZE_CACHE, "w") as f:
        json.dump(cache, f, indent=2)
