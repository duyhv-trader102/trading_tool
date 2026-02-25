"""
markets/daily_scan.py — Daily scan entry point.

Scans all configured markets, syncs data, and generates a combined
HTML dashboard.

Usage:
    python -m markets.daily_scan                          # all markets
    python -m markets.daily_scan --markets FX COMM        # specific markets
    python -m markets.daily_scan --no-charts              # skip chart gen
    python -m markets.daily_scan --skip-update            # skip data refresh
    python -m markets.daily_scan --open                   # open dashboard after scan
    python -m markets.daily_scan --universe-only          # BINANCE: use watchlist only
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# ── project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from markets.registry import MarketRegistry
from markets.manager import MarketManager
from markets.base.scanner import BaseScanner
from markets.sync import sync_mt5_data, sync_vnstock_data, sync_binance_data
from markets.reporting import DashboardReporter
from markets.base.viz_tpo_chart import BaseVizTPOChart
from markets.utils.constants import WEEKEND_MARKETS, MARKET_META, DEFAULT_MARKETS
from infra.signal_logger import SignalLogger
from infra.signal_diff import SignalDiff

logging.basicConfig(level=logging.WARNING, format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s")
logger = logging.getLogger("DailyScan")

# ── Market configuration ──────────────────────────────────────────────────────

# Default output directory (relative to project root)
DEFAULT_OUTPUT = "markets/output/daily"

# ── Parallelism configuration ─────────────────────────────────────────────────
MAX_WORKERS_SYMBOLS = 4   # parallel symbol analysis (ProcessPool, CPU-bound TPO)


# ── Core scan logic ───────────────────────────────────────────────────────────

# ── Helpers for parallel symbol analysis ──────────────────────────────────────

def _analyze_one_symbol(
    sym: str,
    market: str,
) -> Dict[str, Any] | None:
    """Process-safe wrapper: analyse a single symbol.

    Each worker process creates its own scanner + data provider so there
    is no shared mutable state.
    """
    try:
        from markets.manager import MarketManager as _MM
        scanner = _MM.get_scanner(market)
        if not scanner.provider.ensure_data(sym, "4h"):
            return None
        res = scanner.analyze_symbol(sym, print_report=False)
        if res:
            res["market"] = market
        return res
    except Exception as exc:
        return None


def scan_market(
    market: str,
    output_dir: Path,
    generate_charts: bool,
    universe_symbols: List[str] | None = None,
    max_workers: int = MAX_WORKERS_SYMBOLS,
) -> List[Dict[str, Any]]:
    """Scan one market; return list of result dicts (each tagged with 'market').

    Symbol analysis is parallelised across *max_workers* processes (ProcessPoolExecutor — CPU-bound TPO).
    """
    if universe_symbols is not None and market == "BINANCE":
        symbols = universe_symbols
        print(f"  [UNIVERSE] Using {len(symbols)} coins from watchlist")
    else:
        symbols = MarketRegistry.get_symbols(market)
    if not symbols:
        print(f"  [SKIP] {market}: no symbols configured")
        return []

    meta = MARKET_META.get(market, {"label": market, "color": "#d4d4d4"})
    print(f"\n{'-'*60}")
    print(f"  {meta['label']} ({len(symbols)} symbols)")
    print(f"{'-'*60}")

    try:
        scanner = MarketManager.get_scanner(market)
    except Exception as e:
        print(f"  [ERROR] Cannot create scanner for {market}: {e}")
        return []

    # ── Parallel symbol analysis (process pool — CPU-bound TPO) ─────────────
    results: List[Dict[str, Any]] = []
    t0 = time.perf_counter()

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_analyze_one_symbol, sym, market): sym
            for sym in symbols
        }
        for future in as_completed(future_map):
            sym = future_map[future]
            try:
                res = future.result()
                if res is None:
                    print(f"  {sym:<14}  [skip]")
                    continue
                results.append(res)
                sig = res.get("signal") or "-"
                print(f"  {sym:<14}  {sig}{' *' if 'READY' in sig else ''}")
            except Exception as exc:
                logger.warning("%s future error: %s", sym, exc)

    elapsed = time.perf_counter() - t0
    print(f"  [{meta['label']}] {len(results)} symbols analysed in {elapsed:.1f}s")

    # ── Per-market output directory ───────────────────────────────────────────
    market_dir = output_dir / market.lower()
    market_dir.mkdir(parents=True, exist_ok=True)

    # ── TPO charts for READY symbols ──────────────────────────────────────────
    chart_generated: set = set()
    chart_urls: dict = {}   # sym -> presigned S3 URL (when S3 is available)
    if generate_charts:
        ready = [r["symbol"] for r in results if r.get("signal") and "READY" in r["signal"]]
        if ready:
            print(f"\n  Generating charts for {len(ready)} READY symbol(s)...")
            viz = BaseVizTPOChart(scanner.provider, market, str(market_dir))
            for sym in ready:
                try:
                    url = viz.generate_tpo_chart(sym)
                    chart_generated.add(sym)
                    if url:
                        chart_urls[sym] = url
                    print(f"    [ok] {sym}")
                except Exception as e:
                    logger.warning("Chart failed %s: %s", sym, e)

    for r in results:
        sym = r["symbol"]
        chart_file = sym.replace("/", "_").replace(":", "_") + "_TPO_TopDown.html"
        r["has_chart"] = sym in chart_generated or (market_dir / chart_file).exists()
        if sym in chart_urls:
            r["chart_url"] = chart_urls[sym]

    # NOTE: SignalLogger is called AFTER all markets complete (in main)
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Daily scan — all markets, single HTML dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--markets", nargs="+", default=DEFAULT_MARKETS, metavar="MKT",
                   help=f"Markets to scan (default: {' '.join(DEFAULT_MARKETS)})")
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT, metavar="DIR",
                   help=f"Base output directory (default: {DEFAULT_OUTPUT})")
    p.add_argument("--no-charts", action="store_true", help="Skip TPO chart generation for READY symbols")
    p.add_argument("--skip-update", action="store_true", help="Skip data refresh (use existing parquet files)")
    p.add_argument("--no-open", action="store_true", help="Don't auto-open dashboard in browser")
    p.add_argument(
        "--universe-only", action="store_true",
        help="BINANCE: scan only coins in universe/watchlist.json. "
             "Run 'python -m universe.cli screen' first to build the watchlist.",
    )
    p.add_argument(
        "--tiers", nargs="+",
        default=["Tier 1", "Tier 2", "Tier 3", "Tier 4"],
        metavar="TIER",
        help="Watchlist tiers to include with --universe-only "
             "(default: all 4 tiers). Example: --tiers 'Tier 1' 'Tier 2'",
    )
    p.add_argument(
        "--workers", type=int, default=MAX_WORKERS_SYMBOLS, metavar="N",
        help=f"Max parallel workers per market (default: {MAX_WORKERS_SYMBOLS})",
    )
    return p.parse_args()


def main():
    args    = parse_args()
    markets = [m.upper() for m in args.markets]

    today_str   = datetime.now().strftime("%Y-%m-%d")
    base_dir    = ROOT / args.output_dir / today_str
    base_dir.mkdir(parents=True, exist_ok=True)
    report_path = base_dir / "dashboard.html"

    print(f"\n{'='*60}")
    print(f"  Daily Scan - {today_str}")
    print(f"  Markets : {', '.join(markets)}")
    print(f"  Output  : {base_dir}")
    print(f"{'='*60}")

    t_total = time.perf_counter()

    # ── Phase 1: Data sync (sequential per source) ───────────────────────────
    if not args.skip_update:
        sync_mt5_data(markets, skip_update=False)

        if "VNSTOCK" in markets:
            vn_symbols = MarketRegistry.get_symbols("VNSTOCK", group="VN100")
            sync_vnstock_data(vn_symbols)

        if "VN30" in markets and "VNSTOCK" not in markets:
            vn30_symbols = MarketRegistry.get_symbols("VN30")
            sync_vnstock_data(vn30_symbols)

        if "BINANCE" in markets:
            from markets.binance.config import DEFAULT_SYMBOLS as BINANCE_SYMBOLS
            sync_binance_data(BINANCE_SYMBOLS)

        print(f"\n  Data sync done ({time.perf_counter() - t_total:.1f}s)")
    else:
        print("\n  Skipping data refresh (--skip-update)")

    # ── Load universe watchlist (for --universe-only) ────────────────────────
    universe_symbols: List[str] | None = None
    if args.universe_only and "BINANCE" in markets:
        try:
            from universe.watchlist import get_tradeable_symbols
            tiers = args.tiers
            universe_symbols = get_tradeable_symbols(tiers=tiers)
            if universe_symbols:
                tier_str = "+".join(t.replace("Tier ", "T") for t in tiers)
                print(f"\n  Universe watchlist loaded: {len(universe_symbols)} coins ({tier_str})")
            else:
                print("\n  [WARN] Watchlist empty — run: python -m universe.cli screen")
                print("  Falling back to full Binance symbol list.")
        except Exception as exc:
            logger.warning("Could not load universe watchlist: %s", exc)

    # ── Phase 2: Market scanning (sequential markets, parallel symbols) ──────
    # Markets run one-by-one; within each market, symbol TPO analysis is
    # parallelised via ProcessPool (CPU-bound work bypasses the GIL).
    valid_markets = [m for m in markets if m in MarketRegistry.list_markets()]
    invalid = set(markets) - set(valid_markets)
    for m in invalid:
        print(f"\n  [WARN] Unknown market '{m}', skipping")

    all_results: List[Dict] = []
    t_scan = time.perf_counter()

    for market in valid_markets:
        all_results.extend(
            scan_market(
                market, base_dir,
                generate_charts=not args.no_charts,
                universe_symbols=universe_symbols if market == "BINANCE" else None,
                max_workers=args.workers,
            )
        )

    scan_time = time.perf_counter() - t_scan
    print(f"\n  All markets scanned in {scan_time:.1f}s")

    if not all_results:
        print("\n[!] No results — check data availability.")
        return

    # ── Phase 3: Signal logging (sequential — shared file) ───────────────────
    sig_logger = SignalLogger()
    markets_in_results = {r["market"] for r in all_results}
    for mkt in markets_in_results:
        mkt_results = [r for r in all_results if r["market"] == mkt]
        sig_logger.log_scan_results(mkt, mkt_results)

    # ── Phase 3b: Signal diff (new / gone / flipped vs previous day) ─────────
    diff = SignalDiff(sig_logger)
    diff_report = diff.compare(today_str)
    diff.print_diff(diff_report)

    # ── Summary ───────────────────────────────────────────────────────────────
    ready = [r for r in all_results if r.get("signal") and "READY" in r["signal"]]
    total_time = time.perf_counter() - t_total
    print(f"\n{'='*60}")
    print(f"  Scan complete: {len(all_results)} symbols, {len(ready)} READY  ({total_time:.1f}s total)")
    if ready:
        print()
        for r in sorted(ready, key=lambda x: x["market"]):
            mkt  = r["market"]
            meta = MARKET_META.get(mkt, {"label": mkt, "color": ""})
            print(f"    *  {r['symbol']:<14}  [{meta['label']}]  {r['signal']}")

    # ── Dashboard ─────────────────────────────────────────────────────────────
    path = DashboardReporter.generate_dashboard(all_results, markets, report_path, MARKET_META, diff_report=diff_report)
    print(f"\n  Dashboard -> {path}")
    print(f"{'='*60}\n")

    # ── Backup output to S3 (archive, same tree structure) ───────────────────
    from infra.s3_storage import backup_report_dir
    n_uploaded = backup_report_dir(base_dir)
    if n_uploaded:
        print(f"  S3 backup: {n_uploaded} files uploaded")

    if not args.no_open:
        import webbrowser
        webbrowser.open(path.as_uri())
        print("  Opened in browser.")


if __name__ == "__main__":
    main()
