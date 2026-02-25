"""
MT5DataProvider — Fetches live OHLCV data from MetaTrader 5 terminal.

Design:
  - Pure live fetch: no resample fallback, no cache.
  - Returns None when the broker simply has no data for the requested TF.
  - Call site decides what to do (e.g. resample from H4).

Typical usage: called by UnifiedProvider when parquet cache is missing/stale.
"""
from __future__ import annotations

import logging
from typing import Optional

import polars as pl

from infra.data.utils.tf_mapping import mt5_timeframe
from infra.data.utils.column_normalizer import normalize_mt5_columns

logger = logging.getLogger(__name__)


class MT5DataProvider:
    """
    Live data from MetaTrader 5 terminal.

    - connect() must be called (or auto-called on first get_data()).
    - NO resample fallback: if broker has no W1 bars → returns None.
    """

    def __init__(self):
        self._connected: bool = False

    # ------------------------------------------------------------------ #
    #  Connection                                                          #
    # ------------------------------------------------------------------ #

    def connect(self) -> bool:
        if self._connected:
            return True
        try:
            import MetaTrader5 as mt5
            from infra.settings_loader import get_mt5_config
            cfg = get_mt5_config()
            ok = mt5.initialize(
                login=int(cfg["username"]),
                password=cfg["password"],
                server=cfg["server"],
                path=cfg.get("mt5Pathway"),
            )
            if not ok:
                ok = mt5.initialize(path=cfg.get("mt5Pathway"))
            self._connected = bool(ok)
            return self._connected
        except Exception as exc:
            logger.error("MT5 connect failed: %s", exc)
            return False

    def is_connected(self) -> bool:
        if not self._connected:
            return False
        try:
            import MetaTrader5 as mt5
            return mt5.terminal_info() is not None
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    #  Data fetch                                                          #
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
        Fetch native OHLCV bars from MT5 terminal.

        Returns None (no resample fallback) if broker has insufficient data.
        """
        if not self._connected:
            if not self.connect():
                return None

        import MetaTrader5 as mt5

        mt5_tf = mt5_timeframe(timeframe)
        if mt5_tf is None:
            logger.error("Unsupported timeframe: %s", timeframe)
            return None

        if not mt5.symbol_select(symbol, True):
            # Debug-level: expected for non-MT5 symbols (e.g. Binance "D/USDT")
            logger.debug("Cannot select symbol: %s", symbol)
            return None

        limit = bars if bars else 10_000
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, limit)

        if rates is None or len(rates) == 0:
            logger.warning("MT5 returned no data for %s %s", symbol, timeframe)
            return None

        return normalize_mt5_columns(pl.DataFrame(rates))

    def get_tick_size(self, symbol: str) -> Optional[float]:
        """Return minimum tick size for symbol."""
        if not self._connected:
            if not self.connect():
                return None
        import MetaTrader5 as mt5
        info = mt5.symbol_info(symbol)
        return info.point if info else None
