"""
Pipeline - Core orchestration for TPO analysis.

Provides reusable functions for:
- Loading data from parquet or MT5
- Two-pass TPO analysis with dynamic block size
"""
import polars as pl
from typing import List, Tuple

from core.data_provider import DataProvider
from core.tpo import TPOProfile, calc_block_size, TPOResult, SessionType
from core.convergence import get_default_rows
from core.session_policy import get_session_policy
from infra.parquet_manager import load_from_parquet

def get_data(symbol: str, timeframe: str, provider: DataProvider = None, bars: int = None, use_parquet: bool = True) -> pl.DataFrame:
    """
    Get OHLC data from parquet (if available) or DataProvider.
    
    Args:
        symbol: Trading symbol
        timeframe: Data timeframe (D1, H4, etc.)
        provider: DataProvider instance (MT5, VNStock, Binance)
        bars: Number of bars (only used when fetching from provider)
        use_parquet: Try loading from parquet first
    
    Returns:
        Polars DataFrame with OHLC data, or None if not available
    """
    # 1. Try Parquet Cache First
    if use_parquet:
        df = load_from_parquet(symbol, timeframe)
        if df is not None:
            if bars and len(df) > bars:
                df = df.slice(-bars, bars)
            return df

    # 2. Fall back to Data Provider
    if provider is None:
        # For backward compatibility (or simplistic usage), we might auto-detect
        # But ideally, caller provides it.
        # print("Warning: No DataProvider provided and not found in parquet.")
        return None

    if bars is None:
        bars = 100
        
    df = provider.get_ohlc(symbol, timeframe, limit=bars)
    
    # Provider is responsible for returning clean Polars DF, so we just return it
    return df


def analyze_from_df(
    df: pl.DataFrame,
    session_type: str,
    sat_sun: str = 'Normal',
    target_rows: int = None,
    min_block: float = None,
    ib_bars: int = 2,
    policy_name: str = "mt5",
) -> Tuple[List[TPOResult], float]:
    """
    Two-pass TPO analysis from DataFrame (no MT5 query).

    Pass 1: Coarse block (2× default_rows) to detect sessions.
    Pass 2: analyze_dynamic with Convergence Consensus — auto-calibrates
            target_rows per session from get_default_rows(session_type).

    Args:
        target_rows: Override for coarse-pass block sizing and returned block_size.
                     Defaults to get_default_rows(session_type) (25/25/20).
                     Has NO effect on individual session target_rows when
                     use_convergence=True (the default in analyze_dynamic).

    Returns:
        (results: List[TPOResult], block_size: float)
    """
    if df.is_empty():
        return [], 0

    # Resolve target_rows: fall back to convergence default for this session type
    rows = target_rows if target_rows is not None else get_default_rows(session_type)

    policy = get_session_policy(policy_name)

    # Pass 1: coarse block to detect sessions (2× rows → large blocks, fast split)
    # min_bars=1 for high-TF session types where 1 bar = 1 session
    min_b = 1 if session_type in ('D', 'W', 'M') else 3

    overall_range = df['high'].max() - df['low'].min()
    initial_block = calc_block_size(overall_range, rows * 2, min_block)
    tpo_raw = TPOProfile(tick_size=initial_block, va_percentage=0.7, ib_bars=ib_bars)
    raw_results = tpo_raw.analyze(df, session_type=session_type, sat_sun_solution=sat_sun, min_bars=min_b, policy=policy)

    if not raw_results:
        return [], 0

    # Pass 2: per-session dynamic block via Convergence Consensus
    tpo = TPOProfile(tick_size=initial_block, va_percentage=0.7, ib_bars=ib_bars)
    results = tpo.analyze_dynamic(
        df, session_type=session_type, sat_sun_solution=sat_sun,
        min_block=min_block, min_bars=min_b,
        policy=policy
        # target_rows intentionally omitted → analyze_dynamic uses get_default_rows internally
    )

    # Representative block size for callers (viz sizing only)
    if results:
        max_range = max(r.range for r in results)
        min_ib = min((r.ib_range for r in results if r.ib_range > 0), default=None)
        block_size = calc_block_size(max_range, rows, min_block, ib_range=min_ib)
    else:
        block_size = initial_block

    return results, block_size


def analyze_timeframe(
    symbol: str,
    data_tf: str,
    session_type: str,
    provider: DataProvider = None,
    bars: int = 100,
    sat_sun: str = 'Normal',
    target_rows: int = None,
    min_block: float = None,
    ib_bars: int = 2,
    policy_name: str = "mt5",
    use_parquet: bool = True
):
    df = get_data(symbol, data_tf, provider=provider, bars=bars, use_parquet=use_parquet)
    # If no data, return empty
    if df is None:
        return [], 0
        
    return analyze_from_df(
        df, session_type, sat_sun, 
        target_rows=target_rows, 
        min_block=min_block, 
        ib_bars=ib_bars,
        policy_name=policy_name
    )


# ── Deprecated compat stubs ─────────────────────────────────────────
# These functions are kept for backward compatibility with EA code
# that has not yet migrated to the new tracker-based workflow.
# New code should use analytic.tpo_mba.tracker directly.

def classify_regime(results: list) -> list:
    """Classify sessions using detector's _build_regime_result.

    .. deprecated:: Use ``build_mba_context()`` from ``analytic.tpo_mba.tracker`` instead.
    """
    import warnings
    warnings.warn(
        "classify_regime() is deprecated. Use build_mba_context() from analytic.tpo_mba.tracker.",
        DeprecationWarning,
        stacklevel=2,
    )
    if len(results) < 2:
        return []
    from analytic.tpo_mba.detector import _build_regime_result, _detect_responsive_activity
    regimes = []
    for i in range(1, len(results)):
        current = results[i]
        previous = results[i - 1]
        # _detect_responsive_activity expects (session, imbalance_direction)
        # but we don't have imbalance_direction here, so pass None
        activity = _detect_responsive_activity(current, None)
        regime_label = "BALANCE"
        direction = None
        rules: list = []
        regime = _build_regime_result(
            current, previous, regime_label, direction, rules, activity
        )
        regimes.append(regime)
    return regimes
