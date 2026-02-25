"""
universe.backtester — Thin Backtest Wrapper
============================================

Wraps ``EA.macro_trend_catcher.backtest.run_single_backtest()``
to produce the result dict format expected by
``EA.shared.market_filter.score_symbols()``.

Design:
    - Does NOT duplicate backtest logic — calls EA engine directly
    - Normalises the ``SpotBacktestResult`` → plain dict for scoring
    - Adds a simple progress reporter (no external deps)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from universe.config import BacktestConfig

log = logging.getLogger(__name__)

# Fee identical to EA default (0.1% per side → 0.2% round-trip)
_DEFAULT_FEE = 0.001


def run_batch_backtest(
    symbols: List[str],
    config: BacktestConfig | None = None,
    *,
    progress: bool = True,
) -> List[Dict[str, Any]]:
    """
    Run backtest for every symbol and return a list of result dicts
    compatible with ``EA.shared.market_filter.score_symbols()``.

    Args:
        symbols:   Pre-screened symbol list (e.g. "BTC/USDT").
        config:    BacktestConfig — uses defaults if None.
        progress:  Print live progress to stdout.

    Returns:
        List of dicts, one per symbol, with keys:
        ``symbol, trades, win_rate, total_return, max_drawdown,
          profit_factor, sharpe_ratio, data_years, avg_duration, error``
    """
    from EA.macro_trend_catcher.backtest import run_single_backtest
    from EA.macro_trend_catcher.config import BINANCE_SPOT_V2

    cfg = config or BacktestConfig()
    results: List[Dict[str, Any]] = []
    n = len(symbols)
    t0 = time.time()

    for idx, raw_sym in enumerate(symbols, 1):
        # Normalise BTC/USDT → BTC  (EA expects bare base asset)
        sym = raw_sym.replace("/USDT", "").replace("USDT", "").strip()

        if progress:
            elapsed = time.time() - t0
            eta = (elapsed / idx) * (n - idx) if idx > 1 else 0
            print(
                f"\r  [{idx:>3}/{n}]  {sym:<12}  "
                f"elapsed {elapsed:>5.0f}s  ETA {eta:>5.0f}s",
                end="", flush=True,
            )

        try:
            res = run_single_backtest(
                symbol=sym,
                config=BINANCE_SPOT_V2,
                fee_rate=_DEFAULT_FEE,
                signal_version="v3",
                market="binance",
                has_weekend=True,
                allow_short=False,
                require_compression=cfg.require_compression,
                soft_sl=cfg.use_soft_sl,
            )

            row: Dict[str, Any] = {
                "symbol": raw_sym,
                "trades": res.total_trades,
                "win_rate": res.win_rate / 100.0,   # market_filter expects 0-1
                "total_return": res.net_return,
                "max_drawdown": res.max_drawdown,
                "profit_factor": res.profit_factor,
                "sharpe_ratio": res.sharpe_ratio,
                "data_years": res.data_years,
                "avg_duration": res.avg_duration,
                "error": res.error,
            }
        except Exception as exc:
            log.error("Backtest failed for %s: %s", sym, exc)
            row = {
                "symbol": raw_sym,
                "trades": 0,
                "win_rate": 0.0,
                "total_return": 0.0,
                "max_drawdown": 100.0,
                "profit_factor": 0.0,
                "sharpe_ratio": 0.0,
                "data_years": 0.0,
                "avg_duration": 0.0,
                "error": str(exc)[:200],
            }

        results.append(row)
        log.debug("%-12s  trades=%d  ret=%.1f%%  pf=%.2f  err=%s",
                  sym, row["trades"], row["total_return"],
                  row["profit_factor"], row["error"])

    if progress:
        print()  # newline after progress bar

    total_time = time.time() - t0
    passed = sum(1 for r in results if not r["error"])
    log.info("Backtest done: %d symbols in %.0fs  (%d ok, %d error)",
             n, total_time, passed, n - passed)

    return results
