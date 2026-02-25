"""
universe.pre_screener — Fast Symbol Pre-screening
==================================================

Filters raw Binance symbol list (~400) down to quality candidates
(~100-150) based on data availability, volume, price, and history
BEFORE running the expensive backtest step.

Filters applied (in order):
    1. Skip known stablecoins / wrapped tokens (BINANCE_SKIP_SYMBOLS)
    2. Minimum listing history (days of parquet data)
    3. Minimum average daily volume in USDT
    4. Minimum last close price (reject dust tokens)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import polars as pl

from universe.config import PreScreenConfig

log = logging.getLogger(__name__)


# ── Result dataclass ──────────────────────────────────────────

@dataclass
class PreScreenResult:
    symbol: str
    passed: bool
    reject_reason: str = ""
    history_days: int = 0
    avg_volume_usdt: float = 0.0
    last_price: float = 0.0


# ── Main function ─────────────────────────────────────────────

def pre_screen_symbols(
    symbols: List[str],
    data_provider,                      # BinanceDataProvider instance
    config: PreScreenConfig | None = None,
    *,
    verbose: bool = False,
) -> List[PreScreenResult]:
    """
    Apply fast filters to a raw symbol list.

    Args:
        symbols:       Full list from BinanceDataProvider.get_all_symbols()
        data_provider: BinanceDataProvider (or any provider with .get_data())
        config:        PreScreenConfig — defaults if None
        verbose:       Print per-symbol result

    Returns:
        List[PreScreenResult] — all symbols, passed=True/False
    """
    from EA.macro_trend_catcher.config import BINANCE_SKIP_SYMBOLS

    cfg = config or PreScreenConfig()
    results: List[PreScreenResult] = []

    # Normalise: strip /USDT suffix for skip-set lookup
    def base(sym: str) -> str:
        return sym.replace("/USDT", "").replace("USDT", "").strip()

    for sym in symbols:
        # ── 1. Skip known bad symbols ──────────────────────────
        if base(sym) in BINANCE_SKIP_SYMBOLS:
            r = PreScreenResult(sym, False, "skip_list")
            results.append(r)
            if verbose:
                log.debug("%-15s  SKIP  %s", sym, "skip_list")
            continue

        # ── 2. Load D1 data (resampled from H4 storage) ────────
        try:
            df: Optional[pl.DataFrame] = data_provider.get_data(
                sym, timeframe="D1", bars=5000
            )
        except Exception as exc:
            r = PreScreenResult(sym, False, f"load_error: {exc}")
            results.append(r)
            continue

        if df is None or df.is_empty():
            r = PreScreenResult(sym, False, "no_data")
            results.append(r)
            if verbose:
                log.debug("%-15s  FAIL  no_data", sym)
            continue

        # ── 3. History length ──────────────────────────────────
        history_days = len(df)
        if history_days < cfg.min_history_days:
            r = PreScreenResult(
                sym, False,
                f"short_history ({history_days}d < {cfg.min_history_days}d)",
                history_days=history_days,
            )
            results.append(r)
            if verbose:
                log.debug("%-15s  FAIL  %s", sym, r.reject_reason)
            continue

        # ── 4. Average daily volume (USDT) ────────────────────
        # volume column is base asset volume; multiply by close for USDT
        has_volume = "volume" in df.columns
        has_close = "close" in df.columns

        if has_volume and has_close:
            # Use last 180 days for volume average
            recent = df.tail(180)
            avg_vol_usdt = float(
                (recent["volume"] * recent["close"]).mean()
            )
        else:
            avg_vol_usdt = 0.0

        if avg_vol_usdt < cfg.min_avg_volume_usdt:
            r = PreScreenResult(
                sym, False,
                f"low_volume (${avg_vol_usdt:,.0f} < ${cfg.min_avg_volume_usdt:,.0f})",
                history_days=history_days,
                avg_volume_usdt=avg_vol_usdt,
            )
            results.append(r)
            if verbose:
                log.debug("%-15s  FAIL  %s", sym, r.reject_reason)
            continue

        # ── 5. Last close price ────────────────────────────────
        last_price = float(df["close"][-1]) if has_close else 0.0
        if last_price < cfg.min_price_usdt:
            r = PreScreenResult(
                sym, False,
                f"dust_price (${last_price:.6f} < ${cfg.min_price_usdt})",
                history_days=history_days,
                avg_volume_usdt=avg_vol_usdt,
                last_price=last_price,
            )
            results.append(r)
            if verbose:
                log.debug("%-15s  FAIL  %s", sym, r.reject_reason)
            continue

        # ── PASS ───────────────────────────────────────────────
        r = PreScreenResult(
            sym, True,
            history_days=history_days,
            avg_volume_usdt=avg_vol_usdt,
            last_price=last_price,
        )
        results.append(r)
        if verbose:
            log.debug("%-15s  PASS  hist=%dd  vol=$%,.0f  price=$%.4f",
                      sym, history_days, avg_vol_usdt, last_price)

    passed = [r for r in results if r.passed]
    log.info("Pre-screen: %d / %d symbols passed", len(passed), len(results))

    # Cap to max_symbols (sort by volume desc)
    if len(passed) > cfg.max_symbols:
        passed_sorted = sorted(passed, key=lambda r: r.avg_volume_usdt, reverse=True)
        cut = passed_sorted[cfg.max_symbols:]
        for r in cut:
            r.passed = False
            r.reject_reason = f"universe_cap (top {cfg.max_symbols} by volume)"
        log.info("Capped universe to top %d by avg volume", cfg.max_symbols)

    return results
