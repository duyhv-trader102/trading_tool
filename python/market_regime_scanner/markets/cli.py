import sys
import argparse

from markets.manager import MarketManager
from markets.registry import MarketRegistry
from infra.signal_logger import SignalLogger

def main():
    parser = argparse.ArgumentParser(description="Central Market CLI")
    parser.add_argument("action", choices=["scan", "viz", "tpo", "log"], help="Action to perform")
    parser.add_argument("--market", type=str, help="Market type (e.g. COIN, VNSTOCK)")
    parser.add_argument("--symbol", type=str, help="Symbol to analyze/visualize")
    parser.add_argument("--all", action="store_true", help="Run action for all symbols in market (scan only)")
    parser.add_argument("--group", type=str, help="Symbol group (e.g. VN30, VN100)")
    parser.add_argument("--tick", type=float, help="Tick size for TPO")
    # Signal log options
    parser.add_argument("--date", type=str, help="Date for log view (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=7, help="Number of days for log history (default: 7)")
    parser.add_argument("--ready", action="store_true", help="Show only READY signals in log")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open report in browser")
    
    args = parser.parse_args()

    if args.action == "log":
        _handle_log(args)
        return

    if not args.market:
        print("Error: --market is required for scan/viz/tpo actions")
        return

    market = args.market.upper()
    if market not in MarketRegistry.list_markets():
        print(f"Error: Unknown market '{args.market}'. Available: {MarketRegistry.list_markets()}")
        return

    if args.action == "scan":
        MarketManager.run_scanner(market, symbol=args.symbol, run_all=args.all, group=args.group, auto_open=not args.no_open)
    elif args.action == "viz" or args.action == "tpo":
        # Merged viz/tpo to both run TPO visualization, as candlestick is removed
        if not args.symbol:
            print("Error: --symbol is required for visualization")
            return
        MarketManager.run_visualizer(market, args.symbol, viz_type="tpo", tick=args.tick)


def _handle_log(args):
    """Handle the 'log' action — view signal log history."""
    logger = SignalLogger()

    # If specific symbol requested → show symbol history
    if args.symbol:
        logger.print_symbol_history(args.symbol, market=args.market)
        return

    # If specific date requested → show that day
    if args.date:
        logger.print_date(args.date)
        return

    # If --ready → show only READY signals history
    if args.ready:
        logger.print_ready_history(last_n=args.days)
        return

    # Default: show summary history
    logger.print_history(last_n=args.days)

if __name__ == "__main__":
    main()
