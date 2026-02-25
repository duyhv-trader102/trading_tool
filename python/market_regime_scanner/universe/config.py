"""
universe.config — Universe Selection Configuration
===================================================

All tunable parameters for the 3-stage pipeline in one place.
"""

from dataclasses import dataclass, field
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────
UNIVERSE_DIR = Path(__file__).parent
CACHE_DIR = UNIVERSE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

BACKTEST_CACHE_FILE = CACHE_DIR / "backtest_results.json"
PRE_SCREEN_CACHE_FILE = CACHE_DIR / "pre_screen_results.json"
WATCHLIST_FILE = UNIVERSE_DIR / "watchlist.json"


# ── Pre-screen filters ────────────────────────────────────────
@dataclass
class PreScreenConfig:
    """Fast filters applied before the expensive backtest."""

    # Minimum average daily volume in USDT — ensures liquidity
    min_avg_volume_usdt: float = 1_000_000.0   # $1M/day

    # Minimum listing history (days of data in parquet)
    # ~500 D1 bars ≈ 1.5 years crypto (24/7) — enough for backtest with
    # compression gate while still including mid-lifecycle altcoins.
    min_history_days: int = 500

    # Spot price floor — reject dust / dead tokens
    min_price_usdt: float = 0.0001

    # Maximum universe size after pre-screen (safety cap)
    max_symbols: int = 200


# ── Backtest config ───────────────────────────────────────────
@dataclass
class BacktestConfig:
    """Parameters forwarded to the EA backtest engine."""

    # Use D1 bars resampled from H4 storage (fast)
    timeframe: str = "D1"

    # SL multiplier (ATR-based), same as EA default
    sl_atr_mult: float = 3.0
    atr_period: int = 14

    # Skip coin if position held longer than this (data error guard)
    max_hold_days: int = 500

    # Strategy gates
    require_compression: bool = True
    use_soft_sl: bool = True

    # Cooldown after SL hit (same as EA)
    cooldown_days: int = 20


# ── Scoring & tier config ─────────────────────────────────────
# Delegate to EA/shared/market_filter.FilterConfig — imported in screener.py
# We just expose the defaults here for CLI override convenience.
@dataclass
class ScoringConfig:
    """Thin wrapper around FilterConfig thresholds."""

    # Hard filters
    # With compression gate ON, strategy fires very rarely (0.5-0.8 trade/year).
    # Quality is enforced by min_profit_factor + min_total_return, not trade count.
    min_trades: int = 2
    min_data_years: float = 1.5
    min_profit_factor: float = 1.3
    max_drawdown_limit: float = 95.0

    # Tier cutoffs
    tier1_min_score: float = 70.0
    tier2_min_score: float = 50.0
    tier3_min_score: float = 35.0


# ── Combined config ───────────────────────────────────────────
@dataclass
class UniverseConfig:
    """Top-level config aggregating all stages."""

    pre_screen: PreScreenConfig = field(default_factory=PreScreenConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)

    # Cache behaviour
    use_backtest_cache: bool = True   # skip re-backtest if cache exists
    force_refresh: bool = False       # override cache
