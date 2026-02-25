import logging
import os
import math
from typing import Optional, List, Dict, Any

from markets.registry import MarketRegistry
from markets.base.scanner import BaseScanner
from markets.base.viz_tpo_chart import BaseVizTPOChart
from markets.reporting import HTMLReporter
from infra.signal_logger import SignalLogger

logger = logging.getLogger("MarketManager")

class MarketManager:
    """
    Central manager to run any market scanner or visualizer.
    Delegates to specific MarketProviders/Scanners via Registry.
    """
    
    @staticmethod
    def get_scanner(market: str) -> BaseScanner:
        """Get a scanner instance for the specified market."""
        try:
            provider = MarketRegistry.get_provider(market)
            return BaseScanner(provider, market)
        except ValueError as e:
            logger.error(f"Failed to get scanner for {market}: {e}")
            raise

    @staticmethod
    def run_scanner(market: str, symbol: str = None, run_all: bool = False, group: str = None, auto_open: bool = True):
        """
        Run the market scanner.
        
        Args:
            market: Market identifier (COIN, VNSTOCK, etc.)
            symbol: Specific symbol to scan
            run_all: If True, scan all default symbols for the market
            group: Optional group name (e.g. VN30, VN100)
        """
        try:
            scanner = MarketManager.get_scanner(market)
        except Exception:
            return

        if run_all or group:
            symbols = MarketRegistry.get_symbols(market, group)
            if not symbols:
                print(f"No default symbols found for {market}")
                return
                
            print(f"Scanning {market} ({len(symbols)} symbols)...")
            results = []
            for sym in symbols:
                try:
                    # Ensure data is fresh
                    if scanner.provider.ensure_data(sym, "4h"):
                        res = scanner.analyze_symbol(sym, print_report=False)
                        if res: results.append(res)
                except Exception as e:
                    logger.error(f"Error scanning {sym}: {e}")
                    
            scanner.print_table(results)
            
            # Log signals persistently (dedup by date + market + symbol)
            sig_logger = SignalLogger()
            logged_count = sig_logger.log_scan_results(market, results)
            if logged_count:
                print(f"[+] Signal log: {logged_count} new/updated entries saved to {sig_logger.log_dir}")
            
            # Determine output directory
            market_dir = market.lower()
            output_dir = os.path.join("markets", market_dir, "output")
            os.makedirs(output_dir, exist_ok=True)

            # Auto-generate charts for READY symbols
            ready_symbols = [
                r['symbol'] for r in results
                if r.get('signal') and 'READY' in r['signal']
            ]
            chart_generated = set()
            if ready_symbols:
                print(f"\n[+] Generating charts for {len(ready_symbols)} READY symbols...")
                viz = BaseVizTPOChart(scanner.provider, market, output_dir)
                for sym in ready_symbols:
                    try:
                        viz.generate_tpo_chart(sym)
                        chart_generated.add(sym)
                        print(f"    \u2713 {sym}")
                    except Exception as e:
                        logger.error(f"Chart generation failed for {sym}: {e}")

            # Mark results that have charts (generated now or pre-existing)
            for r in results:
                sym = r['symbol']
                chart_file = sym.replace('/', '_').replace(':', '_') + '_TPO_TopDown.html'
                r['has_chart'] = (
                    sym in chart_generated
                    or os.path.exists(os.path.join(output_dir, chart_file))
                )

            # Generate HTML Report
            report_path = HTMLReporter.generate_report(market, results, output_dir)
            print(f"\n[+] HTML Report generated: {report_path}")

            if auto_open:
                import webbrowser
                webbrowser.open(f"file:///{os.path.abspath(report_path)}")
                print("  Opened in browser.")
            
        elif symbol:
            if scanner.provider.ensure_data(symbol, "4h"):
                scanner.analyze_symbol(symbol, print_report=True)
        else:
            print("Error: Must specify --symbol or --all")

    @staticmethod
    def run_visualizer(market: str, symbol: str, viz_type: str = "tpo", **kwargs):
        """
        Run a visualizer for a specific symbol.
        
        Args:
            market: Market identifier
            symbol: Symbol to visualize
            viz_type: 'tpo' (Candlestick removed)
            **kwargs: Additional arguments (tick, lookback, etc.)
        """
        try:
            scanner = MarketManager.get_scanner(market)
            # Ensure data is fresh
            if not scanner.provider.ensure_data(symbol, "4h"):
                logger.error(f"Cannot ensure data for {symbol}")
                return
        except Exception:
            return
        
        # Determine output directory based on market
        # Simple convention: market/[market_type]/output
        market_dir = market.lower()

        # Use project root relative path
        output_dir = os.path.join("markets", market_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
            
        print(f"Running {viz_type.upper()} Visualizer for {symbol}...")
        
        if viz_type == "tpo":
            # Default to BaseVizTPOChart or specific override if needed
            # For now, all markets use BaseVizTPOChart logic (or inherited class)
            # We can check if specific market has a specialized TPO viz class, 
            # otherwise use BaseVizTPOChart directly.
            
            # Dynamic import to check for market specific overrides?
            # Or just use BaseVizTPOChart for all since it's generic now.
            # To respect current structure, let's try to load market specific TPO viz if exists.
            
            viz = BaseVizTPOChart(scanner.provider, market, output_dir)
            viz.generate_tpo_chart(symbol, tick_size=kwargs.get('tick'))
        else:
            print(f"Unknown viz_type: {viz_type}")
