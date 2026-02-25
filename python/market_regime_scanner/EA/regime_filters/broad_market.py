"""
Broad Market Bear Filter — Block spot buys when >N% of coins are bearish.

Logic:
    Pre-compute Monthly MBA direction for ALL coins in the universe.
    For each date, compute the percentage of coins whose Monthly MBA
    direction is "bearish".

    If **bear_pct >= threshold** (default 70%) → market is in bear mode
    → block all bullish/long spot entries.

Data:
    Reads all ``data/binance/{SYM}_USDT_H4.parquet`` files, resamples
    to W1, builds Monthly TPO sessions, extracts MBA direction per day.
    Uses the same TPO/MBA engine as the main backtest.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set

import polars as pl

from EA.regime_filters.base import BaseRegimeFilter, RegimeVerdict

logger = logging.getLogger(__name__)

# Minimum W1 bars required to compute a meaningful Monthly MBA
_MIN_W1_BARS = 40  # ~10 months of weekly data


class BroadMarketFilter(BaseRegimeFilter):
    """Gate spot longs when the broad market is in bear territory."""

    def __init__(
        self,
        data_dir: str = "",  # kept for backward compatibility — data is read from S3 in build()
        bear_threshold: float = 0.70,
        skip_symbols: Optional[Set[str]] = None,
        min_h4_bars: int = 4536,
    ):
        """
        Parameters
        ----------
        data_dir : str
            Deprecated. Kept for backward compatibility. Data is now read from S3.
        bear_threshold : float
            Fraction of coins that must be bearish to trigger (default 0.70).
        skip_symbols : set[str], optional
            Coins to exclude from the scan (e.g. stablecoins).
        min_h4_bars : int
            Minimum H4 bars for a coin to be included in the universe.
        """
        self.bear_threshold = bear_threshold
        self.skip_symbols = skip_symbols or set()
        self.min_h4_bars = min_h4_bars

        # date → {total_coins, bearish_count, bear_pct, is_bear}
        self._daily_stats: Dict[str, Dict] = {}
        self._universe: List[str] = []

    @property
    def name(self) -> str:
        return "broad_market"

    # ── Build ─────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Scan all coin H4 data and compute daily broad-market regime."""
        from core.tpo import TPOProfile
        from core.resampler import resample_data
        from analytic.tpo_mba.tracker import build_mba_context

        from infra.s3_storage import s3_dir_mtimes, read_parquet_s3

        # List all available H4 symbols from S3 (primary data store)
        mtimes = s3_dir_mtimes("binance")
        all_syms = {
            fname.replace("_USDT_H4.parquet", "")
            for fname in mtimes
            if fname.endswith("_USDT_H4.parquet")
        }

        if not all_syms:
            logger.warning("No H4 parquets found on S3 (binance/)")
            return

        engine = TPOProfile(va_percentage=0.7, ib_bars=2)

        # ── Phase 1: compute per-coin daily direction ──
        # coin_lookups[sym] = {date_str: "bullish"/"bearish"/"neutral"}
        coin_lookups: Dict[str, Dict[str, str]] = {}

        for sym in sorted(all_syms):
            if sym in self.skip_symbols:
                continue

            try:
                df_h4 = read_parquet_s3(f"binance/{sym}_USDT_H4.parquet")
                if df_h4 is None:
                    continue
                if len(df_h4) < self.min_h4_bars:
                    continue

                df_h4 = df_h4.sort("time")
                df_d1 = resample_data(df_h4, "D1", has_weekend=True)
                df_w1 = resample_data(df_h4, "W1", has_weekend=True)

                if len(df_w1) < _MIN_W1_BARS:
                    continue

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
                        closed_m, timeframe="Monthly", symbol=sym
                    )
                    if meta_m and meta_m.is_ready and meta_m.ready_direction:
                        lookup[date_str] = meta_m.ready_direction
                    else:
                        lookup[date_str] = "neutral"

                coin_lookups[sym] = lookup
                logger.debug("  %s: %d dates", sym, len(lookup))

            except Exception as exc:
                logger.warning("BroadMarketFilter: %s failed — %s", sym, exc)
                continue

        self._universe = sorted(coin_lookups.keys())
        logger.info(
            "BroadMarketFilter: %d coins in universe", len(self._universe)
        )

        if not coin_lookups:
            return

        # ── Phase 2: aggregate into daily bear percentage ──
        all_dates: Set[str] = set()
        for lk in coin_lookups.values():
            all_dates.update(lk.keys())

        for date_str in sorted(all_dates):
            directions = [
                coin_lookups[sym].get(date_str, "neutral")
                for sym in self._universe
                if date_str in coin_lookups[sym]
            ]
            total = len(directions)
            if total == 0:
                continue

            bearish_count = sum(1 for d in directions if d == "bearish")
            bullish_count = sum(1 for d in directions if d == "bullish")
            neutral_count = total - bearish_count - bullish_count
            bear_pct = bearish_count / total

            self._daily_stats[date_str] = {
                "total": total,
                "bearish": bearish_count,
                "bullish": bullish_count,
                "neutral": neutral_count,
                "bear_pct": bear_pct,
                "is_bear": bear_pct >= self.bear_threshold,
            }

        bear_days = sum(1 for v in self._daily_stats.values() if v["is_bear"])
        total_days = len(self._daily_stats)
        logger.info(
            "BroadMarketFilter: %d/%d days are bear (%.1f%%) "
            "— threshold %.0f%%",
            bear_days, total_days,
            bear_days / total_days * 100 if total_days else 0,
            self.bear_threshold * 100,
        )

    # ── Check ─────────────────────────────────────────────────────────────

    def check(
        self,
        date_str: str,
        *,
        direction: str = "bullish",
        symbol: str = "",
    ) -> RegimeVerdict:
        """Block bullish entries when broad market is in bear territory."""
        if direction != "bullish":
            return RegimeVerdict(blocked=False, filter_name=self.name)

        stats = self._daily_stats.get(date_str)
        if stats is None:
            return RegimeVerdict(blocked=False, filter_name=self.name)

        if stats["is_bear"]:
            return RegimeVerdict(
                blocked=True,
                reason=(
                    f"Broad market bear on {date_str}: "
                    f"{stats['bearish']}/{stats['total']} coins bearish "
                    f"({stats['bear_pct']:.0%} >= {self.bear_threshold:.0%})"
                ),
                filter_name=self.name,
                details=stats,
            )

        return RegimeVerdict(blocked=False, filter_name=self.name)

    def get_state(self, date_str: str) -> Dict:
        """Return full daily stats for diagnostics."""
        return self._daily_stats.get(date_str, {})
