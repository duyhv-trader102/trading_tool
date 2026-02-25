"""
markets/base/data_provider.py

Market-facing data provider base and MT5 concrete implementation.

``BaseDataProvider`` lives in ``data_providers.base`` (the infrastructure
layer shared by all consumers).  This module re-exports it for convenience
and provides the MT5-specific concrete class.
"""
from __future__ import annotations

from typing import Optional, List
import polars as pl

# Re-export the canonical abstract base (single source of truth)
from data_providers.base import BaseDataProvider  # noqa: F401


class MT5DataProvider(BaseDataProvider):
    """Concrete provider that reads live / cached data via UnifiedDataProvider."""

    def __init__(self):
        from infra.data.mt5_provider import MT5Provider
        self.provider = MT5Provider()

    def get_data(
        self,
        symbol: str,
        timeframe: str,
        bars: Optional[int] = None,
        *,
        has_weekend: bool = False,
    ) -> Optional[pl.DataFrame]:
        return self.provider.get_ohlc(symbol, timeframe, bars or 2000, has_weekend=has_weekend)

    def ensure_data(self, symbol: str, timeframe: str) -> bool:
        """Return True when the MT5 connection is live."""
        if not self.provider._connected:
            return self.provider.connect()
        return self.provider.check_connection()

    def get_all_symbols(self) -> List[str]:
        raise NotImplementedError("MT5DataProvider does not enumerate symbols; use market configs.")
