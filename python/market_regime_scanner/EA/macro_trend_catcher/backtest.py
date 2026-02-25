"""
Trend Catcher V2.1 — Binance SPOT Backtest with Detailed Trade Log
====================================================================

Same logic as ``backtest_spot_v21.py`` but outputs a per-trade CSV/JSON
log with full entry context for manual analysis.

Each trade record includes:
- Entry/exit time, price, reason
- M/W/D alignment state (ready, direction, compressed)
- MBA range per TF (area_low → area_high)
- ATR at entry, stop-loss distance
- Gross/net return, duration

Post-backtest pipeline:
1. Run all symbols → collect trades
2. Score/rank via EA.shared.market_filter
3. Export detailed trade log (CSV + JSON)
4. Print summary report with aggregate stats

Outputs::

    reports/v21_trade_log.csv          — every trade, every symbol
    reports/v21_trade_log.json         — same data, JSON format
    reports/v21_summary_report.txt     — human-readable summary
    reports/spot_v21_backtest_results.json — per-symbol results (for filter)

Usage::

    python -m EA.macro_trend_catcher.backtest
    python -m EA.macro_trend_catcher.backtest --cooldown 20 --sl-mult 3.0
"""

import os
import sys
import csv
import json
import logging
import time
import statistics
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict

import polars as pl

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.tpo import TPOProfile
from core.resampler import resample_data
from analytic.tpo_mba.tracker import build_mba_context
from analytic.tpo_mba.alignment import build_tf_regime, evaluate_overall_signal
from EA.shared.indicators import calculate_atr
from EA.shared.backtest_utils import Trade, calculate_metrics
from EA.macro_trend_catcher.config import (
    TrendCatcherV2Config,
    BINANCE_SKIP_SYMBOLS,
    ASSET_CONFIG,
    FOREX_V2,
    COMMODITIES_V2,
    US_STOCKS_V2,
    CRYPTO_V2,
)
from EA.macro_trend_catcher.signals import SignalGeneratorV2
from EA.regime_filters import RegimeGate, BtcRegimeFilter, BroadMarketFilter

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("SpotBacktestV21Detail")

BINANCE_DATA_DIR = os.path.join(project_root, "data", "binance")
MT5_DATA_DIR = os.path.join(project_root, "data", "mt5")
DATA_DIR = BINANCE_DATA_DIR  # default for backward compat
REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")

SKIP_SYMBOLS = BINANCE_SKIP_SYMBOLS
MIN_H4_BARS = 4536  # ~3 years
MIN_H4_BARS_MT5 = 3000  # ~2 years (MT5 data is shorter)

# Binance spot fee: 0.1% maker/taker (BNB discount not assumed)
DEFAULT_FEE_RATE = 0.001  # 0.1% per side → 0.2% round-trip
# MT5 fee: spread is already embedded in OHLC → near-zero extra fee
MT5_FEE_RATE = 0.00005  # ~0.005% nominal for slippage


# ═══════════════════════════════════════════════════════════════
# Regime Filters  (see EA/regime_filters/)
# ═══════════════════════════════════════════════════════════════

def build_regime_gate(
    btc_filter: bool = False,
    broad_market_filter: bool = False,
    bear_threshold: float = 0.70,
    data_dir: str = "",
) -> Optional[RegimeGate]:
    """
    Build a :class:`RegimeGate` from CLI flags.

    Returns *None* if no filter is enabled.
    """
    if not data_dir:
        data_dir = BINANCE_DATA_DIR

    gate = RegimeGate()

    if btc_filter:
        gate.add(BtcRegimeFilter(data_dir=data_dir))

    if broad_market_filter:
        gate.add(BroadMarketFilter(
            data_dir=data_dir,
            bear_threshold=bear_threshold,
            skip_symbols=SKIP_SYMBOLS,
        ))

    if not gate.filters:
        return None

    gate.build()          # pre-compute all lookups
    return gate


def build_btc_regime_lookup() -> Dict[str, str]:
    """Legacy wrapper — delegates to BtcRegimeFilter."""
    filt = BtcRegimeFilter(data_dir=BINANCE_DATA_DIR)
    filt.build()
    return filt._lookup


# ═══════════════════════════════════════════════════════════════
# Data Types
# ═══════════════════════════════════════════════════════════════

@dataclass
class TradeLogEntry:
    """Detailed per-trade log entry for analysis."""
    # ── Identification ────────────────────────────────────
    symbol: str
    trade_id: int

    # ── Timing ────────────────────────────────────────────
    entry_time: str
    exit_time: str
    duration_days: int

    # ── Price action ──────────────────────────────────────
    entry_price: float
    exit_price: float
    stop_loss: float
    sl_distance_pct: float      # (entry - SL) / entry * 100
    atr_at_entry: float

    # ── Returns ───────────────────────────────────────────
    direction: str               # "bullish"
    exit_reason: str
    gross_return_pct: float
    net_return_pct: float        # after fees
    is_win: bool

    # ── Monthly alignment ─────────────────────────────────
    m_ready: bool
    m_direction: str
    m_compressed: bool
    m_mba_low: float
    m_mba_high: float
    m_continuity: int

    # ── Weekly alignment ──────────────────────────────────
    w_ready: bool
    w_direction: str
    w_compressed: bool
    w_mba_low: float
    w_mba_high: float
    w_continuity: int

    # ── Daily alignment ───────────────────────────────────
    d_ready: bool
    d_direction: str
    d_compressed: bool
    d_mba_low: float
    d_mba_high: float
    d_continuity: int

    # ── Alignment summary ─────────────────────────────────
    alignment_summary: str       # e.g. "[ALIGNED] M:✓⊕(bullish) W:✓⊕(bullish) D:✓⊕(bullish)"

    # ── Equity state ──────────────────────────────────────
    equity_before: float         # normalized equity (1.0 = start)
    equity_after: float

    # ── BTC regime at entry ───────────────────────────────
    btc_regime: str = ""         # BTC Monthly MBA direction at entry time


@dataclass
class SpotBacktestResult:
    """Per-symbol result with realistic metrics."""
    symbol: str
    total_trades: int = 0
    long_trades: int = 0
    short_trades: int = 0
    skipped_short: int = 0
    skipped_no_compress: int = 0
    skipped_btc_bearish: int = 0
    win_rate: float = 0.0
    gross_return: float = 0.0
    net_return: float = 0.0
    total_fees: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    avg_duration: float = 0.0
    data_years: float = 0.0
    error: str = ""
    trade_log: List[TradeLogEntry] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# Core Backtest Engine
# ═══════════════════════════════════════════════════════════════

def get_binance_symbols(min_h4_bars: int = MIN_H4_BARS) -> List[str]:
    """Get all tradeable Binance spot symbols with enough data."""
    from infra.s3_storage import list_remote_files, smart_read_parquet
    # Merge local + S3 file lists
    local_files = []
    if os.path.isdir(DATA_DIR):
        local_files = [f for f in os.listdir(DATA_DIR) if f.endswith("_H4.parquet")]
    remote_files = list_remote_files(DATA_DIR, "*_H4.parquet")
    files = sorted(set(local_files) | set(remote_files))
    symbols = []
    for f in sorted(files):
        sym = f.replace("_USDT_H4.parquet", "")
        if sym in SKIP_SYMBOLS:
            continue
        path = os.path.join(DATA_DIR, f)
        try:
            df = smart_read_parquet(path)
            if df is not None and len(df) >= min_h4_bars:
                symbols.append(sym)
        except Exception:
            continue
    return symbols


# ── MT5 symbols: FX, commodities, indices, stocks ──

# Which MT5 symbols have weekend data (crypto only)
MT5_WEEKEND_SYMBOLS = {"BTCUSDm", "ETHUSDm", "SOLUSDm", "XRPUSDm", "BNBUSDm", "LTCUSDm"}


def get_mt5_symbols(groups: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Get MT5 symbols from ASSET_CONFIG with enough parquet data.

    Returns list of dicts: {"symbol": str, "config": TrendCatcherV2Config, "has_weekend": bool}
    If *groups* is None, use all groups except CRYPTO (use Binance for that).
    """
    if groups is None:
        groups = ["FOREX_MAJORS", "FOREX_CROSSES", "COMMODITIES"]

    result = []
    for group_name in groups:
        group = ASSET_CONFIG.get(group_name)
        if group is None:
            logger.warning("Unknown asset group: %s", group_name)
            continue
        cfg = group["config"]
        for sym in group["symbols"]:
            path = os.path.join(MT5_DATA_DIR, f"{sym}_H4.parquet")
            try:
                from infra.s3_storage import smart_read_parquet
                df_check = smart_read_parquet(path)
                if df_check is None:
                    continue
                n = len(df_check)
                if n >= MIN_H4_BARS_MT5:
                    result.append({
                        "symbol": sym,
                        "config": cfg,
                        "has_weekend": sym in MT5_WEEKEND_SYMBOLS,
                    })
            except Exception:
                continue
    return result


def _extract_mba_info(meta) -> Dict[str, Any]:
    """Extract MBA range and continuity from MBAMetadata."""
    if meta is None:
        return {"mba_low": 0.0, "mba_high": 0.0, "continuity": 0}
    mba_low = meta.current_mba.area_low if meta.current_mba else 0.0
    mba_high = meta.current_mba.area_high if meta.current_mba else 0.0
    return {
        "mba_low": round(mba_low, 8),
        "mba_high": round(mba_high, 8),
        "continuity": meta.mba_continuity_count,
    }


def _resolve_btc_regime(
    regime_gate: Optional[RegimeGate],
    btc_regime_lookup: Optional[Dict[str, str]],
    current_date,
) -> str:
    """Return BTC regime string for trade-log context."""
    date_str = current_date.strftime("%Y-%m-%d")
    if regime_gate:
        for f in regime_gate.filters:
            if f.name == "btc_regime":
                return f.get_state(date_str) or "neutral"
    if btc_regime_lookup:
        return btc_regime_lookup.get(date_str, "neutral")
    return ""


def run_single_backtest(
    symbol: str,
    config: TrendCatcherV2Config,
    fee_rate: float = DEFAULT_FEE_RATE,
    btc_regime_lookup: Optional[Dict[str, str]] = None,
    regime_gate: Optional[RegimeGate] = None,
    signal_version: str = "v2",
    market: str = "binance",          # "binance" or "mt5"
    has_weekend: bool = True,         # Binance=True, FX/Commodities=False
    allow_short: bool = False,        # True for MT5 FX/Commodities
    soft_sl: bool = False,            # True = no hard SL, exit only on M direction flip
    require_compression: bool = True, # False = no compression gate (more signals)
) -> SpotBacktestResult:
    """
    Run V2.1 backtest with detailed trade logging.

    When *market* == "mt5", loads from data/mt5/, supports LONG+SHORT,
    and uses near-zero fee (spread is embedded in MT5 OHLC data).
    """
    result = SpotBacktestResult(symbol=symbol)
    round_trip_fee = fee_rate * 2
    trade_log: List[TradeLogEntry] = []

    try:
        # Load H4 data
        if market == "mt5":
            path = os.path.join(MT5_DATA_DIR, f"{symbol}_H4.parquet")
        else:
            path = os.path.join(BINANCE_DATA_DIR, f"{symbol}_USDT_H4.parquet")
        from infra.s3_storage import smart_read_parquet
        df_h4 = smart_read_parquet(path)
        if df_h4 is None:
            result.error = "data_not_found"
            return result
        df_h4 = df_h4.sort("time")
        result.data_years = len(df_h4) / 6 / 252

        # Resample
        df_d1 = resample_data(df_h4, "D1", has_weekend=has_weekend)
        df_w1 = resample_data(df_h4, "W1", has_weekend=has_weekend)

        if len(df_d1) < 100 or len(df_w1) < 20:
            result.error = "insufficient_resampled_data"
            return result

        # Build TPO sessions
        engine = TPOProfile(va_percentage=0.7, ib_bars=2)
        all_m = engine.analyze_dynamic(df_w1, session_type="M")
        all_w = engine.analyze_dynamic(df_d1, session_type="W")
        all_d = engine.analyze_dynamic(df_h4, session_type="D")

        if len(all_m) < 5 or len(all_w) < 5 or len(all_d) < 5:
            result.error = "insufficient_sessions"
            return result

        # Walk-forward
        signal_gen = SignalGeneratorV2()
        trades: List[Trade] = []
        open_position = None
        cooldown_until = None
        cooldown_direction = None
        skipped_short = 0
        skipped_no_compress = 0
        skipped_btc_bearish = 0
        trade_counter = 0

        # Track equity for logging
        equity = 1.0

        # Store entry context for logging at exit
        entry_context: Optional[Dict] = None

        start_idx = 80
        for i in range(start_idx, len(df_d1)):
            current_date = df_d1[i, "time"]
            daily_high = df_d1[i, "high"]
            daily_low = df_d1[i, "low"]
            current_price = df_d1[i, "close"]

            closed_m = [s for s in all_m if s.session_end < current_date and s.is_closed]
            closed_w = [s for s in all_w if s.session_end < current_date and s.is_closed]
            closed_d = [s for s in all_d if s.session_end < current_date and s.is_closed]

            if len(closed_m) < 3 or len(closed_w) < 3 or len(closed_d) < 3:
                continue

            meta_m = build_mba_context(closed_m, timeframe="Monthly", symbol=symbol)
            meta_w = build_mba_context(closed_w, timeframe="Weekly", symbol=symbol)
            meta_d = build_mba_context(closed_d, timeframe="Daily", symbol=symbol)

            alignment = signal_gen.build_alignment(
                meta_m, meta_w, meta_d,
                require_compression=require_compression,
            )

            # V3: build TFRegimes for unified signal evaluation
            if signal_version == "v3":
                regime_m = build_tf_regime(meta_m, closed_m)
                regime_w = build_tf_regime(meta_w, closed_w)
                regime_d = build_tf_regime(meta_d, closed_d)

            # ── Exit check ──
            if open_position:
                pos = open_position
                hit_sl = False
                exit_price = current_price
                exit_reason = ""

                # SL hit detection: LONG checks low, SHORT checks high
                # When soft_sl=True, skip hard SL → exit only on M direction flip
                pos_dir = pos["direction"]
                if not soft_sl:
                    if pos_dir == "bullish" and daily_low <= pos["stop_loss"]:
                        exit_price = pos["stop_loss"]
                        hit_sl = True
                        exit_reason = "stop_loss"
                    elif pos_dir == "bearish" and daily_high >= pos["stop_loss"]:
                        exit_price = pos["stop_loss"]
                        hit_sl = True
                        exit_reason = "stop_loss"

                if not hit_sl:
                    exit_check = signal_gen.check_exit(
                        position_direction=pos_dir, meta_m=meta_m,
                    )
                    if exit_check:
                        exit_reason = exit_check

                if exit_reason:
                    trade = Trade(
                        entry_time=pos["entry_time"], exit_time=current_date,
                        direction=pos_dir, entry_price=pos["entry_price"],
                        exit_price=exit_price, exit_reason=exit_reason,
                        stop_loss=pos["stop_loss"],
                    )
                    trades.append(trade)

                    # ── Log this trade ──
                    gross_ret = trade.return_pct
                    net_ret = gross_ret - (round_trip_fee * 100)
                    equity_before = equity
                    equity *= (1 + net_ret / 100)

                    trade_counter += 1
                    ctx = entry_context or {}
                    log_entry = TradeLogEntry(
                        symbol=symbol,
                        trade_id=trade_counter,
                        entry_time=pos["entry_time"].strftime("%Y-%m-%d"),
                        exit_time=current_date.strftime("%Y-%m-%d"),
                        duration_days=trade.duration_days,
                        entry_price=round(pos["entry_price"], 8),
                        exit_price=round(exit_price, 8),
                        stop_loss=round(pos["stop_loss"], 8),
                        sl_distance_pct=round(
                            abs(pos["entry_price"] - pos["stop_loss"]) / pos["entry_price"] * 100, 2
                        ),
                        atr_at_entry=round(pos["atr"], 8),
                        direction=pos_dir,
                        exit_reason=exit_reason,
                        gross_return_pct=round(gross_ret, 4),
                        net_return_pct=round(net_ret, 4),
                        is_win=net_ret > 0,
                        m_ready=ctx.get("m_ready", False),
                        m_direction=ctx.get("m_direction", ""),
                        m_compressed=ctx.get("m_compressed", False),
                        m_mba_low=ctx.get("m_mba_low", 0.0),
                        m_mba_high=ctx.get("m_mba_high", 0.0),
                        m_continuity=ctx.get("m_continuity", 0),
                        w_ready=ctx.get("w_ready", False),
                        w_direction=ctx.get("w_direction", ""),
                        w_compressed=ctx.get("w_compressed", False),
                        w_mba_low=ctx.get("w_mba_low", 0.0),
                        w_mba_high=ctx.get("w_mba_high", 0.0),
                        w_continuity=ctx.get("w_continuity", 0),
                        d_ready=ctx.get("d_ready", False),
                        d_direction=ctx.get("d_direction", ""),
                        d_compressed=ctx.get("d_compressed", False),
                        d_mba_low=ctx.get("d_mba_low", 0.0),
                        d_mba_high=ctx.get("d_mba_high", 0.0),
                        d_continuity=ctx.get("d_continuity", 0),
                        alignment_summary=ctx.get("alignment_summary", ""),
                        equity_before=round(equity_before, 6),
                        equity_after=round(equity, 6),
                    )
                    log_entry.btc_regime = ctx.get("btc_regime", "")
                    trade_log.append(log_entry)

                    open_position = None
                    entry_context = None
                    if hit_sl:
                        cooldown_until = current_date + timedelta(days=config.cooldown_days)
                        cooldown_direction = pos_dir
                    continue

            # ── Entry check (Compression Gate) ──
            if not open_position:
                if signal_version == "v3":
                    # V3: unified pipeline with Path 1 + Path 2
                    sig_result = evaluate_overall_signal(
                        regime_m, regime_w, regime_d,
                        require_compression=require_compression,
                    )
                    # Track compression gate impact (no-compress vs compress)
                    if require_compression:
                        sig_no_compress = evaluate_overall_signal(
                            regime_m, regime_w, regime_d,
                            require_compression=False,
                        )
                        if sig_no_compress.direction and not sig_result.direction:
                            skipped_no_compress += 1

                    if not sig_result.direction:
                        continue

                    direction = sig_result.direction
                    signal_path = sig_result.path
                    if direction == "bearish" and not allow_short:
                        skipped_short += 1
                        continue
                else:
                    # V2: legacy alignment (balance-only)
                    alignment_v2 = signal_gen.build_alignment(
                        meta_m, meta_w, meta_d,
                        require_compression=False,
                    )
                    if alignment_v2.is_aligned and not alignment.is_aligned:
                        skipped_no_compress += 1

                    if not alignment.is_aligned:
                        continue

                    direction = alignment.direction
                    signal_path = "balance_aligned"
                    if direction == "bearish" and not allow_short:
                        skipped_short += 1
                        continue

                # ── Regime Gate (BTC + Broad Market, etc.) ──
                date_str = current_date.strftime("%Y-%m-%d")
                if regime_gate:
                    verdict = regime_gate.check(
                        date_str, direction=direction, symbol=symbol
                    )
                    if verdict.blocked:
                        skipped_btc_bearish += 1
                        continue
                elif btc_regime_lookup and symbol != "BTC":
                    # Legacy path: plain dict lookup
                    btc_dir = btc_regime_lookup.get(date_str, "neutral")
                    if btc_dir == "bearish":
                        skipped_btc_bearish += 1
                        continue

                # Cooldown
                if (cooldown_until is not None
                    and current_date < cooldown_until
                    and direction == cooldown_direction):
                    continue

                # Price-direction validation
                price_ok = True
                for meta in (meta_m, meta_w, meta_d):
                    if meta and meta.current_mba:
                        if direction == "bullish" and current_price < meta.current_mba.area_low:
                            price_ok = False
                            break
                        if direction == "bearish" and current_price > meta.current_mba.area_high:
                            price_ok = False
                            break
                if not price_ok:
                    continue

                # MBA continuity
                skip = False
                for meta in (meta_m, meta_w, meta_d):
                    if meta and meta.mba_continuity_count < config.min_mba_continuity:
                        skip = True
                        break
                if skip:
                    continue

                # ATR
                closes_win = [df_d1[j, "close"] for j in range(max(0, i - 20), i + 1)]
                highs_win = [df_d1[j, "high"] for j in range(max(0, i - 20), i + 1)]
                lows_win = [df_d1[j, "low"] for j in range(max(0, i - 20), i + 1)]
                atr = calculate_atr(highs_win, lows_win, closes_win, config.atr_period)
                if atr <= 0:
                    continue

                if direction == "bullish":
                    sl = current_price - config.initial_stop_atr_mult * atr
                else:
                    sl = current_price + config.initial_stop_atr_mult * atr

                open_position = {
                    "direction": direction,
                    "entry_price": current_price,
                    "stop_loss": sl,
                    "entry_time": current_date,
                    "atr": atr,
                }

                # ── Capture entry context for logging ──
                m_info = _extract_mba_info(meta_m)
                w_info = _extract_mba_info(meta_w)
                d_info = _extract_mba_info(meta_d)

                if signal_version == "v3":
                    entry_context = {
                        "m_ready": regime_m.is_ready,
                        "m_direction": regime_m.ready_direction or regime_m.trend or "",
                        "m_compressed": regime_m.is_compressed,
                        "m_mba_low": m_info["mba_low"],
                        "m_mba_high": m_info["mba_high"],
                        "m_continuity": m_info["continuity"],
                        "w_ready": regime_w.is_ready,
                        "w_direction": regime_w.ready_direction or regime_w.trend or "",
                        "w_compressed": regime_w.is_compressed,
                        "w_mba_low": w_info["mba_low"],
                        "w_mba_high": w_info["mba_high"],
                        "w_continuity": w_info["continuity"],
                        "d_ready": regime_d.is_ready,
                        "d_direction": regime_d.ready_direction or regime_d.trend or "",
                        "d_compressed": regime_d.is_compressed,
                        "d_mba_low": d_info["mba_low"],
                        "d_mba_high": d_info["mba_high"],
                        "d_continuity": d_info["continuity"],
                        "alignment_summary": f"[V3:{signal_path}] {sig_result.signal}",
                        "btc_regime": _resolve_btc_regime(regime_gate, btc_regime_lookup, current_date),
                    }
                else:
                    entry_context = {
                        "m_ready": alignment.monthly_ready,
                        "m_direction": alignment.monthly_direction or "",
                        "m_compressed": alignment.monthly_compressed,
                        "m_mba_low": m_info["mba_low"],
                        "m_mba_high": m_info["mba_high"],
                        "m_continuity": m_info["continuity"],
                        "w_ready": alignment.weekly_ready,
                        "w_direction": alignment.weekly_direction or "",
                        "w_compressed": alignment.weekly_compressed,
                        "w_mba_low": w_info["mba_low"],
                        "w_mba_high": w_info["mba_high"],
                        "w_continuity": w_info["continuity"],
                        "d_ready": alignment.daily_ready,
                        "d_direction": alignment.daily_direction or "",
                        "d_compressed": alignment.daily_compressed,
                        "d_mba_low": d_info["mba_low"],
                        "d_mba_high": d_info["mba_high"],
                        "d_continuity": d_info["continuity"],
                        "alignment_summary": alignment.summary(),
                        "btc_regime": _resolve_btc_regime(regime_gate, btc_regime_lookup, current_date),
                    }

        # Close open position at end of data
        if open_position:
            last_price = df_d1[-1, "close"]
            last_date = df_d1[-1, "time"]
            eob_dir = open_position["direction"]
            trade = Trade(
                entry_time=open_position["entry_time"], exit_time=last_date,
                direction=eob_dir,
                entry_price=open_position["entry_price"],
                exit_price=last_price, exit_reason="end_of_backtest",
                stop_loss=open_position["stop_loss"],
            )
            trades.append(trade)

            gross_ret = trade.return_pct
            net_ret = gross_ret - (round_trip_fee * 100)
            equity_before = equity
            equity *= (1 + net_ret / 100)

            trade_counter += 1
            ctx = entry_context or {}
            log_entry = TradeLogEntry(
                symbol=symbol, trade_id=trade_counter,
                entry_time=open_position["entry_time"].strftime("%Y-%m-%d"),
                exit_time=last_date.strftime("%Y-%m-%d"),
                duration_days=trade.duration_days,
                entry_price=round(open_position["entry_price"], 8),
                exit_price=round(last_price, 8),
                stop_loss=round(open_position["stop_loss"], 8),
                sl_distance_pct=round(
                    abs(open_position["entry_price"] - open_position["stop_loss"]) / open_position["entry_price"] * 100, 2
                ),
                atr_at_entry=round(open_position["atr"], 8),
                direction=eob_dir, exit_reason="end_of_backtest",
                gross_return_pct=round(gross_ret, 4),
                net_return_pct=round(net_ret, 4),
                is_win=net_ret > 0,
                m_ready=ctx.get("m_ready", False),
                m_direction=ctx.get("m_direction", ""),
                m_compressed=ctx.get("m_compressed", False),
                m_mba_low=ctx.get("m_mba_low", 0.0),
                m_mba_high=ctx.get("m_mba_high", 0.0),
                m_continuity=ctx.get("m_continuity", 0),
                w_ready=ctx.get("w_ready", False),
                w_direction=ctx.get("w_direction", ""),
                w_compressed=ctx.get("w_compressed", False),
                w_mba_low=ctx.get("w_mba_low", 0.0),
                w_mba_high=ctx.get("w_mba_high", 0.0),
                w_continuity=ctx.get("w_continuity", 0),
                d_ready=ctx.get("d_ready", False),
                d_direction=ctx.get("d_direction", ""),
                d_compressed=ctx.get("d_compressed", False),
                d_mba_low=ctx.get("d_mba_low", 0.0),
                d_mba_high=ctx.get("d_mba_high", 0.0),
                d_continuity=ctx.get("d_continuity", 0),
                alignment_summary=ctx.get("alignment_summary", ""),
                equity_before=round(equity_before, 6),
                equity_after=round(equity, 6),
            )
            log_entry.btc_regime = ctx.get("btc_regime", "")
            trade_log.append(log_entry)

        result.skipped_short = skipped_short
        result.skipped_no_compress = skipped_no_compress
        result.skipped_btc_bearish = skipped_btc_bearish
        result.trade_log = trade_log

        if not trades:
            result.error = "no_trades"
            return result

        # ── Calculate metrics ──
        result.long_trades = sum(1 for t in trades if t.direction == "bullish")
        result.short_trades = sum(1 for t in trades if t.direction == "bearish")
        result.total_trades = len(trades)

        gross_returns = [t.return_pct for t in trades]
        net_returns = [r - (round_trip_fee * 100) for r in gross_returns]

        eq = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in net_returns:
            eq *= (1 + r / 100)
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)

        result.gross_return = sum(gross_returns)
        result.net_return = (eq - 1.0) * 100
        result.total_fees = len(trades) * round_trip_fee * 100
        result.max_drawdown = max_dd

        wins_net = [r for r in net_returns if r > 0]
        losses_net = [r for r in net_returns if r <= 0]
        result.win_rate = len(wins_net) / len(net_returns) * 100 if net_returns else 0

        total_win_pct = sum(wins_net) if wins_net else 0
        total_loss_pct = abs(sum(losses_net)) if losses_net else 0.001
        result.profit_factor = total_win_pct / total_loss_pct

        if len(net_returns) > 1:
            avg_r = statistics.mean(net_returns)
            std_r = statistics.stdev(net_returns)
            trades_per_year = min(len(net_returns) / max(result.data_years, 0.5), 252)
            if std_r > 0:
                result.sharpe_ratio = (avg_r / std_r) * (trades_per_year ** 0.5)

        result.avg_duration = sum(t.duration_days for t in trades) / len(trades)

    except Exception as e:
        result.error = str(e)[:200]

    return result


# ═══════════════════════════════════════════════════════════════
# Trade Log Export
# ═══════════════════════════════════════════════════════════════

CSV_COLUMNS = [
    "symbol", "trade_id", "entry_time", "exit_time", "duration_days",
    "entry_price", "exit_price", "stop_loss", "sl_distance_pct", "atr_at_entry",
    "direction", "exit_reason", "gross_return_pct", "net_return_pct", "is_win",
    "m_ready", "m_direction", "m_compressed", "m_mba_low", "m_mba_high", "m_continuity",
    "w_ready", "w_direction", "w_compressed", "w_mba_low", "w_mba_high", "w_continuity",
    "d_ready", "d_direction", "d_compressed", "d_mba_low", "d_mba_high", "d_continuity",
    "alignment_summary", "equity_before", "equity_after", "btc_regime",
]


def export_trade_log(
    all_logs: List[TradeLogEntry],
    csv_path: str,
    json_path: str,
):
    """Export trade log to CSV and JSON."""
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    # CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for entry in all_logs:
            writer.writerow(asdict(entry))

    # JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            [asdict(entry) for entry in all_logs],
            f, indent=2, ensure_ascii=False,
        )

    print(f"  Trade log CSV -> {csv_path}  ({len(all_logs)} trades)")
    print(f"  Trade log JSON -> {json_path}")


# ═══════════════════════════════════════════════════════════════
# Summary Report Generator
# ═══════════════════════════════════════════════════════════════

def generate_report(
    results: List[SpotBacktestResult],
    all_logs: List[TradeLogEntry],
    config: TrendCatcherV2Config,
    fee_rate: float,
    report_path: str,
):
    """Generate a comprehensive text report."""
    valid = [r for r in results if not r.error and r.total_trades >= 3]
    profitable = [r for r in valid if r.net_return > 0]
    losing = [r for r in valid if r.net_return <= 0]

    total_skipped_short = sum(r.skipped_short for r in results)
    total_skipped_compress = sum(r.skipped_no_compress for r in results)
    total_skipped_btc = sum(r.skipped_btc_bearish for r in results)
    total_trades = sum(r.total_trades for r in valid)

    lines = []
    w = lines.append

    w("=" * 100)
    w("TREND CATCHER V2.1 — BINANCE SPOT BACKTEST REPORT (DETAILED)")
    w(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w("=" * 100)
    w("")

    # ── Config ──
    w("CONFIGURATION")
    w("-" * 50)
    w(f"  Strategy:           Macro Trend Catcher V2.1 (Compression Gate)")
    w(f"  Mode:               LONG-ONLY (Binance Spot)")
    w(f"  SL Multiplier:      {config.initial_stop_atr_mult}x ATR")
    w(f"  Cooldown:           {config.cooldown_days} days after SL")
    w(f"  Fee/side:           {fee_rate * 100:.2f}%  (round-trip: {fee_rate * 200:.2f}%)")
    w(f"  Min data:           {MIN_H4_BARS} H4 bars (~3 years)")
    w(f"  Compression Gate:   Normal / Neutral / 3-1-3 (all 3 TFs)")
    w(f"  BTC Regime Filter:  {'ON' if total_skipped_btc > 0 else 'OFF'}")
    w("")

    # ── Universe ──
    w("UNIVERSE SUMMARY")
    w("-" * 50)
    w(f"  Total symbols tested:     {len(results)}")
    w(f"  Valid (≥3 trades):        {len(valid)}")
    w(f"  Profitable:               {len(profitable)}  ({len(profitable)/max(len(valid),1)*100:.0f}%)")
    w(f"  Losing:                   {len(losing)}")
    w(f"  Total trades:             {total_trades}")
    w(f"  Total trade log entries:  {len(all_logs)}")
    w(f"  Bearish skipped (spot):   {total_skipped_short}")
    w(f"  Compression gate blocked: {total_skipped_compress}")
    w(f"  BTC bearish blocked:      {total_skipped_btc}")
    w("")

    # ── Aggregate stats ──
    if valid:
        avg_ret = sum(r.net_return for r in valid) / len(valid)
        med_ret = sorted(r.net_return for r in valid)[len(valid) // 2]
        avg_wr = sum(r.win_rate for r in valid) / len(valid)
        avg_pf = sum(r.profit_factor for r in valid) / len(valid)
        avg_dd = sum(r.max_drawdown for r in valid) / len(valid)
        avg_fees = sum(r.total_fees for r in valid) / len(valid)
        avg_dur = sum(r.avg_duration for r in valid) / len(valid)
        avg_trades = total_trades / len(valid)

        w("AGGREGATE METRICS")
        w("-" * 50)
        w(f"  Avg Net Return:     {avg_ret:+.1f}%")
        w(f"  Median Net Return:  {med_ret:+.1f}%")
        w(f"  Avg Win Rate:       {avg_wr:.1f}%")
        w(f"  Avg Profit Factor:  {avg_pf:.2f}")
        w(f"  Avg Max Drawdown:   {avg_dd:.1f}%")
        w(f"  Avg Fee Drag:       {avg_fees:.1f}%")
        w(f"  Avg Duration:       {avg_dur:.0f} days")
        w(f"  Avg Trades/Symbol:  {avg_trades:.1f}")
        w("")

    # ── Trade-level stats from log ──
    if all_logs:
        wins = [t for t in all_logs if t.is_win]
        losses = [t for t in all_logs if not t.is_win]
        win_returns = [t.net_return_pct for t in wins]
        loss_returns = [t.net_return_pct for t in losses]

        w("TRADE-LEVEL ANALYSIS (from detailed log)")
        w("-" * 50)
        w(f"  Total trades:       {len(all_logs)}")
        w(f"  Wins:               {len(wins)}  ({len(wins)/len(all_logs)*100:.1f}%)")
        w(f"  Losses:             {len(losses)}  ({len(losses)/len(all_logs)*100:.1f}%)")
        w(f"  Avg win:            {statistics.mean(win_returns):+.2f}%" if wins else "  Avg win:            N/A")
        w(f"  Avg loss:           {statistics.mean(loss_returns):+.2f}%" if losses else "  Avg loss:           N/A")
        w(f"  Biggest win:        {max(win_returns):+.2f}%" if wins else "  Biggest win:        N/A")
        w(f"  Biggest loss:       {min(loss_returns):+.2f}%" if losses else "  Biggest loss:       N/A")
        w(f"  Avg duration:       {statistics.mean([t.duration_days for t in all_logs]):.0f} days")
        w(f"  Median duration:    {sorted([t.duration_days for t in all_logs])[len(all_logs)//2]} days")
        w("")

        # Exit reason breakdown
        exit_reasons: Dict[str, int] = {}
        exit_reasons_win: Dict[str, int] = {}
        for t in all_logs:
            exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1
            if t.is_win:
                exit_reasons_win[t.exit_reason] = exit_reasons_win.get(t.exit_reason, 0) + 1

        w("EXIT REASON BREAKDOWN")
        w("-" * 50)
        w(f"  {'Reason':<25s} {'Count':>6s} {'Win':>6s} {'Win%':>6s}")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            win_count = exit_reasons_win.get(reason, 0)
            win_pct = win_count / count * 100 if count > 0 else 0
            w(f"  {reason:<25s} {count:>6d} {win_count:>6d} {win_pct:>5.1f}%")
        w("")

        # SL distance analysis
        sl_dists = [t.sl_distance_pct for t in all_logs]
        w("STOP-LOSS DISTANCE ANALYSIS")
        w("-" * 50)
        w(f"  Avg SL distance:     {statistics.mean(sl_dists):.2f}%")
        w(f"  Median SL distance:  {sorted(sl_dists)[len(sl_dists)//2]:.2f}%")
        w(f"  Min SL distance:     {min(sl_dists):.2f}%")
        w(f"  Max SL distance:     {max(sl_dists):.2f}%")
        w("")

    # ── Top/Bottom performers ──
    if valid:
        top = sorted(valid, key=lambda r: r.net_return, reverse=True)
        w("TOP 30 SYMBOLS")
        w("-" * 120)
        w(f"  {'Symbol':<15s} {'Trades':>6s} {'WR%':>6s} {'Net%':>9s} {'PF':>6s} {'Sharpe':>7s} {'DD%':>7s} {'AvgDur':>7s} {'SkipCmp':>7s}")
        w(f"  {'-'*15:<15s} {'-'*6:>6s} {'-'*6:>6s} {'-'*9:>9s} {'-'*6:>6s} {'-'*7:>7s} {'-'*7:>7s} {'-'*7:>7s} {'-'*7:>7s}")
        for r in top[:30]:
            w(f"  {r.symbol:<15s} {r.total_trades:>6d} {r.win_rate:>5.1f}% {r.net_return:>+8.1f}% "
              f"{r.profit_factor:>6.2f} {r.sharpe_ratio:>7.2f} {r.max_drawdown:>6.1f}% "
              f"{r.avg_duration:>6.0f}d {r.skipped_no_compress:>7d}")
        w("")

        w("BOTTOM 10 SYMBOLS")
        w("-" * 120)
        for r in top[-10:]:
            w(f"  {r.symbol:<15s} {r.total_trades:>6d} {r.win_rate:>5.1f}% {r.net_return:>+8.1f}% "
              f"{r.profit_factor:>6.2f} {r.sharpe_ratio:>7.2f} {r.max_drawdown:>6.1f}% "
              f"{r.avg_duration:>6.0f}d {r.skipped_no_compress:>7d}")
        w("")

        # Strong candidates
        strong = [r for r in valid
                  if r.profit_factor >= 1.5 and r.net_return >= 20 and r.total_trades >= 5]
        strong.sort(key=lambda r: r.profit_factor, reverse=True)
        w(f"STRONG CANDIDATES (PF≥1.5, Net≥20%, Trades≥5): {len(strong)}")
        w("-" * 120)
        for r in strong:
            w(f"  {r.symbol:<15s} {r.total_trades:>6d} {r.win_rate:>5.1f}% {r.net_return:>+8.1f}% "
              f"{r.profit_factor:>6.2f} {r.sharpe_ratio:>7.2f} {r.max_drawdown:>6.1f}% "
              f"{r.avg_duration:>6.0f}d")
        w("")

    # ── Compression gate impact ──
    w("=" * 100)
    w("V2.1 COMPRESSION GATE IMPACT")
    w("-" * 50)
    w(f"  Total signals blocked:  {total_skipped_compress}")
    w(f"  These would have entered in V2 but were rejected because")
    w(f"  at least one TF's last session was NOT Normal/Neutral/3-1-3")
    w("")

    # Write report
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  Report -> {report_path}")


# ═══════════════════════════════════════════════════════════════
# Ranking Integration
# ═══════════════════════════════════════════════════════════════

def _run_market_filter(results_json_path: str):
    """Run market_filter scoring on the results."""
    try:
        from EA.shared.market_filter import FilterConfig, score_symbols, export_watchlist

        with open(results_json_path) as f:
            data = json.load(f)

        scored = score_symbols(data["results"], FilterConfig())

        watchlist_path = os.path.join(REPORT_DIR, "spot_v21_watchlist.json")
        export_watchlist(scored, watchlist_path)

        print(f"\n{'=' * 80}")
        print(f"MARKET FILTER - Tiered Watchlist (V2.1)")
        print(f"{'-' * 80}")
        tier_counts = {}
        for s in scored:
            tier_counts[s.tier] = tier_counts.get(s.tier, 0) + 1
        for tier in ["Tier 1", "Tier 2", "Tier 3", "Rejected"]:
            print(f"  {tier}: {tier_counts.get(tier, 0)}")
        print(f"  Watchlist saved -> {watchlist_path}")

        elite = [s for s in scored if s.tier in ("Tier 1", "Tier 2")]
        if elite:
            elite.sort(key=lambda s: s.composite_score, reverse=True)
            print(f"\n  {'Symbol':<15s} {'Tier':<8s} {'Score':>6s} {'Ret%':>8s} {'PF':>6s} {'WR%':>6s} {'DD%':>6s}")
            for s in elite[:30]:
                print(f"  {s.symbol:<15s} {s.tier:<8s} {s.composite_score:>5.1f} "
                      f"{s.total_return:>+7.1f}% {s.profit_factor:>5.2f} "
                      f"{s.win_rate:>5.1f}% {s.max_drawdown:>5.1f}%")

    except Exception as e:
        print(f"\n  Market filter failed: {e}")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Macro Trend Catcher Backtest V2.1 — Detailed Trade Log"
    )
    ap.add_argument("--market", choices=["binance", "mt5"], default="binance",
                     help="Data source: binance (LONG-ONLY) or mt5 (LONG+SHORT)")
    ap.add_argument("--groups", nargs="+",
                     help="MT5 asset groups from ASSET_CONFIG (e.g. FOREX_MAJORS COMMODITIES)")
    ap.add_argument("--min-years", type=float, default=3.0)
    ap.add_argument("--cooldown", type=int, default=20)
    ap.add_argument("--sl-mult", type=float, default=None,
                     help="Override SL ATR multiplier (default: per-asset-class)")
    ap.add_argument("--fee", type=float, default=None,
                     help="Fee rate per side (default: 0.001 binance, 0.00005 mt5)")
    ap.add_argument("--no-rank", action="store_true", help="Skip ranking step")
    ap.add_argument("--btc-filter", action="store_true",
                     help="Enable BTC Monthly regime filter: skip LONG entry when BTC is bearish")
    ap.add_argument("--broad-market-filter", action="store_true",
                     help="Enable broad-market bear filter: skip LONG when >=N%% of coins are bearish")
    ap.add_argument("--bear-threshold", type=float, default=0.70,
                     help="Bear threshold for broad-market filter (default: 0.70 = 70%%)")
    ap.add_argument("--signal-version", choices=["v2", "v3"], default="v2",
                     help="v2 = balance-only alignment (legacy), v3 = unified pipeline with breakout_ready")
    ap.add_argument("--soft-sl", action="store_true",
                     help="Soft SL: no hard stop-loss, exit only on Monthly direction flip")
    ap.add_argument("--symbols", nargs="+",
                     help="Specific MT5 symbols to backtest (e.g. XAUUSDm XAGUSDm USOILm)")
    args = ap.parse_args()

    is_mt5 = args.market == "mt5"
    fee_rate = args.fee if args.fee is not None else (MT5_FEE_RATE if is_mt5 else DEFAULT_FEE_RATE)
    allow_short = is_mt5  # MT5 supports SHORT (FX, commodities, etc.)

    config = TrendCatcherV2Config(
        initial_stop_atr_mult=args.sl_mult or 3.0,
        cooldown_days=args.cooldown,
    )

    # ── Build Regime Gate ──
    regime_gate = None
    btc_lookup = None
    if args.btc_filter or args.broad_market_filter:
        print("Building regime filters...")
        t_regime = time.time()
        regime_gate = build_regime_gate(
            btc_filter=args.btc_filter,
            broad_market_filter=args.broad_market_filter,
            bear_threshold=args.bear_threshold,
        )
        regime_time = time.time() - t_regime
        active_names = [f.name for f in regime_gate.filters] if regime_gate else []
        print(f"  Active filters: {', '.join(active_names) or 'none'} ({regime_time:.1f}s)")

        # Show BTC regime stats for backward compat
        if regime_gate and args.btc_filter:
            for f in regime_gate.filters:
                if f.name == "btc_regime":
                    lk = f._lookup
                    if lk:
                        bull_days = sum(1 for v in lk.values() if v == "bullish")
                        bear_days = sum(1 for v in lk.values() if v == "bearish")
                        neut_days = sum(1 for v in lk.values() if v == "neutral")
                        print(f"  BTC regime: {len(lk)} days | "
                              f"Bullish: {bull_days} ({bull_days/len(lk)*100:.0f}%) | "
                              f"Bearish: {bear_days} ({bear_days/len(lk)*100:.0f}%) | "
                              f"Neutral: {neut_days} ({neut_days/len(lk)*100:.0f}%)")

        # Show broad market stats
        if regime_gate and args.broad_market_filter:
            for f in regime_gate.filters:
                if f.name == "broad_market":
                    stats = f._daily_stats
                    bear_days = sum(1 for v in stats.values() if v.get("is_bear"))
                    print(f"  Broad market: {len(stats)} days | "
                          f"Bear days: {bear_days} ({bear_days/len(stats)*100:.0f}%) | "
                          f"Threshold: {args.bear_threshold:.0%} | "
                          f"Universe: {len(f._universe)} coins")

    # ── Build symbol list ──
    if args.symbols:
        # Specific symbols requested — look them up in all ASSET_CONFIG groups
        all_groups = list(ASSET_CONFIG.keys())
        mt5_entries = get_mt5_symbols(all_groups)
        entry_map = {e["symbol"]: e for e in mt5_entries}
        symbols = []
        symbol_configs = {}
        for sym in args.symbols:
            if sym in entry_map:
                symbols.append(sym)
                symbol_configs[sym] = entry_map[sym]
            else:
                # Try loading directly if parquet exists
                path = os.path.join(MT5_DATA_DIR, f"{sym}_H4.parquet")
                if os.path.exists(path):
                    symbols.append(sym)
                    symbol_configs[sym] = {
                        "symbol": sym, "config": COMMODITIES_V2,
                        "has_weekend": sym in MT5_WEEKEND_SYMBOLS,
                    }
                else:
                    print(f"  WARNING: {sym} not found in ASSET_CONFIG or data/mt5/")
        if not is_mt5:
            is_mt5 = True  # force MT5 mode for specific symbols
            fee_rate = MT5_FEE_RATE
            allow_short = True
    elif is_mt5:
        default_groups = ["FOREX_MAJORS", "FOREX_CROSSES", "COMMODITIES"]
        groups = args.groups or default_groups
        mt5_entries = get_mt5_symbols(groups)
        symbols = [e["symbol"] for e in mt5_entries]
        symbol_configs = {e["symbol"]: e for e in mt5_entries}
    else:
        min_bars = int(args.min_years * 252 * 6)  # years → H4 bars
        symbols = get_binance_symbols(min_h4_bars=min_bars)
        symbol_configs = {}

    fee_pct = fee_rate * 100
    mode_str = "MT5 LONG+SHORT" if is_mt5 else "Binance LONG-ONLY"
    sl_mode = "SOFT-SL (M direction flip only)" if args.soft_sl else "HARD SL"
    btc_tag = " + BTC REGIME FILTER" if args.btc_filter else ""
    broad_tag = " + BROAD MARKET FILTER" if args.broad_market_filter else ""
    sig_tag = f" [{args.signal_version.upper()}]" if args.signal_version != "v2" else ""
    soft_tag = " [SOFT-SL]" if args.soft_sl else ""
    print(f"\n{'=' * 90}")
    print(f"  Backtest V2.1 - {mode_str} + COMPRESSION GATE{btc_tag}{broad_tag}{sig_tag}{soft_tag}")
    print(f"{'=' * 90}")
    print(f"  Compression = Normal / Neutral / 3-1-3 (last session per TF must be nen)")
    if is_mt5 and not args.symbols:
        print(f"  Groups:     {', '.join(groups)}")
    if args.btc_filter:
        print(f"  BTC Filter  = Skip LONG entry when BTC Monthly MBA is bearish")
    if args.broad_market_filter:
        print(f"  Broad Mkt   = Skip LONG when >= {args.bear_threshold:.0%} of coins are bearish")
    print(f"  Signal Ver: {args.signal_version.upper():<10s}")
    if args.signal_version == "v3":
        print(f"  V3 Paths:   balance_aligned + breakout_ready (Monthly BREAKOUT + W+D ready)")
    print(f"  Symbols:  {len(symbols):<10d}  Fee/side: {fee_pct:.4f}%  (round-trip: {fee_pct*2:.4f}%)")
    print(f"  SL Mode:  {sl_mode}")
    print(f"  SL Mult:  {'per-asset' if args.sl_mult is None and is_mt5 else str(config.initial_stop_atr_mult):<10s}  Cooldown: {config.cooldown_days}d")
    if args.symbols:
        print(f"  Symbols:  {', '.join(args.symbols)}")
    print(f"{'=' * 90}\n")

    results: List[SpotBacktestResult] = []
    all_trade_logs: List[TradeLogEntry] = []
    t0 = time.time()

    for idx, sym in enumerate(symbols, 1):
        t1 = time.time()

        # Per-symbol config for MT5 (use asset-class specific SL mult)
        sym_config = config
        sym_has_weekend = True
        if is_mt5 and sym in symbol_configs:
            entry = symbol_configs[sym]
            sym_has_weekend = entry["has_weekend"]
            if args.sl_mult is None:
                # Use the asset-class config's SL mult
                sym_config = TrendCatcherV2Config(
                    initial_stop_atr_mult=entry["config"].initial_stop_atr_mult,
                    cooldown_days=args.cooldown,
                )

        res = run_single_backtest(
            sym, sym_config, fee_rate=fee_rate,
            btc_regime_lookup=btc_lookup,
            regime_gate=regime_gate,
            signal_version=args.signal_version,
            market=args.market if not args.symbols else "mt5",
            has_weekend=sym_has_weekend,
            allow_short=allow_short,
            soft_sl=args.soft_sl,
        )
        elapsed = time.time() - t1

        results.append(res)
        all_trade_logs.extend(res.trade_log)

        status = "OK" if not res.error else res.error
        if not res.error and res.total_trades > 0:
            ret_str = f"{res.net_return:+.1f}%"
            dir_str = f" L={res.long_trades} S={res.short_trades}" if allow_short else ""
            skip_str = ""
            if res.skipped_no_compress > 0:
                skip_str = f" cmp_blocked={res.skipped_no_compress}"
            if res.skipped_btc_bearish > 0:
                skip_str += f" regime_blocked={res.skipped_btc_bearish}"
        else:
            ret_str = "-"
            dir_str = ""
            skip_str = ""

        print(
            f"[{idx:3d}/{len(symbols)}] {sym:<15s}  "
            f"trades={res.total_trades:3d}{dir_str}  WR={res.win_rate:5.1f}%  "
            f"net={ret_str:>10s}  PF={res.profit_factor:>5.2f}  "
            f"log={len(res.trade_log):3d}  ({elapsed:.1f}s) {status}{skip_str}"
        )

    total_time = time.time() - t0
    print(f"\nCompleted {len(results)} symbols in {total_time:.0f}s")
    print(f"Total trade log entries: {len(all_trade_logs)}")

    # ── Export trade log ──
    os.makedirs(REPORT_DIR, exist_ok=True)
    mkt_prefix = "mt5_" if is_mt5 else ""
    sig_suffix = f"_{args.signal_version}" if args.signal_version != "v2" else ""
    if args.soft_sl:
        sig_suffix += "_softsl"
    csv_path = os.path.join(REPORT_DIR, f"{mkt_prefix}v21_trade_log{sig_suffix}.csv")
    json_log_path = os.path.join(REPORT_DIR, f"{mkt_prefix}v21_trade_log{sig_suffix}.json")
    export_trade_log(all_trade_logs, csv_path, json_log_path)

    # ── Save per-symbol results JSON (for filter/rank) ──
    valid = [r for r in results if not r.error and r.total_trades >= 3]
    profitable = [r for r in valid if r.net_return > 0]

    results_json_path = os.path.join(REPORT_DIR, f"{mkt_prefix}v21_backtest_results{sig_suffix}.json")
    with open(results_json_path, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "mode": f"{'MT5_LONG_SHORT' if is_mt5 else 'LONG_ONLY_SPOT'}_V21_COMPRESSION_GATE",
                "market": args.market,
                "config": {
                    "signal_version": args.signal_version,
                    "sl_mult": config.initial_stop_atr_mult,
                    "cooldown": config.cooldown_days,
                    "fee_per_side": fee_rate,
                    "fee_round_trip": fee_rate * 2,
                    "min_h4_bars": MIN_H4_BARS_MT5 if is_mt5 else MIN_H4_BARS,
                    "compression_gate": True,
                    "btc_filter": args.btc_filter,
                    "allow_short": allow_short,
                },
                "summary": {
                    "total_symbols": len(symbols),
                    "valid_symbols": len(valid),
                    "profitable_symbols": len(profitable),
                    "total_trades": len(all_trade_logs),
                    "total_skipped_short": sum(r.skipped_short for r in results),
                    "total_skipped_compress": sum(r.skipped_no_compress for r in results),
                    "total_skipped_btc_bearish": sum(r.skipped_btc_bearish for r in results),
                },
                "results": [
                    {
                        "symbol": r.symbol,
                        "trades": r.total_trades,
                        "skipped_short": r.skipped_short,
                        "skipped_compress": r.skipped_no_compress,
                        "skipped_btc_bearish": r.skipped_btc_bearish,
                        "win_rate": round(r.win_rate, 1),
                        "gross_return": round(r.gross_return, 2),
                        "total_return": round(r.net_return, 2),
                        "total_fees": round(r.total_fees, 2),
                        "max_drawdown": round(r.max_drawdown, 2),
                        "profit_factor": round(r.profit_factor, 2),
                        "sharpe_ratio": round(r.sharpe_ratio, 2),
                        "avg_duration": round(r.avg_duration, 1),
                        "data_years": round(r.data_years, 1),
                        "error": r.error,
                    }
                    for r in results
                ],
            },
            f,
            indent=2,
        )
    print(f"  Results JSON -> {results_json_path}")

    # ── Generate text report ──
    report_path = os.path.join(REPORT_DIR, f"{mkt_prefix}v21_summary_report{sig_suffix}.txt")
    generate_report(results, all_trade_logs, config, fee_rate, report_path)

    # ── Run ranking ──
    if not args.no_rank:
        _run_market_filter(results_json_path)

    print(f"\n{'=' * 90}")
    print(f"  ALL DONE - {len(all_trade_logs)} trades logged across {len(valid)} valid symbols ({args.market})")
    print(f"  Open {mkt_prefix}v21_trade_log{sig_suffix}.csv in Excel for entry-level analysis")
    print(f"{'=' * 90}")


if __name__ == "__main__":
    main()
