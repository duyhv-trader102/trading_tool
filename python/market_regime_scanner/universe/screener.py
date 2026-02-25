"""
universe.screener — Universe Screening Orchestrator
=====================================================

Runs the full 3-stage pipeline:

    Stage 1 — Pre-screen  : volume / history / price filters
    Stage 2 — Backtest    : EA signals on D1 historical data
    Stage 3 — Score       : reuse EA/shared/market_filter scoring engine

Results are cached so repeated runs don't re-run the expensive backtest.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional

from universe.config import (
    UniverseConfig,
    BACKTEST_CACHE_FILE,
    PRE_SCREEN_CACHE_FILE,
)
from universe.pre_screener import pre_screen_symbols
from universe.backtester import run_batch_backtest
from universe.watchlist import (
    WatchlistResult, WatchlistSymbol,
    save_watchlist, print_watchlist_summary,
)

log = logging.getLogger(__name__)


def run_universe_screening(
    symbols: Optional[List[str]] = None,
    config: Optional[UniverseConfig] = None,
    *,
    run_backtest: bool = True,
    print_summary: bool = True,
    output_path: Optional[str] = None,
) -> WatchlistResult:
    """
    Full universe screening pipeline.

    Args:
        symbols:       Override symbol list.  None = auto-load from BinanceDataProvider.
        config:        UniverseConfig — uses defaults if None.
        run_backtest:  False = pre-screen only (fast, no scoring).
        print_summary: Print result table to stdout.
        output_path:   Override watchlist.json destination.

    Returns:
        WatchlistResult — also written to watchlist.json.
    """
    # ── Import lazily to avoid circular issues ─────────────────
    from markets.binance.data_provider import BinanceDataProvider
    from EA.shared.market_filter import FilterConfig, score_symbols

    cfg = config or UniverseConfig()
    provider = BinanceDataProvider()

    # ── Stage 0: Load symbol universe ─────────────────────────
    if symbols is None:
        print("  Loading Binance symbol list...")
        symbols = provider.get_all_symbols()
        print(f"  Found {len(symbols)} symbols in local data store")

    total_screened = len(symbols)

    # ── Stage 1: Pre-screen ────────────────────────────────────
    print("\n  [Stage 1] Pre-screening...")
    pre_results = pre_screen_symbols(
        symbols, provider, cfg.pre_screen, verbose=False,
    )

    # Cache pre-screen results
    try:
        with open(PRE_SCREEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "symbol": r.symbol,
                        "passed": r.passed,
                        "reject_reason": r.reject_reason,
                        "history_days": r.history_days,
                        "avg_volume_usdt": r.avg_volume_usdt,
                        "last_price": r.last_price,
                    }
                    for r in pre_results
                ],
                f, indent=2,
            )
    except Exception as exc:
        log.warning("Could not save pre-screen cache: %s", exc)

    passed_symbols = [r.symbol for r in pre_results if r.passed]
    print(f"  Pre-screen: {len(passed_symbols)} / {total_screened} passed")

    if not run_backtest:
        # Return early with pre-screen only result
        result = WatchlistResult(
            generated_at=datetime.now().isoformat(),
            total_screened=total_screened,
            total_pre_screen_passed=len(passed_symbols),
            total_backtest_ran=0,
            total_passed=0,
        )
        save_watchlist(result, output_path)
        if print_summary:
            print_watchlist_summary(result)
        return result

    # ── Stage 2: Backtest ──────────────────────────────────────
    use_cache = cfg.use_backtest_cache and not cfg.force_refresh

    backtest_results = None
    if use_cache and BACKTEST_CACHE_FILE.exists():
        print(f"\n  [Stage 2] Loading cached backtest results from {BACKTEST_CACHE_FILE}...")
        try:
            with open(BACKTEST_CACHE_FILE) as f:
                backtest_results = json.load(f)
            print(f"  Loaded {len(backtest_results)} cached results")
        except Exception as exc:
            log.warning("Cache read failed, re-running backtest: %s", exc)
            backtest_results = None

    if backtest_results is None:
        print(f"\n  [Stage 2] Running backtest on {len(passed_symbols)} symbols...")
        print("  (This may take 15-45 minutes depending on universe size)")
        backtest_results = run_batch_backtest(
            passed_symbols,
            cfg.backtest,
            progress=True,
        )

        # Cache raw results
        try:
            with open(BACKTEST_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(backtest_results, f, indent=2)
            print(f"  Backtest results cached -> {BACKTEST_CACHE_FILE}")
        except Exception as exc:
            log.warning("Could not save backtest cache: %s", exc)

    total_backtest_ran = len(backtest_results)

    # ── Stage 3: Score & Tier ──────────────────────────────────
    print("\n  [Stage 3] Scoring and tiering...")
    sc = cfg.scoring
    filter_config = FilterConfig(
        min_trades=sc.min_trades,
        min_data_years=sc.min_data_years,
        min_profit_factor=sc.min_profit_factor,
        max_drawdown_limit=sc.max_drawdown_limit,
        tier1_min_score=sc.tier1_min_score,
        tier2_min_score=sc.tier2_min_score,
        tier3_min_score=sc.tier3_min_score,
    )

    # ── Normalise backtest_results for scoring ─────────────────
    # Problem: coins with 1-2 trades, all wins → PF = hundreds of thousands.
    # This creates extreme outliers that distort range-based normalisation,
    # making all multi-trade coins score near 0 on the PF dimension.
    # Solution: cap PF at a "clearly excellent" ceiling (10).
    _PF_CAP = 10.0
    _WR_CAP = 1.0  # win_rate from backtester is already 0-1; market_filter needs 0-1
    scored_inputs = []
    for r in backtest_results:
        if r.get("error") and r["error"] not in ("", "no_trades"):
            continue
        row = dict(r)
        row["profit_factor"] = min(row.get("profit_factor", 0.0), _PF_CAP)
        # win_rate sanity: already 0-1 from backtester.py (divided by 100)
        row["win_rate"] = min(row.get("win_rate", 0.0), _WR_CAP)
        scored_inputs.append(row)

    scored = score_symbols(scored_inputs, filter_config)

    # ── Build WatchlistResult ──────────────────────────────────
    tradeable = [s for s in scored if s.tier in ("Tier 1", "Tier 2", "Tier 3")]

    # Tier 4 = Rejected coins with ≥ 1 trade (had EA signal, not enough quality)
    tier4 = [
        s for s in scored
        if s.tier == "Rejected" and s.trades >= 1
    ]

    wl_symbols = [
        WatchlistSymbol(
            symbol=s.symbol,
            tier=s.tier,
            score=round(s.composite_score, 1),
            return_pct=round(s.total_return, 1),
            return_per_year=round(s.return_per_year, 1),
            profit_factor=round(s.profit_factor, 2),
            sharpe_ratio=round(s.sharpe_ratio, 2),
            win_rate=round(s.win_rate, 4),
            trades=s.trades,
            max_drawdown=round(s.max_drawdown, 1),
            data_years=round(s.data_years, 1),
            avg_duration_days=round(s.avg_duration, 1),
        )
        for s in tradeable
    ] + [
        WatchlistSymbol(
            symbol=s.symbol,
            tier="Tier 4",
            score=round(s.composite_score, 1),
            return_pct=round(s.total_return, 1),
            return_per_year=round(s.return_per_year, 1),
            profit_factor=round(s.profit_factor, 2),
            sharpe_ratio=round(s.sharpe_ratio, 2),
            win_rate=round(s.win_rate, 4),
            trades=s.trades,
            max_drawdown=round(s.max_drawdown, 1),
            data_years=round(s.data_years, 1),
            avg_duration_days=round(s.avg_duration, 1),
        )
        for s in tier4
    ]

    result = WatchlistResult(
        generated_at=datetime.now().isoformat(),
        total_screened=total_screened,
        total_pre_screen_passed=len(passed_symbols),
        total_backtest_ran=total_backtest_ran,
        total_passed=len(tradeable),
        tiers={
            "tier_1": [s.symbol for s in tradeable if s.tier == "Tier 1"],
            "tier_2": [s.symbol for s in tradeable if s.tier == "Tier 2"],
            "tier_3": [s.symbol for s in tradeable if s.tier == "Tier 3"],
            "tier_4": [s.symbol for s in tier4],
        },
        symbols=wl_symbols,
    )

    saved_path = save_watchlist(result, output_path)
    print(f"\n  Watchlist written -> {saved_path}")

    if print_summary:
        print_watchlist_summary(result)

    return result
