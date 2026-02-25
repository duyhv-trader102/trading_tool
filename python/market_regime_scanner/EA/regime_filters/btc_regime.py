"""
BTC Regime Filter — Block altcoin buys when BTC Monthly MBA is bearish.

Logic:
    Pre-compute BTC Monthly MBA direction for every date.
    On any given date, if BTC Monthly MBA direction == "bearish"
    → block bullish (long/buy) entries for all altcoins.

    BTC itself is excluded from the gate (it trades on its own signal).

Data:
    Reads ``data/binance/BTC_USDT_H4.parquet`` → resamples to D1/W1 →
    builds Monthly TPO sessions → extracts MBA direction per day.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import polars as pl

from EA.regime_filters.base import BaseRegimeFilter, RegimeVerdict

logger = logging.getLogger(__name__)


class BtcRegimeFilter(BaseRegimeFilter):
    """Gate altcoin longs when BTC Monthly MBA is bearish."""

    def __init__(self, data_dir: str = ""):
        # data_dir kept for backward compatibility — data is read from S3 in build()
        self._lookup: Dict[str, str] = {}

    @property
    def name(self) -> str:
        return "btc_regime"

    # ── Build ─────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Pre-compute date → BTC Monthly MBA direction lookup."""
        from core.tpo import TPOProfile
        from core.resampler import resample_data
        from analytic.tpo_mba.tracker import build_mba_context

        from infra.s3_storage import read_parquet_s3
        df_h4 = read_parquet_s3("binance/BTC_USDT_H4.parquet")
        if df_h4 is None:
            logger.warning(
                "BTC data not found on S3 (binance/BTC_USDT_H4.parquet) — BTC filter disabled"
            )
            self._lookup = {}
            return

        df_h4 = df_h4.sort("time")
        df_d1 = resample_data(df_h4, "D1", has_weekend=True)
        df_w1 = resample_data(df_h4, "W1", has_weekend=True)

        engine = TPOProfile(va_percentage=0.7, ib_bars=2)
        all_m = engine.analyze_dynamic(df_w1, session_type="M")

        lookup: Dict[str, str] = {}
        for i in range(len(df_d1)):
            current_date = df_d1[i, "time"]
            date_str = current_date.strftime("%Y-%m-%d")

            closed_m = [
                s for s in all_m
                if s.session_end < current_date and s.is_closed
            ]
            if len(closed_m) < 3:
                lookup[date_str] = "neutral"
                continue

            meta_m = build_mba_context(
                closed_m, timeframe="Monthly", symbol="BTC"
            )
            if meta_m and meta_m.is_ready and meta_m.ready_direction:
                lookup[date_str] = meta_m.ready_direction
            else:
                lookup[date_str] = "neutral"

        self._lookup = lookup
        logger.info("BtcRegimeFilter: %d dates indexed", len(lookup))

    # ── Check ─────────────────────────────────────────────────────────────

    def check(
        self,
        date_str: str,
        *,
        direction: str = "bullish",
        symbol: str = "",
    ) -> RegimeVerdict:
        """Block bullish altcoin entries when BTC Monthly is bearish."""
        # BTC itself is not gated by this filter
        if symbol.upper().startswith("BTC"):
            return RegimeVerdict(blocked=False, filter_name=self.name)

        btc_dir = self._lookup.get(date_str, "neutral")

        if direction == "bullish" and btc_dir == "bearish":
            return RegimeVerdict(
                blocked=True,
                reason=f"BTC Monthly MBA bearish on {date_str}",
                filter_name=self.name,
                details={"btc_direction": btc_dir, "date": date_str},
            )

        return RegimeVerdict(blocked=False, filter_name=self.name)

    def get_state(self, date_str: str) -> str:
        return self._lookup.get(date_str, "neutral")
