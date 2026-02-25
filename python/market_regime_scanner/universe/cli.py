"""
universe.cli — Command-Line Interface
======================================

Usage::

    python -m universe.cli screen                    # full pipeline (~30 min)
    python -m universe.cli screen --no-backtest      # pre-screen only (fast)
    python -m universe.cli screen --force            # ignore cache, re-run all
    python -m universe.cli report                    # print last watchlist
    python -m universe.cli list                      # list Tier 1+2 symbols
    python -m universe.cli list --tier 1             # list Tier 1 only
"""

from __future__ import annotations

import argparse
import logging
import sys


def cmd_screen(args: argparse.Namespace) -> None:
    """Run the full universe screening pipeline."""
    from universe.config import UniverseConfig, PreScreenConfig, ScoringConfig
    from universe.screener import run_universe_screening

    cfg = UniverseConfig(
        use_backtest_cache=not args.force,
        force_refresh=args.force,
    )

    # Apply CLI overrides
    pre = cfg.pre_screen
    if args.min_volume is not None:
        pre.min_avg_volume_usdt = args.min_volume
    if args.min_history is not None:
        pre.min_history_days = args.min_history

    sc = cfg.scoring
    if args.min_pf is not None:
        sc.min_profit_factor = args.min_pf
    if args.min_years is not None:
        sc.min_data_years = args.min_years

    print("\n" + "=" * 60)
    print("  COIN UNIVERSE SCREENING")
    print("=" * 60)
    if not args.backtest:
        print("  Mode: pre-screen only (--no-backtest)")
    elif args.force:
        print("  Mode: full pipeline (cache ignored)")
    else:
        print("  Mode: full pipeline (cache enabled)")
    print()

    run_universe_screening(
        config=cfg,
        run_backtest=args.backtest,
        print_summary=True,
        output_path=args.output,
    )


def cmd_report(args: argparse.Namespace) -> None:
    """Print the last watchlist report."""
    from universe.watchlist import load_watchlist, print_watchlist_summary

    result = load_watchlist(args.path)
    if result is None:
        print("  No watchlist found. Run: python -m universe.cli screen")
        sys.exit(1)

    print_watchlist_summary(result)


def cmd_list(args: argparse.Namespace) -> None:
    """List symbols for selected tier(s)."""
    from universe.watchlist import get_tradeable_symbols, load_watchlist

    tier_map = {
        "1": "Tier 1",
        "2": "Tier 2",
        "3": "Tier 3",
        "all": None,
    }

    tier_arg = str(args.tier)
    if tier_arg == "all" or tier_arg is None:
        tiers = ["Tier 1", "Tier 2", "Tier 3"]
    else:
        label = tier_map.get(tier_arg)
        if label is None:
            print(f"  Unknown tier '{tier_arg}'. Use 1, 2, 3, or all.")
            sys.exit(1)
        tiers = [label]

    symbols = get_tradeable_symbols(args.path, tiers=tiers)
    if not symbols:
        print("  No symbols found. Run: python -m universe.cli screen")
        sys.exit(1)

    print(f"\n  {len(symbols)} symbols ({', '.join(tiers)}):")
    print("  " + ", ".join(symbols))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m universe.cli",
        description="Coin Universe Selection — build a quality-filtered Binance watchlist",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── screen ───────────────────────────────────────────────
    p_screen = sub.add_parser("screen", help="Run full screening pipeline")
    p_screen.add_argument(
        "--no-backtest", dest="backtest", action="store_false",
        help="Pre-screen only, skip backtest (fast)",
    )
    p_screen.add_argument(
        "--force", action="store_true",
        help="Ignore cache and re-run backtest from scratch",
    )
    p_screen.add_argument("--output", type=str, default=None, help="Override output path")
    p_screen.add_argument("--min-volume", type=float, default=None,
                          help="Min avg daily volume USDT (default 5_000_000)")
    p_screen.add_argument("--min-history", type=int, default=None,
                          help="Min history in days (default 365)")
    p_screen.add_argument("--min-pf", type=float, default=None,
                          help="Min profit factor (default 1.3)")
    p_screen.add_argument("--min-years", type=float, default=None,
                          help="Min data years for scoring (default 1.0)")

    # ── report ───────────────────────────────────────────────
    p_report = sub.add_parser("report", help="Print last saved watchlist")
    p_report.add_argument("--path", type=str, default=None, help="Watchlist JSON path")

    # ── list ──────────────────────────────────────────────────
    p_list = sub.add_parser("list", help="List symbols by tier")
    p_list.add_argument("--tier", type=str, default="all",
                        choices=["1", "2", "3", "all"],
                        help="Tier to list (default: all)")
    p_list.add_argument("--path", type=str, default=None, help="Watchlist JSON path")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    dispatch = {
        "screen": cmd_screen,
        "report": cmd_report,
        "list": cmd_list,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
