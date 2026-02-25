"""
Macro Trend Catcher V2 — Configuration
========================================

Top-down alignment strategy using MBA readiness signals from
``analytic.tpo_mba.tracker.build_mba_context()``.

V2 Philosophy
-------------
- Wait for confluence: M → W → D alignment.
- 1M session ready ⇒ direction (anchor).
- 1W session ready + same direction as 1M.
- 1D session ready + same direction as 1W  ⇒ ENTER.
- Fixed stop-loss based on ATR (no trailing).
- Exit on monthly direction flip or stop-loss hit.

Timeframe Mapping
-----------------
Each session is built from bars of a **lower** timeframe to reduce noise::

    Session     Bar TF     Bars/Session    Purpose
    ─────────   ──────     ────────────    ───────
    Monthly     W1         ≈4-5            Macro trend anchor
    Weekly      D1         ≈5              Intermediate trend
    Daily       H4         ≈6              Entry trigger

Data Sources
------------
- **MT5**: ``infra.data.mt5_provider.MT5Provider`` → D1, W1, H4 bars
- **Binance**: ``data/binance/{SYMBOL}_USDT_H4.parquet`` → resampled via
  ``core.resampler.resample_data()`` to D1 and W1

Entry Filters
-------------
1. Price-direction consistency (price inside MBA range on all TFs)
2. MBA continuity check (configurable)
3. Cooldown after stop-loss (same direction blocked for N days)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict


@dataclass
class TrendCatcherV2Config:
    """Configuration for Macro Trend Catcher V2 (Alignment)."""

    # ─── Stop Loss ────────────────────────────────────────────
    initial_stop_atr_mult: float = 3.0      # Initial SL at 3x Daily ATR
    use_trailing_stop: bool = False          # V2: no trailing – ride full trend

    # ─── Technical Periods ────────────────────────────────────
    atr_period: int = 14

    # ─── Position Sizing ──────────────────────────────────────
    risk_per_trade_pct: float = 2.0         # Risk 2% of equity per trade

    # ─── Constraints ──────────────────────────────────────────
    max_positions: int = 10                 # Max concurrent positions across all symbols
    cooldown_days: int = 20                 # Cooldown after stop loss hit (bars/days)

    # ─── MBA age (sessions since mother) ──────────────────────
    min_mba_continuity: int = 0             # 0 = accept any MBA; raise to filter immature MBAs


# ═══════════════════════════════════════════════════════════════
# Per-asset-class configs
# ═══════════════════════════════════════════════════════════════

FOREX_V2 = TrendCatcherV2Config(initial_stop_atr_mult=3.0)
US_STOCKS_V2 = TrendCatcherV2Config(initial_stop_atr_mult=3.5)
COMMODITIES_V2 = TrendCatcherV2Config(initial_stop_atr_mult=3.0)
CRYPTO_V2 = TrendCatcherV2Config(initial_stop_atr_mult=2.5)

# Binance spot — used by backtest_binance.py and market_filter.py
BINANCE_SPOT_V2 = TrendCatcherV2Config(
    initial_stop_atr_mult=3.0,
    cooldown_days=20,
)

# Symbols to skip in Binance batch (stablecoins, wrapped, dead projects)
BINANCE_SKIP_SYMBOLS = {
    "FDUSD", "TUSD", "USDC", "USDE", "USDP", "USTC", "RLUSD", "USD1",
    "XUSD", "BFUSD", "WBTC", "WBETH", "BNSOL", "PAXG", "FRAX", "EUR",
    "AEUR", "EURI", "LUNC", "LUNA", "FTT",
}


# ═══════════════════════════════════════════════════════════════
# Asset Universe
# ═══════════════════════════════════════════════════════════════

ASSET_CONFIG: Dict[str, dict] = {
    "FOREX_MAJORS": {
        "symbols": [
            "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm",
            "USDCADm", "USDCHFm", "NZDUSDm",
        ],
        "config": FOREX_V2,
    },
    "FOREX_CROSSES": {
        "symbols": [
            # EUR crosses
            "EURGBPm", "EURJPYm", "EURAUDm", "EURNZDm", "EURCADm", "EURCHFm",
            # GBP crosses
            "GBPJPYm", "GBPAUDm", "GBPNZDm", "GBPCADm", "GBPCHFm",
            # JPY crosses
            "AUDJPYm", "NZDJPYm", "CADJPYm", "CHFJPYm",
            # AUD/NZD/CAD/CHF
            "AUDCADm", "AUDNZDm", "AUDCHFm", "NZDCADm", "NZDCHFm",
        ],
        "config": FOREX_V2,
    },
    "COMMODITIES": {
        "symbols": [
            "XAUUSDm", "XAGUSDm", "XPTUSDm", "XPDUSDm",  # metals
            "USOILm", "UKOILm",                            # energy
        ],
        "config": COMMODITIES_V2,
    },
    "US_INDICES": {
        "symbols": [
            "US500m", "US30m", "USTECm",
            "DE30m", "JP225m", "HK50m",
        ],
        "config": US_STOCKS_V2,
    },
    "US_TECH_STOCKS": {
        "symbols": [
            "NVDAm", "AAPLm", "MSFTm", "GOOGLm",
            "AMZNm", "TSLAm", "METAm", "AMDm",
        ],
        "config": US_STOCKS_V2,
    },
    "US_OTHER_STOCKS": {
        "symbols": [
            "NFLXm", "ADBEm", "INTCm",
            "PYPLm", "Vm",
        ],
        "config": US_STOCKS_V2,
    },
    "CRYPTO": {
        "symbols": [
            "BTCUSDm", "ETHUSDm", "SOLUSDm",
            "XRPUSDm", "BNBUSDm", "LTCUSDm",
        ],
        "config": CRYPTO_V2,
    },
}


# ═══════════════════════════════════════════════════════════════
# State / Logging Paths
# ═══════════════════════════════════════════════════════════════

STATE_DIR = Path(__file__).parent / "state"
STATE_DIR.mkdir(exist_ok=True)
STATE_FILE = STATE_DIR / "positions_v2.json"

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

REPORT_DIR = Path(__file__).parent / "reports"
REPORT_DIR.mkdir(exist_ok=True)

MAGIC_NUMBER = 20260202  # V2 magic number
