"""
Signal Performance Tracker -- price-focused insight dashboard.

Tracks READY signals against actual price movement:
  - PnL% (entry price -> current price)
  - Direction validation (is price moving as predicted?)
  - Daily / Weekly price changes
  - Price position within MBA range
  - Compact regime status badges

First run  : Analyse all READY signals, save snapshot with entry price.
Next runs  : Load saved snapshot, show PnL from locked-in entry price.

Snapshot storage: markets/logs/tracker/YYYY-MM-DD.csv

Usage:
    python -m markets.pnl_tracker                         # today, all markets
    python -m markets.pnl_tracker --date 2026-02-23       # specific date
    python -m markets.pnl_tracker --markets BINANCE FX    # filter markets
    python -m markets.pnl_tracker --no-open               # skip browser open
    python -m markets.pnl_tracker --reset                 # rebuild snapshot
"""

import argparse
import csv
import logging
import sys
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project root is on sys.path when run as a script
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import polars as pl

from infra.signal_logger import SignalLogger
from markets.manager import MarketManager
from markets.utils.constants import WEEKEND_MARKETS, MARKET_ORDER, MARKET_META
from markets.utils.formatters import fmt_price as _p, fmt_pct as _pct, compact_regime as _compact_regime, sorted_markets as _sorted_markets
from markets.utils.html_helpers import (
    change_cell as _change_cell,
    range_bar_html as _range_bar_html,
    trend_badge_cls as _trend_badge_cls,
    build_trade_history_html as _build_trade_history_html,
    dashboard_css as _dashboard_css,
    dashboard_js as _dashboard_js,
)
from analytic.tpo_mba.alignment import build_tf_regime
from data_providers import get_data as _dp_get_data

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

SNAPSHOT_DIR = Path("markets/logs/tracker")

TRADE_COLUMNS = [
    "market", "symbol", "direction", "signal",
    "entry_date", "entry_price",
    "exit_date", "exit_price", "exit_signal",
    "pnl_pct", "days_held",
    "closed_at",
]

SNAP_COLUMNS = [
    "market", "symbol", "signal", "scanned_at", "snapshot_at", "entry_price",
    # Tracking fields (updated each run)
    "last_price", "last_pnl_pct", "last_tracked_at",
    # Monthly (frozen at signal time)
    "m_status", "m_trend", "m_range_low", "m_range_high",
    "m_is_ready", "m_ready_direction",
    # Weekly (frozen at signal time)
    "w_status", "w_trend", "w_range_low", "w_range_high",
    "w_is_ready", "w_ready_direction",
    # Daily (frozen at signal time)
    "d_status", "d_trend", "d_range_low", "d_range_high",
    "d_is_ready", "d_ready_direction",
]


# ── Snapshot persistence ─────────────────────────────────────────



def _snap_path(date_str: str) -> Path:
    return SNAPSHOT_DIR / f"{date_str}.csv"


def load_snapshot(date_str: str) -> Dict[str, Dict]:
    path = _snap_path(date_str)

    def _read(p: Path) -> Dict[str, Dict]:
        result: Dict[str, Dict] = {}
        with open(p, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                for col in ("entry_price", "last_price", "last_pnl_pct",
                            "m_range_low", "m_range_high",
                            "w_range_low", "w_range_high",
                            "d_range_low", "d_range_high"):
                    v = row.get(col)
                    row[col] = float(v) if v not in ("", "None", None) else None
                for col in ("m_is_ready", "w_is_ready", "d_is_ready"):
                    row[col] = str(row.get(col, "")).lower() in ("true", "1", "yes")
                for col in ("m_ready_direction", "w_ready_direction", "d_ready_direction"):
                    if row.get(col) in ("", "None"):
                        row[col] = None
                key = f"{row['market']}:{row['symbol']}"
                result[key] = dict(row)
        return result

    if path.exists():
        return _read(path)
    try:
        from infra.s3_storage import download_read_clean
        return download_read_clean(path, _read) or {}
    except Exception:
        return {}


def save_snapshot(date_str: str, data: Dict[str, Dict]):
    path = _snap_path(date_str)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SNAP_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for entry in data.values():
            writer.writerow(entry)
    # Sync to S3 then remove local copy
    try:
        from infra.s3_storage import upload_and_clean
        upload_and_clean(path)
    except Exception:
        pass


# ── Trade history persistence ─────────────────────────────────────

def _trade_history_path() -> Path:
    return SNAPSHOT_DIR / "trade_history.csv"


def load_trade_history() -> List[Dict]:
    """Load all closed trades from persistent history."""
    path = _trade_history_path()

    def _read(p: Path) -> List[Dict]:
        trades: List[Dict] = []
        with open(p, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                for col in ("entry_price", "exit_price", "pnl_pct"):
                    v = row.get(col)
                    row[col] = float(v) if v not in ("", "None", None) else None
                for col in ("days_held",):
                    v = row.get(col)
                    try:
                        row[col] = int(v) if v not in ("", "None", None) else None
                    except (ValueError, TypeError):
                        row[col] = None
                trades.append(dict(row))
        return trades

    if path.exists():
        return _read(path)
    try:
        from infra.s3_storage import download_read_clean
        return download_read_clean(path, _read) or []
    except Exception:
        return []


def save_closed_trades(rows: List[Dict]):
    """Append newly closed trades to persistent trade_history.csv.

    Deduplicates by (market, symbol, entry_date, exit_date).
    """
    if not rows:
        return
    path = _trade_history_path()
    existing = load_trade_history()
    existing_keys = {
        (t["market"], t["symbol"], t.get("entry_date", ""), t.get("exit_date", ""))
        for t in existing
    }

    new_trades = []
    for r in rows:
        key = (r["market"], r["symbol"], r.get("entry_date", ""), r.get("exit_date", ""))
        if key not in existing_keys:
            new_trades.append(r)
            existing_keys.add(key)

    if not new_trades:
        return

    # Full rewrite (existing + new) so the local file is self-contained
    all_trades = existing + new_trades
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for t in all_trades:
            writer.writerow(t)
    logger.info("Trade history: %d new closed trade(s) appended", len(new_trades))
    # Sync to S3 then remove local copy
    try:
        from infra.s3_storage import upload_and_clean
        upload_and_clean(path)
    except Exception:
        pass


# ── Realtime price fetching ───────────────────────────────────────

def _fetch_mt5_prices(symbols: List[str]) -> Dict[str, float]:
    """Batch-fetch current prices from MT5 terminal via symbol_info_tick."""
    prices: Dict[str, float] = {}
    try:
        import MetaTrader5 as mt5
        from data_providers import get_provider
        prov = get_provider(auto_connect=True)
        # Ensure MT5 is connected
        mt5_prov = prov._get_mt5() if hasattr(prov, '_get_mt5') else None
        if mt5_prov is None or not mt5_prov.is_connected():
            logger.warning("MT5 not connected - skip realtime prices")
            return prices
        for sym in symbols:
            tick = mt5.symbol_info_tick(sym)
            if tick is not None:
                # Use last price if available (for CFD/stocks), else bid
                p = tick.last if tick.last > 0 else tick.bid
                if p and p > 0:
                    prices[sym] = float(p)
    except Exception as e:
        logger.warning("MT5 realtime price fetch failed: %s", e)
    return prices


def _fetch_binance_prices(symbols: List[str]) -> Dict[str, float]:
    """Batch-fetch current prices from Binance via ccxt."""
    prices: Dict[str, float] = {}
    if not symbols:
        return prices
    try:
        import ccxt
        exchange = ccxt.binance({'enableRateLimit': True})
        # Convert parquet-style symbols (BTC_USDT) to ccxt-style (BTC/USDT)
        sym_map = {}
        for s in symbols:
            ccxt_sym = s.replace("_", "/")
            sym_map[ccxt_sym] = s
        # fetch_tickers is efficient (single API call for all)
        tickers = exchange.fetch_tickers(list(sym_map.keys()))
        for ccxt_sym, orig_sym in sym_map.items():
            t = tickers.get(ccxt_sym)
            if t and t.get('last'):
                prices[orig_sym] = float(t['last'])
    except Exception as e:
        logger.warning("Binance realtime price fetch failed: %s", e)
    return prices


def _fetch_vnstock_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch current prices from VNStock via price_board API."""
    prices: Dict[str, float] = {}
    if not symbols:
        return prices
    try:
        from vnstock import Vnstock
        # Use a single client, batch all symbols in one call
        stock = Vnstock().stock(symbol=symbols[0], source='VCI')
        df = stock.trading.price_board(symbols_list=symbols)
        if df is None or df.empty:
            return prices
        # DataFrame has MultiIndex columns: ('match', 'match_price'), ('listing', 'symbol')
        cols = df.columns
        # Find symbol and match_price columns
        sym_col = None
        price_col = None
        for c in cols:
            if isinstance(c, tuple):
                if c == ('listing', 'symbol'):
                    sym_col = c
                elif c == ('match', 'match_price'):
                    price_col = c
            else:
                if c == 'symbol':
                    sym_col = c
                elif c == 'match_price':
                    price_col = c
        if sym_col is None or price_col is None:
            logger.warning("VNStock price_board: could not find symbol/price columns")
            return prices
        for _, row in df.iterrows():
            sym = row[sym_col]
            val = row[price_col]
            if sym and val and float(val) > 0:
                # price_board returns raw VND; historical data uses 1000-VND units
                prices[str(sym)] = float(val) / 1000.0
    except Exception as e:
        logger.warning("VNStock realtime price fetch failed: %s", e)
    return prices


def fetch_realtime_prices(signals: List[Dict]) -> Dict[str, float]:
    """Fetch realtime prices for all symbols, keyed by MARKET:SYMBOL.

    Returns dict mapping 'MARKET:SYMBOL' -> price.
    """
    by_market: Dict[str, List[str]] = {}
    for s in signals:
        by_market.setdefault(s["market"], []).append(s["symbol"])
    for m in by_market:
        by_market[m] = list(dict.fromkeys(by_market[m]))  # dedup

    result: Dict[str, float] = {}

    # MT5 markets
    mt5_syms = []
    for mkt in ("FX", "COMM", "US_STOCK", "COIN"):
        mt5_syms.extend(by_market.get(mkt, []))
    if mt5_syms:
        print(f"  Fetching realtime prices: MT5 ({len(mt5_syms)} symbols) ...")
        mt5_prices = _fetch_mt5_prices(mt5_syms)
        for mkt in ("FX", "COMM", "US_STOCK", "COIN"):
            for sym in by_market.get(mkt, []):
                if sym in mt5_prices:
                    result[f"{mkt}:{sym}"] = mt5_prices[sym]

    # Binance
    bn_syms = by_market.get("BINANCE", [])
    if bn_syms:
        print(f"  Fetching realtime prices: Binance ({len(bn_syms)} symbols) ...")
        bn_prices = _fetch_binance_prices(bn_syms)
        for sym in bn_syms:
            if sym in bn_prices:
                result[f"BINANCE:{sym}"] = bn_prices[sym]

    # VNStock / VN30
    vn_syms = by_market.get("VNSTOCK", []) + by_market.get("VN30", [])
    vn_syms = list(dict.fromkeys(vn_syms))  # dedup
    if vn_syms:
        print(f"  Fetching realtime prices: VNStock ({len(vn_syms)} symbols) ...")
        vn_prices = _fetch_vnstock_prices(vn_syms)
        for mkt in ("VNSTOCK", "VN30"):
            for sym in by_market.get(mkt, []):
                if sym in vn_prices:
                    result[f"{mkt}:{sym}"] = vn_prices[sym]

    print(f"  Realtime prices: {len(result)}/{sum(len(v) for v in by_market.values())} fetched")
    return result


# ── Signal lifecycle: detect superseded signals ──────────────────

def _find_exit_info(signals: List[Dict], signal_date: str) -> Dict[str, Dict]:
    """Scan signal logs AFTER *signal_date* to find direction flips.

    A signal is "exited" only when the same MARKET:SYMBOL gets a READY
    signal in the **opposite direction** on a later date.
    Same-direction re-signals are ignored (still profitable → keep tracking).

    Uses the aggregate file (``signals_all.csv``) for O(1) file-open
    instead of opening every daily CSV.  Falls back to per-file scan
    if the aggregate hasn't been built yet.

    Returns dict keyed by "MARKET:SYMBOL" -> {
        "exit_date": "YYYY-MM-DD",
        "exit_signal": "READY (BULLISH)" / ...,
        "exit_reason": "direction_flipped",
    }
    Only contains entries for signals whose direction has FLIPPED.
    """
    sig_logger = SignalLogger()

    # Build lookup: which keys are we tracking + their direction
    tracked_keys: Dict[str, str] = {}  # key -> original signal
    for s in signals:
        key = f"{s['market']}:{s['symbol']}"
        tracked_keys[key] = s.get("signal", "")

    exits: Dict[str, Dict] = {}

    # ── Fast path: use aggregate file ────────────────────────────
    agg_by_date = sig_logger.load_aggregate_by_date()
    if agg_by_date:
        future_dates = sorted(d for d in agg_by_date if d > signal_date)
        for future_d in future_dates:
            day_data = agg_by_date[future_d]
            _scan_day_for_exits(day_data, tracked_keys, exits, future_d)
            if len(exits) >= len(tracked_keys):
                break
        return exits

    # ── Fallback: per-file scan (slow, pre-aggregate) ────────────
    all_dates = sig_logger.list_dates()
    future_dates = [d for d in all_dates if d > signal_date]
    if not future_dates:
        return {}

    for future_d in future_dates:
        day_data = sig_logger.get_date(future_d)
        _scan_day_for_exits(day_data, tracked_keys, exits, future_d)
        if len(exits) >= len(tracked_keys):
            break

    return exits


def _scan_day_for_exits(day_data: Dict[str, Dict],
                        tracked_keys: Dict[str, str],
                        exits: Dict[str, Dict],
                        future_d: str):
    """Check one day's signal data for direction flips.  Mutates *exits*."""
    for key, entry in day_data.items():
        if key not in tracked_keys:
            continue
        if key in exits:
            continue

        new_sig = entry.get("signal", "")
        if not new_sig or not new_sig.startswith("READY"):
            continue

        old_sig = tracked_keys[key]

        old_bull = "BULLISH" in old_sig
        new_bull = "BULLISH" in new_sig
        old_bear = "BEARISH" in old_sig
        new_bear = "BEARISH" in new_sig

        if (old_bull and new_bear) or (old_bear and new_bull):
            exits[key] = {
                "exit_date": future_d,
                "exit_signal": new_sig,
                "exit_reason": "direction_flipped",
            }


def _get_price_at_date(symbol: str, market: str, target_date: str) -> Optional[float]:
    """D1 close at or before *target_date*."""
    has_weekend = market in WEEKEND_MARKETS
    df = _dp_get_data(symbol, "D1", has_weekend=has_weekend)
    if df is None or df.is_empty():
        return None
    try:
        target = date.fromisoformat(target_date)
    except (ValueError, TypeError):
        return None
    filtered = df.filter(pl.col("time").dt.date() <= target)
    if filtered.is_empty():
        return None
    return float(filtered[-1, "close"])


# ── Price helpers ────────────────────────────────────────────────

def _get_entry_price(symbol: str, market: str, scanned_at: str) -> Optional[float]:
    """D1 close at or before signal date -> entry price."""
    has_weekend = market in WEEKEND_MARKETS
    df = _dp_get_data(symbol, "D1", has_weekend=has_weekend)
    if df is None or df.is_empty():
        return None
    try:
        target = datetime.fromisoformat(scanned_at).date()
    except (ValueError, TypeError):
        return float(df[-1, "close"])
    filtered = df.filter(pl.col("time").dt.date() <= target)
    if filtered.is_empty():
        return float(df[0, "close"])
    return float(filtered[-1, "close"])


def _get_price_context(symbol: str, market: str,
                       realtime_price: Optional[float] = None) -> Dict:
    """Price context: realtime (or D1-close fallback) + recent changes."""
    has_weekend = market in WEEKEND_MARKETS
    df = _dp_get_data(symbol, "D1", has_weekend=has_weekend)
    if df is None or df.is_empty():
        ctx: Dict = {}
        if realtime_price is not None:
            ctx["current_price"] = realtime_price
        return ctx
    closes = df["close"].to_list()
    n = len(closes)
    last_d1 = float(closes[-1])
    # Prefer realtime price, fallback to last D1 close
    cur = realtime_price if realtime_price is not None else last_d1
    ctx = {"current_price": cur, "last_d1_close": last_d1}
    # Intraday change vs last D1 close (meaningful when using realtime)
    if realtime_price is not None and last_d1 > 0:
        ctx["intraday_pct"] = (realtime_price - last_d1) / last_d1 * 100
    if n >= 2:
        prev = float(closes[-2])
        ctx["d1_change_pct"] = (cur - prev) / prev * 100 if prev else None
    if n >= 6:
        ref = float(closes[-6])
        ctx["w_change_pct"] = (cur - ref) / ref * 100 if ref else None
    if n >= 22:
        ref = float(closes[-22])
        ctx["m_change_pct"] = (cur - ref) / ref * 100 if ref else None
    return ctx


# ── Analysis ─────────────────────────────────────────────────────

def analyze_symbol_full(symbol: str, market: str) -> dict:
    """Run fresh M / W / D analysis -> flat dict for snapshot."""
    scanner = MarketManager.get_scanner(market)
    result: dict = {"market": market, "symbol": symbol}

    # VNSTOCK / VN30 only have D1 parquets → skip Daily (needs H4)
    periods = [("1M", "m"), ("1W", "w")]
    if market not in ("VNSTOCK", "VN30"):
        periods.append(("1D", "d"))

    for period, prefix in periods:
        try:
            meta, sess, _closed = scanner.analyze_timeframe(symbol, period)
            regime = build_tf_regime(meta, sess)
            label = {"m": "MONTHLY", "w": "WEEKLY", "d": "DAILY"}[prefix]
            details = scanner.get_regime_details(meta, regime, label, sess)
            result[f"{prefix}_status"] = details.get("status", "")
            result[f"{prefix}_trend"] = details.get("trend", "")
            result[f"{prefix}_range_low"] = details.get("range_low")
            result[f"{prefix}_range_high"] = details.get("range_high")
            result[f"{prefix}_is_ready"] = details.get("is_ready", False)
            result[f"{prefix}_ready_direction"] = details.get("ready_direction")
        except Exception:
            result[f"{prefix}_status"] = "NO DATA"
            result[f"{prefix}_trend"] = "neutral"
            result[f"{prefix}_range_low"] = None
            result[f"{prefix}_range_high"] = None
            result[f"{prefix}_is_ready"] = False
            result[f"{prefix}_ready_direction"] = None
    return result


# ── Core: build snapshot + rows ──────────────────────────────────

def build_tracker_data(signals: List[Dict], date_str: str,
                       realtime_prices: Optional[Dict[str, float]] = None,
                       exit_info: Optional[Dict[str, Dict]] = None,
                       existing_snapshot: Optional[Dict[str, Dict]] = None) -> tuple:
    existing_snap = existing_snapshot if existing_snapshot is not None else load_snapshot(date_str)
    snapshot = dict(existing_snap)
    is_first_run = len(existing_snap) == 0

    # When starting a new day (first run), load the most recent prior snapshot
    # so that entry prices and frozen regime data carry forward for positions
    # that had the SAME signal on the prior day (avoiding a daily price reset).
    prior_snap: Dict = {}
    if is_first_run:
        from datetime import date as _date_t, timedelta as _td
        for lookback in range(1, 8):  # look back up to 7 trading days
            prior_date = (_date_t.fromisoformat(date_str) - _td(days=lookback)).isoformat()
            candidate = load_snapshot(prior_date)
            if candidate:
                prior_snap = candidate
                break

    rows: List[Dict] = []
    total = len(signals)
    now_iso = datetime.now().isoformat()
    rt_prices = realtime_prices or {}
    exits = exit_info or {}

    for i, s in enumerate(signals, 1):
        sym = s["symbol"]
        mkt = s["market"]
        key = f"{mkt}:{sym}"
        scanned_at = s.get("scanned_at", "")
        print(f"  [{i}/{total}] {mkt}:{sym} ...", end="\r")

        # Fresh regime
        current = analyze_symbol_full(sym, mkt)
        # Price context (realtime preferred, D1 close fallback)
        rt_price = rt_prices.get(key)
        price_ctx = _get_price_context(sym, mkt, realtime_price=rt_price)
        current_price = price_ctx.get("current_price")

        if is_first_run or key not in existing_snap:
            # Check if this position was already tracked in the prior day's snapshot
            # with the SAME signal → carry forward frozen entry data.
            prior = prior_snap.get(key) if prior_snap else None
            if prior and prior.get("signal") == s.get("signal", ""):
                snap = prior
                entry_price = prior.get("entry_price")
                snapshot[key] = dict(prior)  # base is prior frozen data
            else:
                entry_price = _get_entry_price(sym, mkt, scanned_at)
                current["signal"] = s.get("signal", "")
                current["scanned_at"] = scanned_at
                current["snapshot_at"] = now_iso
                current["entry_price"] = entry_price
                snapshot[key] = current
                snap = current
        else:
            # Snapshot is FROZEN at signal time — never overwrite regime.
            # Only update tracking fields (last_price, last_pnl_pct).
            snap = existing_snap[key]
            entry_price = snap.get("entry_price")

        # Exit info: if this signal was superseded by a newer one
        key_exit = exits.get(key)
        exit_ctx: Dict = {}
        if key_exit:
            exit_date = key_exit["exit_date"]
            exit_price = _get_price_at_date(sym, mkt, exit_date)
            exit_ctx = {
                "exit_date": exit_date,
                "exit_signal": key_exit.get("exit_signal", ""),
                "exit_reason": key_exit.get("exit_reason", ""),
                "exit_price": exit_price,
            }
            # For closed signals: override current_price with exit price
            if exit_price is not None:
                current_price = exit_price
                price_ctx["current_price"] = exit_price

        rows.append(_build_row(snap, current, s, entry_price, current_price,
                               price_ctx, exit_ctx))

        # Update tracking fields in snapshot (price + pnl at each run)
        snap_entry = snapshot[key]
        snap_entry["last_price"] = current_price
        snap_entry["last_tracked_at"] = now_iso
        if entry_price and current_price and entry_price != 0:
            snap_entry["last_pnl_pct"] = (current_price - entry_price) / entry_price * 100
        else:
            snap_entry["last_pnl_pct"] = None

    print(" " * 60, end="\r")
    save_snapshot(date_str, snapshot)
    return snapshot, rows


def _build_row(snap, current, signal, entry_price, current_price, price_ctx,
               exit_ctx: Optional[Dict] = None) -> dict:
    sig = signal.get("signal", "")
    is_bullish = "BULLISH" in sig
    is_bearish = "BEARISH" in sig

    # Exit status
    is_closed = bool(exit_ctx and exit_ctx.get("exit_date"))

    # PnL
    pnl_pct = None
    direction_match = None
    if entry_price and current_price and entry_price != 0:
        pnl_pct = (current_price - entry_price) / entry_price * 100
        if is_bullish:
            direction_match = pnl_pct >= 0
        elif is_bearish:
            direction_match = pnl_pct <= 0

    # W-range position (0-100, can exceed bounds)
    w_range_pos = None
    w_lo = current.get("w_range_low")
    w_hi = current.get("w_range_high")
    if current_price is not None and w_lo is not None and w_hi is not None:
        span = w_hi - w_lo
        if span > 0:
            w_range_pos = (current_price - w_lo) / span * 100

    # Days since signal
    days_active = None
    scanned = snap.get("scanned_at") or signal.get("scanned_at")
    if scanned:
        try:
            sig_date = datetime.fromisoformat(scanned).date()
            if is_closed:
                # Days = signal date -> exit date
                exit_d = date.fromisoformat(exit_ctx["exit_date"])
                days_active = (exit_d - sig_date).days
            else:
                days_active = (date.today() - sig_date).days
        except (ValueError, TypeError):
            pass

    row: dict = {
        "symbol": signal.get("symbol", ""),
        "market": signal.get("market", ""),
        "signal": sig,
        "scanned_at": snap.get("scanned_at") or signal.get("scanned_at", ""),
        "entry_price": entry_price,
        "current_price": current_price,
        "pnl_pct": pnl_pct,
        "direction_match": direction_match,
        "intraday_pct": price_ctx.get("intraday_pct"),
        "d1_change_pct": price_ctx.get("d1_change_pct"),
        "w_change_pct": price_ctx.get("w_change_pct"),
        "m_change_pct": price_ctx.get("m_change_pct"),
        "w_range_pos": w_range_pos,
        "w_range_low": w_lo,
        "w_range_high": w_hi,
        "days_active": days_active,
        "is_realtime": price_ctx.get("intraday_pct") is not None,
        # Exit info
        "is_closed": is_closed,
        "exit_date": exit_ctx.get("exit_date") if exit_ctx else None,
        "exit_signal": exit_ctx.get("exit_signal") if exit_ctx else None,
        "exit_reason": exit_ctx.get("exit_reason") if exit_ctx else None,
    }

    for prefix in ("m", "w", "d"):
        status = current.get(f"{prefix}_status", "")
        trend = current.get(f"{prefix}_trend", "")
        is_ready = current.get(f"{prefix}_is_ready", False)
        snap_status = snap.get(f"{prefix}_status", "")
        snap_trend = snap.get(f"{prefix}_trend", "")
        row[f"{prefix}_regime"] = _compact_regime(status, trend, is_ready)
        row[f"{prefix}_trend"] = trend
        row[f"{prefix}_changed"] = (status != snap_status or trend != snap_trend)

    return row


def _build_closed_trade_records(rows: List[Dict]) -> List[Dict]:
    """Build trade-history records from closed (flipped) rows."""
    records = []
    now_iso = datetime.now().isoformat()
    for r in rows:
        if not r.get("is_closed"):
            continue
        scanned = r.get("scanned_at", "")
        try:
            entry_date = datetime.fromisoformat(scanned).date().isoformat()
        except (ValueError, TypeError):
            entry_date = ""
        direction = "LONG" if "BULLISH" in r.get("signal", "") else "SHORT"
        records.append({
            "market": r["market"],
            "symbol": r["symbol"],
            "direction": direction,
            "signal": r.get("signal", ""),
            "entry_date": entry_date,
            "entry_price": r.get("entry_price"),
            "exit_date": r.get("exit_date", ""),
            "exit_price": r.get("current_price"),  # current_price = exit_price for closed
            "exit_signal": r.get("exit_signal", ""),
            "pnl_pct": r.get("pnl_pct"),
            "days_held": r.get("days_active"),
            "closed_at": now_iso,
        })
    return records


# ── Terminal report ──────────────────────────────────────────────

def print_terminal_report(rows: List[Dict], scan_dates: List[str], is_first: bool,
                          trade_history: Optional[List[Dict]] = None):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    dates_str = ", ".join(scan_dates)

    active_rows = [r for r in rows if not r.get("is_closed")]
    closed_rows = [r for r in rows if r.get("is_closed")]

    with_pnl = [r for r in rows if r["pnl_pct"] is not None]
    winning = sum(1 for r in with_pnl if r.get("direction_match"))
    losing = len(with_pnl) - winning
    avg_pnl = sum(abs(r["pnl_pct"]) * (1 if r.get("direction_match") else -1)
                  for r in with_pnl) / len(with_pnl) if with_pnl else 0

    hdr = f"  SIGNAL PERFORMANCE TRACKER - Signals from {dates_str}"
    print(f"\n{'='*145}")
    print(hdr)
    print(f"  Checked at: {now_str}")
    if is_first:
        print(f"  ** First run -- snapshot saved as baseline **")
    print(f"{'='*145}")
    status_str = f"  {len(rows)} signals ({len(active_rows)} active, {len(closed_rows)} closed)"
    status_str += f" | {winning} winning | {losing} losing | Avg dir-PnL: {_pct(avg_pnl)}"
    print(status_str)
    print(f"{'='*145}")

    by_market: Dict[str, List[Dict]] = {}
    for r in rows:
        by_market.setdefault(r["market"], []).append(r)

    col = (f"  {'SYMBOL':<17} {'SIGNAL':<18}"
           f" {'ENTRY':>12} {'CURRENT':>12} {'PnL%':>9}"
           f" {'Today':>8} {'1W%':>8}"
           f" {'W-Range':>8}"
           f" {'M':>4} {'W':>4} {'D':>4}"
           f" {'Days':>4}")

    rt_count = sum(1 for r in rows if r.get("is_realtime"))
    if rt_count:
        print(f"  (Realtime prices for {rt_count}/{len(rows)} symbols)")

    for mkt in _sorted_markets(rows):
        items = by_market[mkt]
        meta = MARKET_META.get(mkt, {"label": mkt})
        mkt_win = sum(1 for r in items if r.get("direction_match"))
        mkt_closed = sum(1 for r in items if r.get("is_closed"))
        closed_note = f", {mkt_closed} closed" if mkt_closed else ""
        print(f"\n  [{meta['label']}] ({len(items)} signals, {mkt_win} winning{closed_note})")
        print(col)
        print(f"  {'-'*143}")

        for r in items:
            dm = ""
            if r["direction_match"] is True:
                dm = " ok"
            elif r["direction_match"] is False:
                dm = " !!"

            rng = "-"
            if r["w_range_pos"] is not None:
                rng = f"{r['w_range_pos']:.0f}%"

            days = str(r["days_active"]) if r["days_active"] is not None else "-"

            regime_changed = any(r.get(f"{p}_changed") for p in ("m", "w", "d"))
            tag = " *" if regime_changed else ""
            rt_tag = " RT" if r.get("is_realtime") else ""

            # Closed signal tag
            if r.get("is_closed"):
                exit_d = r.get("exit_date", "")
                rt_tag = f" CLOSED({exit_d})"

            # "Today" = intraday if realtime, else d1_change
            today_pct = r.get("intraday_pct") if r.get("is_realtime") else r.get("d1_change_pct")

            print(
                f"  {r['symbol']:<17} {r['signal']:<18}"
                f" {_p(r['entry_price']):>12} {_p(r['current_price']):>12}"
                f" {_pct(r['pnl_pct']):>8}{dm:<3}"
                f" {_pct(today_pct):>8}"
                f" {_pct(r.get('w_change_pct')):>8}"
                f" {rng:>8}"
                f" {r.get('m_regime',''):>4} {r.get('w_regime',''):>4} {r.get('d_regime',''):>4}"
                f" {days:>4}{tag}{rt_tag}"
            )

    print(f"\n{'='*145}")

    # ── Trade History Summary ────────────────────────────────────
    trades = trade_history or []
    if trades:
        t_with_pnl = [t for t in trades if t.get("pnl_pct") is not None]
        t_wins = [t for t in t_with_pnl
                  if (t["direction"] == "LONG" and t["pnl_pct"] >= 0)
                  or (t["direction"] == "SHORT" and t["pnl_pct"] <= 0)]
        t_losses = [t for t in t_with_pnl if t not in t_wins]
        t_wr = len(t_wins) / len(t_with_pnl) * 100 if t_with_pnl else 0
        t_avg = sum(abs(t["pnl_pct"]) * (1 if t in t_wins else -1)
                    for t in t_with_pnl) / len(t_with_pnl) if t_with_pnl else 0

        print(f"\n  TRADE HISTORY ({len(trades)} closed trades | "
              f"{len(t_wins)}W {len(t_losses)}L | "
              f"WR: {t_wr:.0f}% | Avg PnL: {_pct(t_avg)})")
        print(f"  {'SYMBOL':<17} {'DIR':<6} {'ENTRY DATE':<12} {'EXIT DATE':<12}"
              f" {'ENTRY':>12} {'EXIT':>12} {'PnL%':>9} {'DAYS':>5}")
        print(f"  {'-'*95}")
        for t in trades[-20:]:  # Show last 20
            d = t.get("direction", "?")
            pnl = t.get("pnl_pct")
            is_win = (d == "LONG" and pnl is not None and pnl >= 0) or \
                     (d == "SHORT" and pnl is not None and pnl <= 0)
            tag = " ok" if is_win else " !!" if pnl is not None else ""
            days = str(t.get("days_held", "-")) if t.get("days_held") is not None else "-"
            print(f"  {t.get('symbol',''):<17} {d:<6} {t.get('entry_date',''):<12} "
                  f"{t.get('exit_date',''):<12}"
                  f" {_p(t.get('entry_price')):>12} {_p(t.get('exit_price')):>12}"
                  f" {_pct(pnl):>8}{tag} {days:>5}")
        if len(trades) > 20:
            print(f"  ... and {len(trades) - 20} more trades")

    print()


# ── HTML Dashboard ───────────────────────────────────────────────

def generate_dashboard(
    rows: List[Dict],
    scan_dates: List[str],
    output_path: str,
    is_first: bool,
    trade_history: Optional[List[Dict]] = None,
) -> Path:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    dates_str = ", ".join(scan_dates)

    with_pnl = [r for r in rows if r["pnl_pct"] is not None]
    winning = sum(1 for r in with_pnl if r.get("direction_match"))
    losing = len(with_pnl) - winning
    win_pct = winning / len(with_pnl) * 100 if with_pnl else 0
    avg_pnl = (sum(abs(r["pnl_pct"]) * (1 if r.get("direction_match") else -1)
                   for r in with_pnl) / len(with_pnl)) if with_pnl else 0

    active_count = sum(1 for r in rows if not r.get("is_closed"))
    closed_count = sum(1 for r in rows if r.get("is_closed"))

    by_market: Dict[str, List[Dict]] = {}
    for r in rows:
        by_market.setdefault(r["market"], []).append(r)

    # ── Market summary cards ──
    market_cards = ""
    for mkt in _sorted_markets(rows):
        items = by_market[mkt]
        meta = MARKET_META.get(mkt, {"label": mkt, "color": "#d4d4d4"})
        mw = sum(1 for r in items if r.get("direction_match"))
        ml = sum(1 for r in items if r.get("direction_match") is False)
        market_cards += f"""
        <div class="summary-card" data-market="{mkt}" onclick="filterTable('{mkt}')">
            <div class="card-label" style="color:{meta['color']}">{meta['label']}</div>
            <div class="card-value">{len(items)}</div>
            <div class="card-sub"><span class="win">{mw}W</span> / <span class="lose">{ml}L</span></div>
        </div>"""

    # ── Table rows ──
    table_rows = ""
    for mkt in _sorted_markets(rows):
        items = by_market[mkt]
        meta = MARKET_META.get(mkt, {"label": mkt, "color": "#d4d4d4"})
        mw = sum(1 for r in items if r.get("direction_match"))
        ml = sum(1 for r in items if r.get("direction_match") is False)
        table_rows += f"""
            <tr class="market-group-row" data-market="{mkt}">
                <td colspan="12" style="background:rgba(59,130,246,0.06);font-weight:700;
                    font-size:0.85rem;padding:10px 14px;color:{meta['color']}">
                    {meta['label']} &mdash; {len(items)} signals
                    (<span class="win">{mw} winning</span>,
                     <span class="lose">{ml} losing</span>)
                </td>
            </tr>"""

        for r in items:
            sym = r["symbol"]
            sig = r["signal"] or "-"
            sig_cls = "bullish" if "BULLISH" in sig else "bearish" if "BEARISH" in sig else ""

            # PnL cell
            pnl_val = r["pnl_pct"]
            dm = r["direction_match"]
            pnl_cls = ""
            pnl_icon = ""
            if dm is True:
                pnl_cls = "pnl-win"
                pnl_icon = '<span class="dm-icon win">&#10003;</span>'
            elif dm is False:
                pnl_cls = "pnl-lose"
                pnl_icon = '<span class="dm-icon lose">&#10007;</span>'
            pnl_html = f'{_pct(pnl_val)} {pnl_icon}' if pnl_val is not None else "-"

            # "Today" = intraday if realtime, else d1_change
            is_rt = r.get("is_realtime", False)
            today_val = r.get("intraday_pct") if is_rt else r.get("d1_change_pct")
            today_html = _change_cell(today_val)
            w_html = _change_cell(r.get("w_change_pct"))

            # Price cell: show RT badge if realtime
            cur_price_str = _p(r['current_price'])
            if is_rt:
                cur_price_str += ' <span class="rt-badge">RT</span>'

            # Range bar
            rng_html = _range_bar_html(r["w_range_pos"])

            # Regime badges
            regime_cells = ""
            for px in ("m", "w", "d"):
                badge = r.get(f"{px}_regime", "?")
                trend = r.get(f"{px}_trend", "")
                changed = r.get(f"{px}_changed", False)
                bcls = _trend_badge_cls(trend)
                if changed:
                    bcls += " regime-changed"
                regime_cells += f'<td class="regime-cell"><span class="regime-badge {bcls}">{badge}</span></td>'

            days = r["days_active"] if r["days_active"] is not None else "-"

            # Row class
            is_closed = r.get("is_closed", False)
            row_cls = "win-row" if dm is True else "lose-row" if dm is False else ""
            if is_closed:
                row_cls += " closed-row"
            closed_attr = "1" if is_closed else "0"

            # Status badge for closed signals
            status_html = ""
            if is_closed:
                exit_d = r.get("exit_date", "")
                exit_reason = r.get("exit_reason", "")
                reason_label = "&#x21C4;" if exit_reason == "direction_changed" else "&#x21BB;"
                status_html = (
                    f'<span class="closed-badge" title="Closed {exit_d} ({exit_reason})">'
                    f'{reason_label} {exit_d}</span>'
                )
                # For closed: show exit price, not today's
                cur_price_str = _p(r['current_price'])
                cur_price_str += f' <span class="closed-badge">EXIT</span>'

            table_rows += f"""
            <tr class="{row_cls}" data-market="{mkt}"
                data-dm="{1 if dm is True else 0 if dm is False else -1}"
                data-pnl="{pnl_val if pnl_val is not None else 0}"
                data-closed="{closed_attr}">
                <td class="sym">{sym}{' ' + status_html if status_html else ''}</td>
                <td><span class="signal-badge {sig_cls}">{sig}</span></td>
                <td class="num">{_p(r['entry_price'])}</td>
                <td class="num">{cur_price_str}</td>
                <td class="num {pnl_cls}">{pnl_html}</td>
                <td class="num">{today_html}</td>
                <td class="num">{w_html}</td>
                <td class="range-td">{rng_html}</td>
                {regime_cells}
                <td class="num dim">{days}</td>
            </tr>"""

    # ── Filter buttons ──
    market_btns = ""
    for mkt in _sorted_markets(rows):
        meta = MARKET_META.get(mkt, {"label": mkt})
        market_btns += (
            f'<button class="filter-btn" data-filter="{mkt}" '
            f"onclick=\"filterTable('{mkt}')\">{meta['label']}</button>\n"
        )

    first_note = (
        '<div class="first-run-note">First run -- snapshot saved as baseline. '
        'PnL will appear on subsequent runs.</div>' if is_first else ""
    )

    css = _dashboard_css()
    js = _dashboard_js()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Signal Tracker - {dates_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div class="sticky-header">
<h1>Signal Performance Tracker</h1>
<div class="meta">Signals scanned {dates_str} &middot; Refreshed {now_str}</div>
{first_note}

<div class="stats-strip">
    <div class="stat-box">
        <div class="stat-label">Signals</div>
        <div class="stat-value">{len(rows)}</div>
    </div>
    <div class="stat-box">
        <div class="stat-label">Winning</div>
        <div class="stat-value win">{winning}</div>
    </div>
    <div class="stat-box">
        <div class="stat-label">Losing</div>
        <div class="stat-value lose">{losing}</div>
    </div>
    <div class="stat-box">
        <div class="stat-label">Win Rate</div>
        <div class="stat-value">{win_pct:.0f}%</div>
    </div>
    <div class="stat-box">
        <div class="stat-label">Avg Dir-PnL</div>
        <div class="stat-value {'win' if avg_pnl >= 0 else 'lose'}">{_pct(avg_pnl)}</div>
    </div>
    <div class="stat-box">
        <div class="stat-label">Active</div>
        <div class="stat-value">{active_count}</div>
    </div>
    <div class="stat-box">
        <div class="stat-label">Closed</div>
        <div class="stat-value dim">{closed_count}</div>
    </div>
</div>

<div class="market-cards">{market_cards}
</div>

<div class="filter-bar">
    <button class="filter-btn active" data-filter="ALL" onclick="filterTable('ALL')">All ({len(rows)})</button>
    <button class="filter-btn" data-filter="ACTIVE" onclick="filterTable('ACTIVE')">Active ({active_count})</button>
    <button class="filter-btn" data-filter="CLOSED" onclick="filterTable('CLOSED')">Closed ({closed_count})</button>
    <button class="filter-btn" data-filter="WINNING" onclick="filterTable('WINNING')">Winning ({winning})</button>
    <button class="filter-btn" data-filter="LOSING" onclick="filterTable('LOSING')">Losing ({losing})</button>
    {market_btns}
</div>
</div>

<div class="table-wrap">
<table id="mainTbl">
<thead><tr>
    <th onclick="sortCol(0)">Symbol</th>
    <th onclick="sortCol(1)">Signal</th>
    <th onclick="sortCol(2)" class="num-hdr">Entry</th>
    <th onclick="sortCol(3)" class="num-hdr">Current</th>
    <th onclick="sortCol(4)" class="num-hdr">PnL%</th>
    <th onclick="sortCol(5)" class="num-hdr">Today</th>
    <th onclick="sortCol(6)" class="num-hdr">1W Chg</th>
    <th onclick="sortCol(7)">W-Range</th>
    <th onclick="sortCol(8)">M</th>
    <th onclick="sortCol(9)">W</th>
    <th onclick="sortCol(10)">D</th>
    <th onclick="sortCol(11)" class="num-hdr">Days</th>
</tr></thead>
<tbody>{table_rows}
</tbody>
</table>
</div>

{_build_trade_history_html(trade_history or [])}

<script>{js}</script>
</body>
</html>"""

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


# ── Main ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Signal Performance Tracker")
    parser.add_argument("--date", help="Signal date (YYYY-MM-DD), default: today")
    parser.add_argument("--days", type=int, default=1, help="Include last N days of signals")
    parser.add_argument("--markets", nargs="*", help="Filter markets (e.g. BINANCE FX)")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open dashboard")
    parser.add_argument("--output", help="Dashboard output path")
    parser.add_argument("--reset", action="store_true", help="Delete existing snapshot")
    parser.add_argument("--no-realtime", action="store_true",
                        help="Skip realtime price fetch (use D1 close only)")
    args = parser.parse_args()

    end_date = date.fromisoformat(args.date) if args.date else date.today()
    dates = [(end_date - timedelta(days=i)).isoformat() for i in range(args.days)]
    dates.reverse()

    sig_logger = SignalLogger()
    all_signals: List[Dict] = []
    for d in dates:
        sigs = sig_logger.get_ready_signals(d)
        for s in sigs:
            s["log_date"] = d
        all_signals.extend(sigs)

    if args.markets:
        mkt_filter = {m.upper() for m in args.markets}
        all_signals = [s for s in all_signals if s["market"] in mkt_filter]

    if not all_signals:
        print(f"\n[!] No READY signals found for: {', '.join(dates)}")
        sys.exit(0)

    # Fetch realtime prices (before heavy analysis)
    rt_prices: Dict[str, float] = {}
    if not args.no_realtime:
        rt_prices = fetch_realtime_prices(all_signals)

    # Ensure aggregate signal DB is up-to-date (single-file, fast lookup)
    sig_logger.aggregate()

    # Detect superseded signals (new READY signal on a later date)
    date_str = dates[-1]
    exit_info = _find_exit_info(all_signals, date_str)
    if exit_info:
        n_closed = len(exit_info)
        print(f"  Signal lifecycle: {n_closed} signals flipped direction (closed)")

    if args.reset:
        p = _snap_path(date_str)
        if p.exists():
            p.unlink()
        # Also remove from S3 so next run rebuilds with prior-day entry prices
        try:
            from infra.s3_storage import _get_singleton
            s3 = _get_singleton()
            if s3 is not None:
                key = s3._report_key(p.resolve())
                s3.client.delete_object(Bucket=s3._bucket, Key=key)
                print(f"  Snapshot deleted from S3: {key}")
        except Exception as _e:
            print(f"  [warn] S3 delete failed: {_e}")

    existing = load_snapshot(date_str)
    is_first = len(existing) == 0

    print(f"  Loading {len(all_signals)} signals from {', '.join(dates)}")
    if is_first:
        print(f"  First run -- creating snapshot baseline ...")
    else:
        print(f"  Loaded snapshot ({len(existing)} entries) -- comparing ...")

    snapshot, rows = build_tracker_data(all_signals, date_str,
                                        realtime_prices=rt_prices,
                                        exit_info=exit_info,
                                        existing_snapshot=existing)

    # Persist closed trades to trade history
    closed_trade_records = _build_closed_trade_records(rows)
    if closed_trade_records:
        save_closed_trades(closed_trade_records)
        print(f"  Trade history: {len(closed_trade_records)} closed trade(s) recorded")

    # Load full trade history for reports
    trade_history = load_trade_history()

    print_terminal_report(rows, dates, is_first, trade_history)

    output_path = args.output or "markets/output/signal_tracker.html"
    dashboard = generate_dashboard(rows, dates, output_path, is_first, trade_history)
    print(f"  Snapshot : {_snap_path(date_str)}")
    print(f"  Trade log: {_trade_history_path()} ({len(trade_history)} trades)")
    print(f"  Dashboard: {dashboard}")

    if not args.no_open:
        from infra.s3_storage import publish_and_clean
        url = publish_and_clean(dashboard)
        if url:
            import webbrowser as _wb
            _wb.open(url)
            print(f"  Opened S3 tracker in browser (presigned URL).")
        else:
            # S3 unavailable — open local file (don't delete it)
            import webbrowser as _wb
            _wb.open(f"file:///{Path(dashboard).resolve()}")
            print("  Opened local tracker in browser.")
    else:
        # --no-open: still upload & clean the local HTML file
        try:
            from infra.s3_storage import publish_and_clean
            publish_and_clean(dashboard)
        except Exception:
            pass


if __name__ == "__main__":
    main()
