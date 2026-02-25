"""
BaseDataProvider — Abstract interface for all data providers.

All concrete providers (MT5, Parquet, Binance…) implement this contract.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
import polars as pl


class BaseDataProvider(ABC):
    """
    Single responsibility: return a Polars OHLCV DataFrame.

    Columns guaranteed: time (datetime), open, high, low, close
    Optional extra: tick_volume, spread, real_volume
    """

    @abstractmethod
    def get_data(
        self,
        symbol: str,
        timeframe: str,           # "H4" | "D1" | "W1" | …
        bars: Optional[int] = None,
        *,
        has_weekend: bool = False,
    ) -> Optional[pl.DataFrame]:
        """
        Fetch OHLCV bars.

        Args:
            symbol:      Broker symbol, e.g. "AUDCADm", "XAUUSD"
            timeframe:   "H4", "D1", "W1", "MN1" …
            bars:        Max bars to return; None = all available
            has_weekend: Include Saturday/Sunday bars (crypto)

        Returns:
            Polars DataFrame or None if data unavailable.

        Notes:
            - NO automatic resample fallback in this layer.
              If the broker has no W1 data, return None — let the
              caller decide whether to resample from H4.
            - The DataFrame is always sorted ascending by time.
        """
        ...
