"""
UnifiedDataProvider — Single entry point for all OHLCV data.

Strategy (in order):
  1. ParquetCache  — fast, offline, deterministic.
     Registered fallback dirs (vnstock, binance, …) are searched here.
  2. Resample      — if cached data exists at a finer TF, resample UP locally.
     (E.g. Binance stores H4 → resample to D1/W1.  VNStock stores D1 → W1.)
  3. MT5 live      — fetch when cache is truly missing; save to parquet.

Resample lives HERE (not in parquet layer), honouring the rule
"NO resample in the provider layer below".

Both Scanner and Observer MUST use this provider so they always read
from the same data source and produce identical session typings.
"""
from __future__ import annotations

import logging
from typing import Optional

import polars as pl

from data_providers.base import BaseDataProvider
from data_providers.parquet_data_provider import ParquetDataProvider
from data_providers.mt5_data_provider import MT5DataProvider

logger = logging.getLogger(__name__)

# Default fetch size when no limit is specified
_DEFAULT_BARS = 5_000

# Timeframe hierarchy: lower index = finer resolution.
# Resampling is only valid from a finer TF to a coarser TF (lower→higher index).
_TF_ORDER = {"H1": 0, "H4": 1, "D1": 2, "W1": 3, "M1": 4, "MN1": 4}


def _can_resample(stored_tf: str, target_tf: str) -> bool:
    """Return True if *stored_tf* can be aggregated UP to *target_tf*.

    E.g. H4→D1 ✓, D1→W1 ✓, D1→H4 ✗ (would require fabricating data).
    """
    s = _TF_ORDER.get(stored_tf.upper())
    t = _TF_ORDER.get(target_tf.upper())
    if s is None or t is None:
        return False  # unknown TF — refuse to guess
    return s < t  # stored must be strictly finer


class UnifiedDataProvider(BaseDataProvider):
    """
    Parquet-first, MT5-fallback provider with resample support.

    Usage::

        from data_providers import get_provider
        p = get_provider()
        df = p.get_data("AUDCADm", "D1")

    Thread-safety: not guaranteed; create one instance per thread.
    """

    def __init__(self, auto_connect: bool = True):
        self._parquet = ParquetDataProvider()
        self._mt5: Optional[MT5DataProvider] = None
        self._auto_connect = auto_connect

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def get_data(
        self,
        symbol: str,
        timeframe: str,
        bars: Optional[int] = None,
        *,
        has_weekend: bool = False,
    ) -> Optional[pl.DataFrame]:
        """
        Return OHLCV DataFrame for *symbol* at *timeframe*.

        Resolution order:
          1. Exact-TF parquet hit (primary MT5 dir or registered fallbacks).
          2. Finer stored TF parquet + resample UP (local, no network).
          3. Live MT5 fetch + cache (last resort).

        Returns None when data is truly unavailable.
        """
        tf = timeframe.upper()

        # ── 1. Exact TF from parquet (any registered directory) ──────────
        df = self._parquet.get_data(symbol, tf, bars, has_weekend=has_weekend)
        if df is not None:
            return df

        # ── 2. Fallback: finer stored TF + resample UP (local, no network) ──
        # Try this BEFORE MT5 so symbols stored at a finer TF (e.g. Binance
        # H4-only) are resampled locally rather than triggering a failed MT5
        # lookup that would produce a noisy "Cannot select symbol" error.
        # NOTE: We can only aggregate UP (finer→coarser), e.g. H4→D1, D1→W1.
        # Resampling DOWN (D1→H4) is impossible and must be skipped.
        raw, stored_tf = self._parquet.get_raw_with_tf(symbol, tf, bars)
        if raw is not None and stored_tf is not None and stored_tf != tf:
            if not _can_resample(stored_tf, tf):
                logger.debug(
                    "Skip resample %s %s→%s (cannot downsample)",
                    symbol, stored_tf, tf,
                )
                raw = None  # fall through to MT5 or give up
            else:
                logger.info(
                    "Resampling %s %s→%s (%d bars)", symbol, stored_tf, tf, len(raw)
                )
                try:
                    from core.resampler import resample_data
                    df = resample_data(raw, tf, has_weekend=has_weekend)
                    if bars and len(df) > bars:
                        df = df.slice(-bars, bars)
                    return df
                except Exception as exc:
                    logger.warning(
                        "Resample %s %s→%s failed: %s", symbol, stored_tf, tf, exc
                    )

        # ── 3. Try MT5 live fetch + auto-cache ───────────────────────────
        # Skip MT5 for exchange-format symbols (Binance "BTC/USDT", etc.) —
        # they cannot be resolved by MT5 and would produce misleading errors.
        if "/" in symbol or ":" in symbol:
            logger.debug("No data for %s %s (non-MT5 symbol, S3 miss)", symbol, tf)
            return None

        mt5 = self._get_mt5()
        if mt5 is not None:
            logger.info("Cache miss %s %s — fetching from MT5...", symbol, tf)
            fetch_bars = bars if bars else _DEFAULT_BARS
            df = mt5.get_data(symbol, tf, fetch_bars, has_weekend=has_weekend)
            if df is not None and not df.is_empty():
                # NOTE: intentionally NOT writing to local disk — data is
                # served from S3 (streamed) or MT5 live.  Local data/ dir
                # is not used outside of the observer sync workflow.
                logger.info("MT5 live %d bars → %s %s", len(df), symbol, tf)
                if bars and len(df) > bars:
                    df = df.slice(-bars, bars)
                return df

        logger.warning("No data for %s %s", symbol, tf)
        return None

    def update_cache(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 500,
        *,
        has_weekend: bool = False,
    ) -> bool:
        """
        Pull latest *bars* from MT5 and merge into parquet cache.

        Returns True on success.
        """
        from data_providers.parquet_data_provider import append_new
        mt5 = self._get_mt5()
        if mt5 is None:
            return False

        df = mt5.get_data(symbol, timeframe, bars, has_weekend=has_weekend)
        if df is None or df.is_empty():
            return False

        append_new(symbol, timeframe, df)
        return True

    def get_tick_size(self, symbol: str) -> Optional[float]:
        mt5 = self._get_mt5()
        if mt5:
            return mt5.get_tick_size(symbol)
        return None

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _get_mt5(self) -> Optional[MT5DataProvider]:
        """Lazily initialise MT5 connection."""
        if not self._auto_connect:
            return None
        if self._mt5 is None:
            self._mt5 = MT5DataProvider()
        if not self._mt5.is_connected():
            self._mt5.connect()
        return self._mt5 if self._mt5.is_connected() else None
