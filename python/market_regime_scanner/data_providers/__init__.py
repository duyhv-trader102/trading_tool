"""
data_providers — Unified data access layer.

Public API::

    from data_providers import get_data, get_provider

    # One-shot call (uses a module-level shared provider)
    df = get_data("AUDCADm", "D1")

    # Or get an instance for explicit lifecycle control
    p = get_provider()
    df = p.get_data("AUDCADm", "D1")
    p.update_cache("AUDCADm", "D1")

Design rules:
  - Both Scanner and Observer import from here.
  - No resample in the provider layer.
  - Parquet is the cache; MT5 is the source of truth when online.
"""
from __future__ import annotations

from typing import Optional
import polars as pl

from data_providers.base import BaseDataProvider
from data_providers.mt5_data_provider import MT5DataProvider
from data_providers.parquet_data_provider import (
    ParquetDataProvider,
    get_path,
    save,
    append_new,
)
from data_providers.unified_provider import UnifiedDataProvider

# ── Register well-known market data directories ────────────────────────
# These are always registered here so any consumer (observer, scanner,
# backtest) can locate Binance / VNStock parquets without needing to
# import the market-specific provider modules first.
from pathlib import Path as _Path
_MARKET_DATA_ROOT = _Path(__file__).resolve().parent.parent / "data"

def _register_known_fallbacks() -> None:
    _known: list[tuple[str, str]] = [
        (str(_MARKET_DATA_ROOT / "binance"), "H4"),
        (str(_MARKET_DATA_ROOT / "vnstock"), "D1"),
    ]
    for _dir, _tf in _known:
        # Register regardless of whether the local dir exists — `ParquetDataProvider`
        # will fall through to S3 streaming when the local file is absent.
        ParquetDataProvider.register_fallback(_dir, _tf)

_register_known_fallbacks()

# ── Module-level shared provider instance ─────────────────────────────
# Shared by default callers (scanner, observer, scripts).
# Each call reuses the same parquet cache + MT5 connection.
_provider: Optional[UnifiedDataProvider] = None


def get_provider(auto_connect: bool = True) -> UnifiedDataProvider:
    """Return (or create) the module-level shared provider."""
    global _provider
    if _provider is None:
        _provider = UnifiedDataProvider(auto_connect=auto_connect)
    return _provider


def get_data(
    symbol: str,
    timeframe: str,
    bars: Optional[int] = None,
    *,
    has_weekend: bool = False,
    auto_connect: bool = True,
) -> Optional[pl.DataFrame]:
    """
    Convenience wrapper — fetch OHLCV data using the shared provider.

    Parquet-first; falls back to live MT5 fetch + auto-cache if missing.
    NO resample. Returns None when data truly unavailable.
    """
    return get_provider(auto_connect).get_data(
        symbol, timeframe, bars, has_weekend=has_weekend
    )


__all__ = [
    "BaseDataProvider",
    "MT5DataProvider",
    "ParquetDataProvider",
    "UnifiedDataProvider",
    "get_provider",
    "get_data",
    # parquet helpers
    "get_path",
    "save",
    "append_new",
]
