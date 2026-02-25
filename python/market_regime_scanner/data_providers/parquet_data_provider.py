"""
ParquetDataProvider — Read / write OHLCV data from local Parquet cache.

Storage layout:
    data/mt5/{symbol}_{timeframe}.parquet     (primary, MT5-backed markets)

Additional market directories are registered at import-time by each
market's data_provider module via `ParquetDataProvider.register_fallback()`.

Design rules:
  - NO automatic resample in this layer (callers handle resample).
  - Search is: primary dir → registered fallback dirs in order.
  - If a file exists in a fallback dir but not at the requested TF,
    we return (df, stored_tf) so the caller can resample at its layer.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Tuple

import polars as pl

logger = logging.getLogger(__name__)

# ── Primary parquet storage (MT5-backed markets) ─────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "mt5"
_DATA_ROOT = Path(__file__).resolve().parent.parent / "data"

# ── S3 auto-sync toggle ──────────────────────────────────────────────────────
# S3 is lazy-initialized on first use.  Set S3_BUCKET="" to disable.
_s3_instance = None   # lazy singleton
_s3_checked = False   # whether we already tried to init


def _get_s3():
    """Return the shared S3Storage instance (lazy), or None if S3 is disabled."""
    global _s3_instance, _s3_checked
    if _s3_checked:
        return _s3_instance
    _s3_checked = True
    # Ensure .env is loaded before checking env vars
    try:
        from infra.settings_loader import _load_dotenv
        _load_dotenv()
    except Exception:
        pass
    if not os.environ.get("S3_BUCKET", ""):
        return None
    try:
        from infra.s3_storage import S3Storage
        _s3_instance = S3Storage()
    except Exception as exc:
        logger.warning("S3 unavailable — disabled: %s", exc)
    return _s3_instance


def _rel_path(local_path: Path) -> Optional[str]:
    """Convert an absolute local path to a relative path under data/."""
    try:
        return str(local_path.relative_to(_DATA_ROOT)).replace("\\", "/")
    except ValueError:
        return None


def _try_s3_read(local_path: Path) -> Optional[pl.DataFrame]:
    """Try to read a parquet file directly from S3 (no local download).

    Returns the DataFrame or None.
    """
    rel = _rel_path(local_path)
    if rel is None:
        return None
    try:
        from infra.s3_storage import read_parquet_s3
        return read_parquet_s3(rel)
    except Exception as exc:
        logger.debug("S3 read failed for %s: %s", rel, exc)
        return None


def _s3_upload(local_path: Path) -> None:
    """Best-effort upload of a freshly written parquet to S3."""
    s3 = _get_s3()
    if s3 is None:
        return
    rel = _rel_path(local_path)
    if rel is None:
        return
    try:
        s3.upload_file(rel)
    except Exception as exc:
        logger.warning("S3 upload failed for %s: %s", rel, exc)


def get_path(symbol: str, timeframe: str) -> Path:
    """Return the primary parquet file path for a symbol/timeframe pair."""
    return _DATA_DIR / f"{symbol}_{timeframe}.parquet"


# ── Pluggable fallback registry ───────────────────────────────────────────────
# Each entry: (directory, stored_timeframe)
# Market providers call ParquetDataProvider.register_fallback() at import time.
# Example (in markets/vnstock/data_provider.py):
#   ParquetDataProvider.register_fallback(DATA_DIR, "D1")

class ParquetDataProvider:
    """
    Read-only view of the local parquet cache.

    Write operations (save / update) are exposed as module-level helpers
    so they can be called from the data-sync scripts independently of
    any provider instance.

    Fallback directories are registered by market providers via
    `ParquetDataProvider.register_fallback(directory, stored_tf)`.
    """

    # Class-level registry: list of (Path, stored_tf_str)
    _fallbacks: list[tuple[Path, str]] = []

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize symbol name to a safe filename component.

        e.g. ``ZRO/USDT`` → ``ZRO_USDT``,  ``BTC:USDT`` → ``BTC_USDT``
        """
        return symbol.replace("/", "_").replace(":", "_")

    @classmethod
    def register_fallback(cls, directory: str | Path, stored_tf: str) -> None:
        """
        Register an additional data directory for symbol lookup.

        Args:
            directory:  Absolute path to the market's parquet directory.
            stored_tf:  The timeframe stored in that directory (e.g. "D1", "H4").

        Market providers should call this once at module import, e.g.::

            ParquetDataProvider.register_fallback(DATA_DIR, "D1")
        """
        entry = (Path(directory), stored_tf.upper())
        if entry not in cls._fallbacks:
            cls._fallbacks.append(entry)
            logger.debug("Registered parquet fallback: %s (%s)", directory, stored_tf)

    def get_data(
        self,
        symbol: str,
        timeframe: str,
        bars: Optional[int] = None,
        *,
        has_weekend: bool = False,  # noqa: ARG002
    ) -> Optional[pl.DataFrame]:
        """
        Return OHLCV DataFrame at the *exact* requested timeframe, or None.

        Search order:
          1. Primary: data/mt5/{symbol}_{timeframe}.parquet
          2. Registered fallback dirs — exact TF match only.

        NO resample is performed.  If the file exists only at a different
        timeframe, the caller must use ``get_raw_with_tf()`` to detect
        the mismatch and resample at its own layer.
        """
        tf = timeframe.upper()

        # 1. Primary MT5 directory — exact match
        path = get_path(symbol, tf)
        if path.exists():
            return self._load(path, bars)

        # 2. Fallback directories — exact TF match only (no resample here)
        norm = self._normalize_symbol(symbol)
        for fb_dir, _ in self._fallbacks:
            # Try normalized name first (e.g. ZRO_USDT), then raw symbol
            for name in ({norm, symbol} if norm != symbol else {symbol}):
                fb_path = fb_dir / f"{name}_{tf}.parquet"
                if fb_path.exists():
                    return self._load(fb_path, bars)

        # 3. S3 fallback — read directly from S3 (no local download)
        candidates = [path]
        for fb_dir, _ in self._fallbacks:
            for name in ({norm, symbol} if norm != symbol else {symbol}):
                candidates.append(fb_dir / f"{name}_{tf}.parquet")
        for cand in candidates:
            df = _try_s3_read(cand)
            if df is not None:
                if bars and len(df) > bars:
                    df = df.slice(-bars, bars)
                return df

        return None

    def get_raw_with_tf(
        self,
        symbol: str,
        requested_tf: str,
        bars: Optional[int] = None,
    ) -> Tuple[Optional[pl.DataFrame], Optional[str]]:
        """
        Like ``get_data`` but also searches fallback dirs at their *stored* TF
        when an exact match is not found.

        Returns:
            (df, actual_tf) — actual_tf may differ from requested_tf.
            (None, None)    — if nothing found anywhere.

        The caller is responsible for resampling when actual_tf != requested_tf.
        """
        tf = requested_tf.upper()

        # 1. Primary: exact match
        path = get_path(symbol, tf)
        if path.exists():
            return self._load(path, bars), tf

        # 2. Fallbacks: exact match first, then stored-TF match
        norm = self._normalize_symbol(symbol)
        for fb_dir, stored_tf in self._fallbacks:
            for name in ({norm, symbol} if norm != symbol else {symbol}):
                exact = fb_dir / f"{name}_{tf}.parquet"
                if exact.exists():
                    return self._load(exact, bars), tf
                stored = fb_dir / f"{name}_{stored_tf}.parquet"
                if stored.exists():
                    return self._load(stored, bars), stored_tf

        # 3. S3 fallback — read directly from S3 (no local download)
        s3_candidates = [(path, tf)]
        for fb_dir, stored_tf in self._fallbacks:
            for name in ({norm, symbol} if norm != symbol else {symbol}):
                s3_candidates.append((fb_dir / f"{name}_{tf}.parquet", tf))
                s3_candidates.append((fb_dir / f"{name}_{stored_tf}.parquet", stored_tf))
        for cand, cand_tf in s3_candidates:
            df = _try_s3_read(cand)
            if df is not None:
                if bars and len(df) > bars:
                    df = df.slice(-bars, bars)
                return df, cand_tf

        return None, None

    def exists(self, symbol: str, timeframe: str) -> bool:
        """Return True if data is available at exactly this timeframe."""
        return self.get_data(symbol, timeframe) is not None

    @staticmethod
    def _load(path: Path, bars: Optional[int]) -> pl.DataFrame:
        df = pl.read_parquet(path)
        if bars and len(df) > bars:
            df = df.slice(-bars, bars)
        return df


# ── Write helpers (called by UnifiedProvider / data-sync scripts) ─────────────

def save(symbol: str, timeframe: str, df: pl.DataFrame) -> None:
    """Overwrite the primary parquet file with *df* (full history)."""
    path = get_path(symbol, timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    logger.debug("Saved %d rows → %s", len(df), path)
    _s3_upload(path)


def append_new(symbol: str, timeframe: str, new_df: pl.DataFrame) -> pl.DataFrame:
    """
    Append *new_df* to existing parquet, deduplicate by time, sort, save.

    Returns the merged DataFrame.
    """
    path = get_path(symbol, timeframe)
    if path.exists():
        old_df = pl.read_parquet(path)
        # Normalise time precision: legacy files may be μs, new data is ms.
        if old_df.schema.get("time") != new_df.schema.get("time"):
            old_df = old_df.with_columns(pl.col("time").cast(pl.Datetime("ms")))
            new_df = new_df.with_columns(pl.col("time").cast(pl.Datetime("ms")))
        merged = pl.concat([old_df, new_df]).unique("time", keep="last").sort("time")
    else:
        merged = new_df.sort("time")

    path.parent.mkdir(parents=True, exist_ok=True)
    merged.write_parquet(path)
    logger.debug("Updated %s %s → %d rows", symbol, timeframe, len(merged))
    _s3_upload(path)
    return merged
