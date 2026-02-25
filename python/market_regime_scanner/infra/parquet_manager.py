import logging
import os
from pathlib import Path
from typing import List, Optional

import polars as pl
from infra.mt5 import get_historical_data

logger = logging.getLogger(__name__)

# Legacy local path — kept for backward-compat (observer.py etc.)
_DATA_DIR = os.path.join(Path(__file__).resolve().parent.parent, "data", "mt5")


def _s3_rel_key(symbol: str, timeframe: str) -> str:
    """S3 relative key (under ``data/``) for a symbol/timeframe parquet."""
    return f"mt5/{symbol}_{timeframe}.parquet"

# Symbols to fetch
SYMBOLS: List[str] = [
    "XAUUSDm",
    "EURUSDm",
    "USDJPYm",
    "BTCUSDm",
    "GBPJPYm",
]


def get_parquet_path(symbol: str, timeframe: str) -> str:
    """Get the path to parquet file for a symbol/timeframe."""
    return os.path.join(_DATA_DIR, f"{symbol}_{timeframe}.parquet")


def load_from_parquet(symbol: str, timeframe: str) -> Optional[pl.DataFrame]:
    """Load data from S3 (primary) or local fallback."""
    from infra.s3_storage import read_parquet_s3
    rel = _s3_rel_key(symbol, timeframe)
    df = read_parquet_s3(rel)
    if df is not None:
        return df
    # Fallback: local file (backward compat / offline)
    path = get_parquet_path(symbol, timeframe)
    if os.path.exists(path):
        return pl.read_parquet(path)
    return None


def _rates_to_df(rates) -> pl.DataFrame:
    """Convert MT5 numpy rates array to Polars DataFrame."""
    df = pl.from_numpy(rates)
    return df.with_columns(
        (pl.col("time").cast(pl.Int64) * 1_000).cast(pl.Datetime("ms")).alias("time")
    )


def resample_ohlc(df: pl.DataFrame, target_tf: str, *, has_weekend: bool = False) -> pl.DataFrame:
    """
    Resample H1 OHLC data to higher timeframes.
    
    Args:
        df: H1 DataFrame with columns [time, open, high, low, close, tick_volume, spread, real_volume]
        target_tf: Target timeframe - "H4", "D1", "W1", "M1" (monthly)
        has_weekend: If True the asset trades on weekends (crypto).
                     If False (forex/commodities) Sunday bars are shifted
                     to Monday before grouping.
    
    Returns:
        Resampled DataFrame
    """
    from datetime import timedelta

    interval_map = {
        "H4": "4h",
        "D1": "1d",
        "W1": "1w",
        "M1": "1mo",
    }
    
    interval = interval_map.get(target_tf)
    if interval is None:
        raise ValueError(f"Unknown timeframe: {target_tf}")

    df = df.sort("time")

    # For non-weekend assets: shift Sunday bars → Monday so that
    # D1 has no phantom Sunday bar and W1/M1 boundaries align with broker.
    if not has_weekend:
        df = df.with_columns(
            pl.when(pl.col("time").dt.weekday() == 7)  # Sunday = 7
            .then(pl.col("time") + timedelta(days=1))
            .otherwise(pl.col("time"))
            .alias("time")
        )
        df = df.sort("time")

    # Group by time interval and aggregate OHLC
    resampled = (
        df
        .group_by_dynamic("time", every=interval, closed="left", label="left")
        .agg([
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("tick_volume").sum().alias("tick_volume"),
            pl.col("spread").mean().cast(pl.Int64).alias("spread"),
            pl.col("real_volume").sum().alias("real_volume"),
        ])
    )

    # For weekly resample on non-weekend assets: shift labels from Monday
    # (ISO) back to Sunday (broker convention).
    if interval == "1w" and not has_weekend:
        resampled = resampled.with_columns(
            (pl.col("time") - timedelta(days=1)).alias("time")
        )
    
    return resampled


def fetch_h1_and_resample(symbol: str, years: int = 5, out_dir: str = None, *, has_weekend: bool = False):
    """
    Fetch H1 data and generate all higher timeframes by resampling.
    
    All data is written directly to S3 (no local files).

    Parameters
    ----------
    has_weekend : bool
        True for crypto (24/7 markets). When False, Sunday bars are
        shifted to Monday before resampling.
    """
    # Calculate bars needed for N years of H1 data
    # ~252 trading days * 24 hours * years
    bars = 252 * 24 * years
    
    logger.info("Fetching %s H1 (%d bars for %d years)...", symbol, bars, years)
    rates = get_historical_data(symbol, "H1", bars)
    
    if rates is None or len(rates) == 0:
        logger.warning("No H1 data fetched for %s", symbol)
        return
    
    df_h1 = _rates_to_df(rates)
    
    # Save H1 → S3
    from infra.s3_storage import write_parquet_s3
    write_parquet_s3(_s3_rel_key(symbol, "H1"), df_h1)
    logger.info("  H1: %d rows → S3", len(df_h1))
    
    # Resample and save higher timeframes → S3
    for tf in ["H4", "D1", "W1", "M1"]:
        df_tf = resample_ohlc(df_h1, tf, has_weekend=has_weekend)
        write_parquet_s3(_s3_rel_key(symbol, tf), df_tf)
        logger.info("  %s: %d rows → S3", tf, len(df_tf))


# Symbols to fetch — (symbol, has_weekend)
_SYMBOL_WEEKEND = {
    "BTCUSDm": True,
}


def fetch_all_symbols(years: int = 5):
    """Fetch H1 data for all symbols and resample to higher timeframes."""
    for symbol in SYMBOLS:
        try:
            fetch_h1_and_resample(
                symbol, years=years,
                has_weekend=_SYMBOL_WEEKEND.get(symbol, False),
            )
        except Exception as e:
            logger.error("Failed to fetch %s: %s", symbol, e)


# Legacy functions for backward compatibility
def fetch_and_store_history(symbol, timeframe, years=5, out_dir=None):
    """Fetch N years of history from MT5 and save to S3."""
    from infra.s3_storage import write_parquet_s3
    tf_map = {"D1": 252, "H1": 252 * 24, "W1": 52, "M1": 12 * 5}
    bars = tf_map.get(timeframe, 252) * years
    rates = get_historical_data(symbol, timeframe, bars)
    if rates is None:
        logger.warning("No data fetched for %s %s", symbol, timeframe)
        return
    df = _rates_to_df(rates)
    rel = _s3_rel_key(symbol, timeframe)
    write_parquet_s3(rel, df)
    logger.info("Saved %d rows → S3: %s", len(df), rel)


def fetch_and_store_data(symbol: str, timeframe: str, bars: int, out_dir=None) -> pl.DataFrame:
    """Fetch from MT5 and write directly to S3 (no local file)."""
    from infra.s3_storage import write_parquet_s3

    rates = get_historical_data(symbol, timeframe, bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No data returned from MT5 for {symbol} {timeframe}")

    df = _rates_to_df(rates)
    rel = _s3_rel_key(symbol, timeframe)
    write_parquet_s3(rel, df)
    logger.info("Saved %d rows → S3: %s", len(df), rel)
    return df


def update_parquet(symbol: str, timeframe: str, bars: int = 500, out_dir=None) -> Optional[pl.DataFrame]:
    """
    Update existing S3 parquet with latest bars from MT5.
    
    - If file doesn't exist on S3: full fetch.
    - If file exists: fetch recent bars, merge (dedup by time), write back.
    
    No local files are created — everything streams through S3.
    """
    from infra.s3_storage import read_parquet_s3, write_parquet_s3

    rel = _s3_rel_key(symbol, timeframe)

    # Fetch latest bars from MT5
    rates = get_historical_data(symbol, timeframe, bars)
    if rates is None or len(rates) == 0:
        logger.warning("No data from MT5 for %s %s — keeping existing", symbol, timeframe)
        return load_from_parquet(symbol, timeframe)

    df_new = _rates_to_df(rates)

    # Read existing from S3
    df_old = read_parquet_s3(rel)
    if df_old is None:
        # No existing file — just write the new data
        write_parquet_s3(rel, df_new)
        logger.info("Created %d rows → S3: %s", len(df_new), rel)
        return df_new

    old_count = len(df_old)

    # Align schemas: keep only columns present in df_new (canonical MT5 schema).
    if df_old.columns != df_new.columns:
        shared = [c for c in df_new.columns if c in df_old.columns]
        df_old = df_old.select(shared)

    # Normalise time precision: legacy files may be μs, new data is ms.
    if df_old.schema.get("time") != pl.Datetime("ms"):
        df_old = df_old.with_columns(pl.col("time").cast(pl.Datetime("ms")))

    df_merged = pl.concat([df_old, df_new]).unique(subset=["time"], keep="last").sort("time")
    new_bars_added = len(df_merged) - old_count

    write_parquet_s3(rel, df_merged)
    logger.info("Updated %s %s: %d existing + %d new = %d total → S3",
                symbol, timeframe, old_count, new_bars_added, len(df_merged))
    return df_merged


if __name__ == "__main__":
    import sys
    from infra import mt5
    from infra.settings_loader import get_mt5_config
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    
    # Connect to MT5
    config = get_mt5_config()
    mt5.start_mt5(
        username=int(config['username']),
        password=config['password'],
        server=config['server'],
        mt5Pathway=config['mt5Pathway']
    )
    
    # Fetch all symbols
    years = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print(f"\n{'='*60}")
    print(f"  Fetching {years} years of H1 data for all symbols")
    print(f"  Symbols: {', '.join(SYMBOLS)}")
    print(f"{'='*60}\n")
    
    fetch_all_symbols(years=years)
    
    print(f"\n{'='*60}")
    print("  Done! All data saved to S3")
    print(f"{'='*60}")
