"""
Top-Down TPO + Regime Dashboard (MT5 / Forex / Crypto)

Generates a multi-timeframe regime analysis dashboard for configured symbols.
Features:
- Auto-fetches missing data from MT5.
- Classification: Balance vs Imbalance.
- MBA Detection: Structural support/resistance.
- HTML Dashboard: Interactive charts saved to output/
"""
from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to sys.path if not present
root_path = str(Path(__file__).resolve().parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

# Core imports
from core.tpo import calc_block_size
from viz.tpo_visualizer import visualize_tpo_topdown
from workflow.pipeline import analyze_from_df
from data_providers import get_data
from analytic.tpo_mba.tracker import build_mba_context
from analytic.tpo_mba.detector import find_last_directional_move
from analytic.tpo_confluence.tpo_alignment import build_topdown_conclusion
from analytic.tpo_mba.alignment import build_tf_regime, evaluate_overall_signal
from markets.base.scanner import BaseScanner
from markets.base.data_provider import MT5DataProvider
from infra import mt5
from infra.parquet_manager import fetch_and_store_data, update_parquet
from infra.settings_loader import get_mt5_config
from universe.watchlist import get_tradeable_symbols

# Config imports
from scripts.mt5.config import (
    SYMBOLS,
    BINANCE_SYMBOLS_OBSERVER,
    VN30_SYMBOLS_OBSERVER,
    VN100_SYMBOLS_OBSERVER,
    TIMEFRAMES,
    TIMEFRAMES_MACRO,
    TIMEFRAMES_VN,
    FULL_SYMBOLS,
    MIN_BLOCKS,
    KEEP_SESSIONS,
    ANALYSIS_TARGET_ROWS,
    OUTPUT_DIR,
    TICK_SIZE_DEFAULTS,
    load_tick_cache,
    save_tick_cache,
)
from markets.sync import sync_vnstock_data, sync_vnstock_1h_data
from scripts.topdown_result import TimeframeResult, SymbolResult

# Setup Logger
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def connect_mt5() -> bool:
    """Connect to MT5 terminal using project settings."""
    try:
        config = get_mt5_config()
        mt5.start_mt5(
            username=int(config['username']),
            password=config['password'],
            server=config['server'],
            mt5Pathway=config['mt5Pathway']
        )
        return True
    except Exception as e:
        logger.error(f"Failed to connect to MT5: {e}")
        return False


# =============================================================================
# Data Management (Consolidated from data_prefetch.py)
# =============================================================================

def get_tick_size(symbol: str, mt5_connected: bool) -> float:
    """Return tick size from MT5 (if connected), cache, or fallback."""
    cache = load_tick_cache()
    if mt5_connected:
        try:
            ts = mt5.get_tick_size(symbol)
            cache[symbol] = ts
            save_tick_cache(cache)
            return ts
        except Exception:
            pass
    return cache.get(symbol, TICK_SIZE_DEFAULTS.get(symbol, 0.01))


def ensure_data(symbols: List[Dict], timeframes: Dict[str, Dict], skip_update: bool = False) -> bool:
    """
    Ensure all required parquet files are present and up-to-date.
    
    Behavior:
    - Missing files: always fetched from MT5.
    - Existing files: updated with latest bars from MT5 (unless skip_update=True).
    
    Args:
        symbols: List of symbol configs [{"symbol": ..., "has_weekend": ...}]
        timeframes: Timeframe config dict from config.py
        skip_update: If True, only fetch missing files (offline mode).
    
    Returns:
        True if MT5 connection was established.
    """
    needed: Dict[tuple, int] = {}
    for sym_cfg in symbols:
        symbol = sym_cfg["symbol"]
        for tf_cfg in timeframes.values():
            key = (symbol, tf_cfg["data_tf"])
            bars = tf_cfg["bars"]
            needed[key] = max(needed.get(key, 0), bars if bars is not None else 0)

    missing = []
    to_update = []

    # S3 is the source of truth for freshness
    from infra.s3_storage import s3_dir_mtimes
    s3_mt5 = s3_dir_mtimes("mt5")

    for (symbol, data_tf), bars in needed.items():
        fname = f"{symbol}_{data_tf}.parquet"
        fetch_bars = bars if bars > 0 else 5000
        if s3_mt5.get(fname) is None:
            missing.append((symbol, data_tf, fetch_bars))
        elif not skip_update:
            to_update.append((symbol, data_tf, min(fetch_bars, 500)))

    if not missing and not to_update:
        return False

    # Connect to MT5
    action = []
    if missing:
        action.append(f"{len(missing)} missing")
    if to_update:
        action.append(f"{len(to_update)} to update")
    print(f"\nData sync: {', '.join(action)}. Connecting to MT5 ...")
    connect_mt5()

    # Fetch missing files (full fetch)
    for symbol, data_tf, fetch_bars in missing:
        print(f"  [NEW] {symbol} {data_tf} ({fetch_bars} bars) ...", end=" ")
        try:
            fetch_and_store_data(symbol, data_tf, fetch_bars)
            print("OK")
        except Exception as exc:
            print(f"FAILED — {exc}")

    # Update existing files (incremental)
    for symbol, data_tf, fetch_bars in to_update:
        print(f"  [UPD] {symbol} {data_tf} ({fetch_bars} bars) ...", end=" ")
        try:
            update_parquet(symbol, data_tf, fetch_bars)
            print("OK")
        except Exception as exc:
            print(f"FAILED — {exc}")

    # Cache tick sizes while connected
    cache = load_tick_cache()
    for sym_cfg in symbols:
        try:
            cache[sym_cfg["symbol"]] = mt5.get_tick_size(sym_cfg["symbol"])
        except Exception:
            pass
    save_tick_cache(cache)
    return True


# =============================================================================
# Analysis Logic
# =============================================================================

def _find_nearest_imbalance_session(sessions: List) -> Optional[int]:
    """Find index of most recent imbalance session using detector."""
    imb = find_last_directional_move(sessions)
    if imb is None:
        return None
    return imb["index"]


def analyze_timeframe(symbol: str, tf_label: str, tf_cfg: Dict, has_weekend: bool) -> Optional[TimeframeResult]:
    """Analyze a single timeframe for TPO and MBA."""
    data_tf = tf_cfg["data_tf"]
    sess_type = tf_cfg["session_type"]
    bars = tf_cfg["bars"]
    target_rows = tf_cfg["target_rows"]
    min_block = MIN_BLOCKS.get(symbol, {}).get(tf_label)
    sat_sun = "Normal" if has_weekend else ("Normal" if data_tf == "W1" else "Ignore")
    policy_name = "247" if has_weekend else "mt5"

    # 1. Load Data
    df = get_data(symbol, data_tf, bars=bars, has_weekend=has_weekend)
    if df is None or len(df) == 0:
        return None

    # 2. Viz Pass (blocks for charting)
    all_viz, _ = analyze_from_df(df, sess_type, sat_sun, target_rows, min_block=min_block, policy_name=policy_name)
    if not all_viz:
        return None

    # 4. Analysis Pass (fine blocks for MBA)
    all_analysis, _ = analyze_from_df(df, sess_type, sat_sun, ANALYSIS_TARGET_ROWS, policy_name=policy_name)
    if not all_analysis or len(all_analysis) != len(all_viz):
        all_analysis = all_viz

    # 5. Dynamic Window Slicing (Focus from nearest Imbalance)
    fallback_keep = KEEP_SESSIONS.get(tf_label, 8)
    imb_idx = _find_nearest_imbalance_session(all_analysis)

    if imb_idx is not None:
        start_regime_idx = max(0, imb_idx - 1)
        max_sessions = fallback_keep * 4
        if len(all_analysis) - start_regime_idx > max_sessions:
            start_regime_idx = len(all_analysis) - max_sessions
    else:
        start_regime_idx = max(0, len(all_analysis) - fallback_keep)

    viz_results = all_viz[start_regime_idx:]

    # 6. Recalculate Block Size for Display
    kept_max_range = max(r.range for r in viz_results)
    kept_min_ib = min((r.ib_range for r in viz_results if r.ib_range > 0), default=None)
    block_size = calc_block_size(kept_max_range, target_rows, min_block, ib_range=kept_min_ib)

    # 7. Build MBA Metadata (using full history, new tracker workflow)
    closed_sessions = [s for s in all_analysis if s.is_closed]
    if not closed_sessions:
        # Fallback to empty context if no closed sessions (but keep last session for time)
        meta = MBAMetadata(symbol=symbol, timeframe=tf_label, last_session_time=all_analysis[-1].session_start)
    else:
        meta = build_mba_context(closed_sessions, symbol=symbol, timeframe=tf_label)

    # 8. Compute TFRegime (BREAKOUT/IN BALANCE/WAITING) for chart markers
    tf_regime = build_tf_regime(meta, all_analysis)

    # Use resample timeframe if present, otherwise use data_tf
    display_period = tf_cfg.get("resample") or data_tf

    return TimeframeResult(
        tf_label=tf_label,
        sessions=viz_results,
        period=display_period,
        block_size=block_size,
        regimes=[],          # regime classification removed
        meta=meta,
        session_offset=start_regime_idx,
        tf_regime=tf_regime,
    )


def analyze_symbol(
    symbol: str,
    has_weekend: bool,
    mt5_connected: bool,
    timeframes: Optional[Dict] = None,
    market: str = "MT5",
) -> SymbolResult:
    """Run top-down analysis for a symbol.

    Parameters
    ----------
    market : str
        ``"MT5"`` (default) or ``"BINANCE"``.
        When ``"BINANCE"`` the MT5 scanner branch is skipped entirely and
        the signal is computed directly from the local H4 parquet data.
    """
    if timeframes is None:
        # Always use TIMEFRAMES (M+W+D) for MT5 symbols (they all have H4 data)
        # TIMEFRAMES_MACRO is only for symbols without H4 data (e.g., vnstock)
        timeframes = TIMEFRAMES

    result = SymbolResult(
        symbol=symbol,
        has_weekend=has_weekend,
        tick_size=get_tick_size(symbol, mt5_connected),
    )

    for tf_label, tf_cfg in timeframes.items():
        tf_result = analyze_timeframe(symbol, tf_label, tf_cfg, has_weekend)
        if tf_result:
            result.timeframes[tf_label] = tf_result

    # Conclusion across timeframes (legacy)
    if result.tf_metas:
        result.conclusion = build_topdown_conclusion(result.tf_metas)

    # V3 signal: reuse scanner pipeline (native W1/D1 data, same params)
    # This guarantees identical signal with the market scanner.
    # For BINANCE symbols, always compute directly from local parquet data
    # (MT5 doesn't know Binance symbols like "BTC/USDT").
    if mt5_connected and market != "BINANCE":
        try:
            market_name = market or ("COIN" if has_weekend else "FX")
            provider = MT5DataProvider()
            scanner = BaseScanner(provider, market_name)
            scanner_result = scanner.analyze_symbol(symbol, print_report=False)
            if scanner_result:
                from analytic.tpo_mba.alignment import SignalResult
                raw_signal = scanner_result.get("signal", "")
                if raw_signal:
                    direction = None
                    if "BULLISH" in raw_signal.upper():
                        direction = "bullish"
                    elif "BEARISH" in raw_signal.upper():
                        direction = "bearish"
                    result.signal = SignalResult(
                        signal=raw_signal,
                        direction=direction,
                        path="scanner",
                    )
                else:
                    result.signal = SignalResult()
                # Store scanner regime details for display
                result._scanner_details = scanner_result
        except Exception as e:
            logger.warning(f"Scanner-compatible signal failed: {e}")
            # Fallback: compute from observer's own data
            result.signal = _compute_observer_signal(result)
    else:
        # No MT5 (or BINANCE market) → compute from observer's own H4-resampled data
        result.signal = _compute_observer_signal(result)

    return result


def _compute_observer_signal(result: SymbolResult) -> 'SignalResult':
    """Fallback: compute V3 signal from observer's H4-resampled data.

    Uses the pre-computed ``tf_regime`` from each TimeframeResult
    (built from *all_analysis* — full history) rather than re-computing
    from the windowed ``sessions`` list which may miss post-mother data.
    """
    from analytic.tpo_mba.alignment import SignalResult
    regime_m = None
    regime_w = None
    regime_d = None
    for tf_label in ["Monthly", "Weekly", "Daily"]:
        if tf_label in result.timeframes:
            tf_res = result.timeframes[tf_label]
            regime = tf_res.tf_regime if tf_res.tf_regime else build_tf_regime(tf_res.meta, tf_res.sessions)
            if tf_label == "Monthly":
                regime_m = regime
            elif tf_label == "Weekly":
                regime_w = regime
            else:
                regime_d = regime

    if regime_m and regime_w:
        return evaluate_overall_signal(regime_m, regime_w, regime_d)
    return SignalResult()


# =============================================================================
# Reporting & Output
# =============================================================================

def print_report(result: SymbolResult):
    print(f"\n{'=' * 70}")
    print(f"  {result.symbol}  (Tick: {result.tick_size})")
    print(f"{'=' * 70}")

    # ── V3 Signal Banner ──────────────────────────────────────────
    scanner_data = getattr(result, '_scanner_details', None)
    if result.signal and result.signal.signal:
        print(f"\n  *** SIGNAL: {result.signal.signal} ***")
    else:
        print(f"\n  --- NO SIGNAL ---")

    # ── Per-TF scanner detail (same as scanner report) ────────────
    if scanner_data:
        for p in ['monthly', 'weekly']:
            d = scanner_data.get(p, {})
            if not d:
                continue
            trend_display = (d.get('trend') or 'neutral').upper()
            if trend_display == 'CONFLICT':
                trend_display = 'CONFLICT'
            print(f"\n  [{d.get('period', p.upper())}]")
            print(f"    Status : {d.get('status', '?')}")
            print(f"    Trend  : {trend_display}")
            if d.get('range_low') is not None:
                print(f"    Range  : {d['range_low']:.5g} - {d['range_high']:.5g}")
                mother = d.get('mother_date', '?')
                cont = d.get('continuity', 0)
                print(f"    Mother : {mother} ({cont} bars)")
            print(f"    Ready  : {'YES' if d.get('is_ready') else 'NO'}")
            if d.get('is_ready'):
                print(f"      Reason : {d.get('ready_reason', '')}")
                if d.get('trigger_session_date'):
                    print(f"      Trigger: {d['trigger_session_date']}")

    # -- Per-TF TPO Sessions (observer's H4-resampled view) -------
    print(f"\n  {'-' * 50}")
    print(f"  TPO Sessions (H4 resampled)")
    print(f"  {'-' * 50}")
    for tf_label, tf in result.timeframes.items():
        print(f"\n  [{tf_label}] {len(tf.sessions)} sessions")
        for sess in tf.sessions[-3:]:
            dt = sess.session_start.strftime('%Y-%m-%d')
            st = sess.session_type.name if sess.session_type else "?"
            dist = sess.distribution_type or ""
            tr = sess.target_rows if sess.target_rows > 0 else '?'
            tpo_up = sess.tpo_counts_up
            tpo_dn = sess.tpo_counts_down
            print(f"    {dt}  {st} {dist}  POC={sess.poc:.5g}  VA={sess.val:.5g}-{sess.vah:.5g}  U{tpo_up}D{tpo_dn}  TR:{tr}")
        if tf.meta:
            print(f"    {tf.meta.summary_line(tf_regime=tf.tf_regime)}")
    print(f"  {'-' * 50}")


def save_dashboard(result: SymbolResult) -> Optional[str]:
    viz_data = result.viz_dict()
    if not viz_data:
        return None

    # Sanitize symbol name for use as a filename component
    # e.g. "BTC/USDT" → "BTC_USDT",  "BTC:USDT" → "BTC_USDT"
    safe_sym = result.symbol.replace("/", "_").replace(":", "_").replace("\\", "_")

    tf_count = len(result.timeframes)
    suffix = "topdown" if tf_count >= 3 else "macro"
    filename = str(OUTPUT_DIR / f"{safe_sym}_{suffix}.html")
    
    visualize_tpo_topdown(viz_data, target_rows=25, filename=filename, symbol=result.symbol)
    print(f"  Chart saved: {filename}")
    return filename if suffix == "topdown" else None


def run(
    symbols: Optional[List[Dict]] = None,
    skip_update: bool = False,
    market: str = "MT5",
    tiers: Optional[List[str]] = None,
) -> List[str]:
    """Main execution flow.

    Parameters
    ----------
    market : str
        ``"MT5"`` (default) — fetch/update via MT5, then analyze.
        ``"BINANCE"`` — use local H4 parquets only, no MT5 needed.
        ``"VNSTOCK"`` / ``"VN100"`` — use local D1+H1 parquets for VN stocks.

    Returns
    -------
    List[str]
        Paths of generated topdown HTML dashboards.
    """
    # ── Market-specific configuration ─────────────────────────────────────
    MARKET_CONFIGS = {
        "VNSTOCK": {
            "default_syms": VN30_SYMBOLS_OBSERVER,
            "label": "VN30", "has_weekend": False, "timeframes": TIMEFRAMES_VN,
            "market_tag": "VNSTOCK",
        },
        "VN100": {
            "default_syms": VN100_SYMBOLS_OBSERVER,
            "label": "VN100", "has_weekend": False, "timeframes": TIMEFRAMES_VN,
            "market_tag": "VNSTOCK",
        },
        "BINANCE": {
            "default_syms": BINANCE_SYMBOLS_OBSERVER,  # hardcoded fallback
            "label": "Binance", "has_weekend": True, "timeframes": TIMEFRAMES,
            "market_tag": "BINANCE",
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    topdown_files: List[str] = []

    if market in MARKET_CONFIGS:
        cfg = MARKET_CONFIGS[market]

        # ── Universe integration (Binance): load from backtest watchlist ──
        if symbols:
            syms = symbols
        elif market == "BINANCE":
            # Auto-load from universe/watchlist.json (backtest results);
            # falls back to hardcoded BINANCE_SYMBOLS_OBSERVER if missing
            universe_syms = get_tradeable_symbols(tiers=tiers)
            if universe_syms:
                syms = [{"symbol": s, "has_weekend": True} for s in universe_syms]
                tier_label = tiers or ["Tier 1", "Tier 2"]
                print(f"Loaded {len(syms)} symbols from universe watchlist (tiers: {tier_label})")
            else:
                print("Universe watchlist empty/missing → using hardcoded fallback list")
                syms = cfg["default_syms"]
        else:
            syms = cfg["default_syms"]
        print(f"Starting {cfg['label']} top-down analysis for {len(syms)} symbols...")

        # VNStock: sync D1 + H1 parquets before analysis
        if cfg["market_tag"] == "VNSTOCK":
            sym_names = [s["symbol"] for s in syms]
            sync_vnstock_data(sym_names)
            sync_vnstock_1h_data(sym_names)

        for sym_cfg in syms:
            res = analyze_symbol(
                sym_cfg["symbol"],
                has_weekend=cfg["has_weekend"],
                mt5_connected=False,
                timeframes=cfg["timeframes"],
                market=cfg["market_tag"],
            )
            print_report(res)
            path = save_dashboard(res)
            if path:
                topdown_files.append(path)

    else:  # MT5 (default)
        syms = symbols or SYMBOLS
        print(f"Starting MT5 analysis for {len(syms)} symbols...")
        mt5_connected = ensure_data(syms, TIMEFRAMES, skip_update=skip_update)
        for sym_cfg in syms:
            res = analyze_symbol(
                sym_cfg["symbol"],
                sym_cfg["has_weekend"],
                mt5_connected,
                market="MT5",
            )
            print_report(res)
            path = save_dashboard(res)
            if path:
                topdown_files.append(path)

    print(f"\nAll done. Output directory: {OUTPUT_DIR}")
    return topdown_files


import argparse

def main():
    parser = argparse.ArgumentParser(
        description="Top-Down TPO + Regime Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # MT5 symbols (default)
  python scripts/observer.py --symbol XAUUSDm
  python scripts/observer.py --all

  # Binance symbols (auto-loads from universe/watchlist.json backtest results)
  python scripts/observer.py --market binance
  python scripts/observer.py --market binance --tiers "Tier 1"     # Tier 1 only
  python scripts/observer.py --market binance --symbol BTC/USDT ETH/USDT SOL/USDT
  python scripts/observer.py --market binance --all                # hardcoded full list

  # VN stocks (local D1+H1 parquet, Daily via H1 bars)
  python scripts/observer.py --market vnstock              # VN30 (30 symbols)
  python scripts/observer.py --market vn100                # VN100 (42 symbols)
  python scripts/observer.py --market vnstock --symbol VNM FPT HPG
  python scripts/observer.py --market vn100 --all
""",
    )
    parser.add_argument("--symbol", "-s", nargs="+",
                        help="Symbols to analyze (e.g. XAUUSDm  or  BTC/USDT ETH/USDT)")
    parser.add_argument("--market", "-m", default="mt5",
                        choices=["mt5", "binance", "vnstock", "vn100"],
                        help="Data source: 'mt5' | 'binance' | 'vnstock' (VN30) | 'vn100' (VN100)")
    parser.add_argument("--has-weekend", "-w", action="store_true",
                        help="Force has_weekend=True (MT5 only; Binance always True)")
    parser.add_argument("--all", action="store_true",
                        help="Run all configured symbols for the chosen market")
    parser.add_argument("--no-update", action="store_true",
                        help="Skip MT5 data update (offline mode)")
    parser.add_argument("--no-open", action="store_true",
                        help="Don't auto-open topdown dashboards in browser")
    parser.add_argument("--tiers", nargs="+", default=None,
                        help="Binance tiers to include from universe (default: 'Tier 1' 'Tier 2')")

    args = parser.parse_args()
    market = args.market.upper()  # "MT5" or "BINANCE"

    run_symbols = []

    if args.symbol:
        if market == "BINANCE":
            # Binance symbols always have weekend data
            run_symbols = [{"symbol": s, "has_weekend": True} for s in args.symbol]
        elif market in ("VNSTOCK", "VN100"):
            run_symbols = [{"symbol": s, "has_weekend": False} for s in args.symbol]
        else:
            known_map = {s["symbol"]: s["has_weekend"] for s in SYMBOLS}
            for s in args.symbol:
                hw = known_map.get(s, args.has_weekend)
                run_symbols.append({"symbol": s, "has_weekend": hw})
    elif args.all:
        if market == "BINANCE":
            run_symbols = BINANCE_SYMBOLS_OBSERVER
        elif market == "VNSTOCK":
            run_symbols = VN30_SYMBOLS_OBSERVER
        elif market == "VN100":
            run_symbols = VN100_SYMBOLS_OBSERVER
        else:
            run_symbols = SYMBOLS
    # else: run() will use defaults for the chosen market

    topdown_files = run(
        run_symbols or None,
        skip_update=args.no_update,
        market=market,
        tiers=args.tiers,
    )

    if not args.no_open and topdown_files:
        import webbrowser
        for f in topdown_files:
            webbrowser.open(Path(f).as_uri())
        print(f"  Opened {len(topdown_files)} topdown dashboard(s) in browser (local).")


if __name__ == "__main__":
    main()
