"""
Binance V3 Backtest — 4 Scenarios Comparison
=============================================

Chạy 4 kịch bản trên toàn bộ dữ liệu Binance (ít nhất 8 năm):

  Scenario A: No filter,  Hard SL  (baseline)
  Scenario B: No filter,  Soft SL  (exit on Monthly direction flip only)
  Scenario C: With filter, Hard SL  (BTC regime + compression gate)
  Scenario D: With filter, Soft SL

  - Signal version  : V3 (current logic — convergence + breakout_ready)
  - Account         : $10,000
  - Risk per trade  : 1% of current equity
  - Position sizing : risk_$ / sl_distance_pct (fixed fractional)
  - Mode            : LONG-ONLY (Binance Spot)
  - Fee             : 0.1% per side (0.2% round-trip)

Usage::

    python -m scripts.research.binance_v3_4scenarios
    python -m scripts.research.binance_v3_4scenarios --min-years 5
    python -m scripts.research.binance_v3_4scenarios --symbols BTC ETH SOL
"""

from __future__ import annotations

import os
import sys
import json
import time
import statistics
import csv
import concurrent.futures
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from EA.macro_trend_catcher.backtest import (
    run_single_backtest,
    build_btc_regime_lookup,
    get_binance_symbols,
    TradeLogEntry,
    SpotBacktestResult,
    DEFAULT_FEE_RATE,
    MIN_H4_BARS,
    BINANCE_DATA_DIR,
    export_trade_log,
)
from EA.macro_trend_catcher.config import TrendCatcherV2Config

import polars as pl

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

ACCOUNT_SIZE   = 10_000.0   # USD
RISK_PCT       = 0.01       # 1% per trade
FEE_RATE       = DEFAULT_FEE_RATE  # 0.1% per side
ROUND_TRIP_FEE = FEE_RATE * 2

# 8 years * 365 days * 6 bars/day (Binance has weekends)
MIN_H4_BARS_8Y = int(8 * 365 * 6)   # 17_520

REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "EA", "macro_trend_catcher", "reports", "v3_4scenarios")

SCENARIOS = [
    {"id": "A", "label": "No Filter  + Hard SL", "soft_sl": False, "btc_filter": False, "require_compression": False},
    {"id": "B", "label": "No Filter  + Soft SL", "soft_sl": True,  "btc_filter": False, "require_compression": False},
    {"id": "C", "label": "With Filter + Hard SL", "soft_sl": False, "btc_filter": True,  "require_compression": True},
    {"id": "D", "label": "With Filter + Soft SL", "soft_sl": True,  "btc_filter": True,  "require_compression": True},
]


# ═══════════════════════════════════════════════════════════════
# Portfolio P&L Simulator ($10k, 1% risk)
# ═══════════════════════════════════════════════════════════════

@dataclass
class PortfolioStats:
    """Equity simulation on a dollar account."""
    scenario_id:       str
    scenario_label:    str
    account_start:     float
    account_end:       float
    total_trades:      int
    win_rate:          float   # %
    profit_factor:     float
    max_drawdown_pct:  float   # as % of peak equity
    max_drawdown_usd:  float
    total_pnl_usd:     float
    avg_win_usd:       float
    avg_loss_usd:      float
    avg_rrr:           float   # avg win / avg |loss|
    sharpe_ratio:      float
    total_fees_usd:    float
    avg_trade_pnl_usd: float


def simulate_portfolio(
    trade_logs: List[TradeLogEntry],
    account_start: float = ACCOUNT_SIZE,
    risk_pct: float = RISK_PCT,
    fee_rate: float = FEE_RATE,
    scenario_id: str = "?",
    scenario_label: str = "?",
) -> PortfolioStats:
    """
    Replay trade log with fixed-fractional position sizing.

    Position size per trade:
        risk_$ = equity * risk_pct
        position_$ = risk_$ / (sl_distance_pct / 100)
        pnl_$ = position_$ * return_pct / 100  — fees

    Fees deducted: position_$ * round_trip_fee_rate
    """
    equity       = account_start
    peak         = account_start
    max_dd_pct   = 0.0
    max_dd_usd   = 0.0
    round_trip   = fee_rate * 2

    pnl_list: List[float] = []
    fee_total = 0.0

    for t in trade_logs:
        sl_dist = t.sl_distance_pct / 100.0
        if sl_dist <= 0:
            continue

        risk_usd     = equity * risk_pct
        position_usd = risk_usd / sl_dist
        gross_pnl    = position_usd * (t.gross_return_pct / 100.0)
        fee_usd      = position_usd * round_trip
        net_pnl      = gross_pnl - fee_usd

        equity   += net_pnl
        fee_total += fee_usd
        pnl_list.append(net_pnl)

        peak = max(peak, equity)
        dd_pct = (peak - equity) / peak * 100 if peak > 0 else 0
        dd_usd = peak - equity
        max_dd_pct = max(max_dd_pct, dd_pct)
        max_dd_usd = max(max_dd_usd, dd_usd)

    if not pnl_list:
        return PortfolioStats(
            scenario_id=scenario_id, scenario_label=scenario_label,
            account_start=account_start, account_end=account_start,
            total_trades=0, win_rate=0, profit_factor=0,
            max_drawdown_pct=0, max_drawdown_usd=0,
            total_pnl_usd=0, avg_win_usd=0, avg_loss_usd=0,
            avg_rrr=0, sharpe_ratio=0, total_fees_usd=0, avg_trade_pnl_usd=0,
        )

    wins   = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]

    win_rate      = len(wins) / len(pnl_list) * 100
    avg_win       = statistics.mean(wins)  if wins   else 0.0
    avg_loss      = statistics.mean(losses) if losses else 0.0
    avg_rrr       = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    total_win     = sum(wins)
    total_loss    = abs(sum(losses)) or 0.001
    profit_factor = total_win / total_loss

    sharpe = 0.0
    if len(pnl_list) > 1:
        avg_p = statistics.mean(pnl_list)
        std_p = statistics.stdev(pnl_list)
        if std_p > 0:
            data_years = len(trade_logs[0].entry_time) if trade_logs else 1  # rough
            tpy = len(pnl_list) / max(1, 1)  # per-trade sharpe (annualised below)
            sharpe = (avg_p / std_p) * (len(pnl_list) ** 0.5)

    return PortfolioStats(
        scenario_id      = scenario_id,
        scenario_label   = scenario_label,
        account_start    = round(account_start, 2),
        account_end      = round(equity, 2),
        total_trades     = len(pnl_list),
        win_rate         = round(win_rate, 1),
        profit_factor    = round(profit_factor, 3),
        max_drawdown_pct = round(max_dd_pct, 2),
        max_drawdown_usd = round(max_dd_usd, 2),
        total_pnl_usd    = round(equity - account_start, 2),
        avg_win_usd      = round(avg_win, 2),
        avg_loss_usd     = round(avg_loss, 2),
        avg_rrr          = round(avg_rrr, 2),
        sharpe_ratio     = round(sharpe, 3),
        total_fees_usd   = round(fee_total, 2),
        avg_trade_pnl_usd= round(statistics.mean(pnl_list) if pnl_list else 0, 2),
    )


def _run_one_symbol(
    sym: str,
    config: TrendCatcherV2Config,
    btc_lookup: Optional[Dict],
    use_btc: bool,
    soft_sl: bool,
    req_cmp: bool,
) -> Tuple[str, SpotBacktestResult, float]:
    """Worker function — runs backtest for a single symbol."""
    t0 = time.time()
    res = run_single_backtest(
        symbol              = sym,
        config              = config,
        fee_rate            = FEE_RATE,
        btc_regime_lookup   = btc_lookup if use_btc else None,
        signal_version      = "v3",
        market              = "binance",
        has_weekend         = True,
        allow_short         = False,
        soft_sl             = soft_sl,
        require_compression = req_cmp,
    )
    return sym, res, time.time() - t0


# ═══════════════════════════════════════════════════════════════
# Runners
# ═══════════════════════════════════════════════════════════════

def get_symbols_8y(min_h4_bars: int = MIN_H4_BARS_8Y) -> List[str]:
    """
    Return Binance symbols with at least *min_h4_bars* of H4 data.
    Falls back to MIN_H4_BARS_8Y if no symbol meets that threshold —
    in that case returns all available symbols (data may be <8 years).
    """
    from EA.macro_trend_catcher.backtest import SKIP_SYMBOLS
    files = [f for f in os.listdir(BINANCE_DATA_DIR) if f.endswith("_USDT_H4.parquet")]
    symbols = []
    for f in sorted(files):
        sym = f.replace("_USDT_H4.parquet", "")
        if sym in SKIP_SYMBOLS:
            continue
        path = os.path.join(BINANCE_DATA_DIR, f)
        try:
            n = pl.scan_parquet(path).select(pl.len()).collect().item()
            if n >= min_h4_bars:
                symbols.append(sym)
        except Exception:
            continue

    if not symbols:
        print(f"  [WARN] No symbols found with {min_h4_bars} bars. "
              f"Falling back to default threshold {MIN_H4_BARS}.")
        return get_binance_symbols()

    return symbols


def run_scenario(
    scenario: Dict,
    symbols: List[str],
    btc_lookup: Optional[Dict],
    config: TrendCatcherV2Config,
    min_years: float,
    workers: int = 4,
) -> tuple[List[SpotBacktestResult], List[TradeLogEntry]]:
    """Run one scenario with concurrent per-symbol execution (ThreadPoolExecutor)."""
    sid = scenario["id"]
    label = scenario["label"]
    soft_sl = scenario["soft_sl"]
    use_btc = scenario["btc_filter"]
    req_cmp = scenario["require_compression"]

    print(f"\n{'\u2500' * 80}")
    print(f"  SCENARIO {sid}: {label}")
    print(f"{'\u2500' * 80}")

    results: List[SpotBacktestResult] = []
    logs: List[TradeLogEntry] = []
    total = len(symbols)
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_run_one_symbol, sym, config, btc_lookup, use_btc, soft_sl, req_cmp): sym
            for sym in symbols
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                sym, res, elapsed = fut.result()
                completed += 1
                results.append(res)
                logs.extend(res.trade_log)

                if not res.error and res.total_trades > 0:
                    ret_str  = f"{res.net_return:+.1f}%"
                    skip_str = ""
                    if res.skipped_no_compress > 0:
                        skip_str += f" cmp={res.skipped_no_compress}"
                    if res.skipped_btc_bearish > 0:
                        skip_str += f" btc={res.skipped_btc_bearish}"
                else:
                    ret_str  = f"[{res.error or 'no_trades'}]"
                    skip_str = ""

                print(
                    f"  [{completed:3d}/{total}] {sym:<12s}  "
                    f"trades={res.total_trades:3d}  WR={res.win_rate:5.1f}%  "
                    f"net={ret_str:>10s}  PF={res.profit_factor:>5.2f}  "
                    f"({elapsed:.1f}s){skip_str}"
                )
            except Exception as exc:
                completed += 1
                sym = futures[fut]
                print(f"  [ERR] {sym}: {exc}")

    return results, logs


# ═══════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════

def print_comparison_table(portfolio_stats: List[PortfolioStats]):
    """Print a side-by-side comparison of all 4 scenarios."""
    print(f"\n{'=' * 120}")
    print("  4-SCENARIO COMPARISON  |  Account: ${:,.0f}  |  Risk: {:.0%}/trade  |  Binance LONG-ONLY  |  Signal V3".format(
        ACCOUNT_SIZE, RISK_PCT
    ))
    print(f"{'=' * 120}")
    hdr = (
        f"  {'Scenario':<26s} {'Trades':>7s} {'WR%':>6s} "
        f"{'PF':>6s} {'Sharpe':>7s} "
        f"{'Acct End':>10s} {'P&L $':>10s} {'P&L%':>8s} "
        f"{'MaxDD%':>8s} {'MaxDD$':>9s} "
        f"{'AvgWin$':>9s} {'AvgLoss$':>10s} {'RRR':>5s} "
        f"{'Fees$':>8s}"
    )
    print(hdr)
    print(f"  {'-' * 116}")
    for ps in portfolio_stats:
        pnl_pct = ps.total_pnl_usd / ACCOUNT_SIZE * 100
        print(
            f"  [{ps.scenario_id}] {ps.scenario_label:<22s} "
            f"{ps.total_trades:>7d} {ps.win_rate:>5.1f}% "
            f"{ps.profit_factor:>6.2f} {ps.sharpe_ratio:>7.2f} "
            f"${ps.account_end:>9,.0f} {ps.total_pnl_usd:>+10,.0f} {pnl_pct:>+7.1f}% "
            f"{ps.max_drawdown_pct:>7.1f}% ${ps.max_drawdown_usd:>8,.0f} "
            f"${ps.avg_win_usd:>8,.0f} ${ps.avg_loss_usd:>9,.0f} {ps.avg_rrr:>5.2f} "
            f"${ps.total_fees_usd:>7,.0f}"
        )
    print(f"{'=' * 120}\n")


def generate_comparison_report(
    portfolio_stats: List[PortfolioStats],
    scenario_results: Dict[str, List[SpotBacktestResult]],
    scenario_logs: Dict[str, List[TradeLogEntry]],
    report_path: str,
):
    lines = []
    w = lines.append
    w("=" * 120)
    w("MACRO TREND CATCHER V3 — BINANCE SPOT — 4-SCENARIO COMPARISON")
    w(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w(f"Account   : ${ACCOUNT_SIZE:,.0f}   Risk/trade: {RISK_PCT:.0%}   Fee: {FEE_RATE*100:.2f}%/side")
    w(f"Signal    : V3 (convergence + breakout_ready)")
    w(f"Data      : Binance SPOT LONG-ONLY  (≥8 years H4)")
    w("=" * 120)
    w("")

    w("SCENARIO DEFINITIONS")
    w("-" * 60)
    for s in SCENARIOS:
        btc_tag  = "BTC regime filter ON" if s["btc_filter"] else "No BTC filter"
        cmp_tag  = "(compression gate: Normal/Neutral/3-1-3)"
        sl_tag   = "Soft SL (M flip only)" if s["soft_sl"] else "Hard SL (3× ATR)"
        w(f"  [{s['id']}] {s['label']:<26s} | {sl_tag}  |  {btc_tag}  {cmp_tag if s['btc_filter'] else ''}")
    w("")

    w("PORTFOLIO METRICS  ($10k account, 1% risk fixed-fractional)")
    w("-" * 120)
    w(f"  {'Scenario':<26s} {'Trades':>7s} {'WR%':>6s} {'PF':>6s} {'Sharpe':>7s} "
      f"{'Acct End':>10s} {'P&L $':>10s} {'P&L%':>8s} "
      f"{'MaxDD%':>8s} {'MaxDD$':>9s} {'AvgWin$':>9s} {'AvgLoss$':>10s} {'RRR':>5s} {'Fees$':>8s}")
    w("-" * 120)
    for ps in portfolio_stats:
        pnl_pct = ps.total_pnl_usd / ACCOUNT_SIZE * 100
        w(
            f"  [{ps.scenario_id}] {ps.scenario_label:<22s} "
            f"{ps.total_trades:>7d} {ps.win_rate:>5.1f}% "
            f"{ps.profit_factor:>6.2f} {ps.sharpe_ratio:>7.2f} "
            f"${ps.account_end:>9,.0f} {ps.total_pnl_usd:>+10,.0f} {pnl_pct:>+7.1f}% "
            f"{ps.max_drawdown_pct:>7.1f}% ${ps.max_drawdown_usd:>8,.0f} "
            f"${ps.avg_win_usd:>8,.0f} ${ps.avg_loss_usd:>9,.0f} {ps.avg_rrr:>5.2f} "
            f"${ps.total_fees_usd:>7,.0f}"
        )
    w("")

    # Per-scenario detail
    for ps in portfolio_stats:
        sc_id  = ps.scenario_id
        logs   = scenario_logs.get(sc_id, [])
        res_list = scenario_results.get(sc_id, [])
        valid  = [r for r in res_list if not r.error and r.total_trades >= 3]

        w("=" * 120)
        w(f"SCENARIO {sc_id}: {ps.scenario_label}")
        w("-" * 120)

        if valid:
            top = sorted(valid, key=lambda r: r.net_return, reverse=True)
            w(f"  Valid symbols: {len(valid)}  |  Profitable: {sum(1 for r in valid if r.net_return>0)}")
            w(f"  {'Symbol':<14s} {'Trades':>6s} {'WR%':>6s} {'Net%':>9s} {'PF':>6s} {'Sharpe':>7s} {'DD%':>7s} {'AvgDur':>7s}")
            for r in top[:20]:
                w(f"  {r.symbol:<14s} {r.total_trades:>6d} {r.win_rate:>5.1f}% "
                  f"{r.net_return:>+8.1f}% {r.profit_factor:>6.2f} "
                  f"{r.sharpe_ratio:>7.2f} {r.max_drawdown:>6.1f}% {r.avg_duration:>6.0f}d")

        if logs:
            exits = {}
            for t in logs:
                exits[t.exit_reason] = exits.get(t.exit_reason, 0) + 1
            w(f"\n  Exit breakdown:")
            for reason, cnt in sorted(exits.items(), key=lambda x: -x[1]):
                pct = cnt / len(logs) * 100
                w(f"    {reason:<30s} {cnt:>5d}  ({pct:.1f}%)")
        w("")

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  Report -> {report_path}")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Binance V3 Backtest — 4 Scenarios")
    ap.add_argument("--min-years", type=float, default=8.0,
                    help="Minimum data years per symbol (default: 8)")
    ap.add_argument("--all", action="store_true",
                    help="Run ALL Binance symbols with >=2y data (overrides --min-years)")
    ap.add_argument("--symbols", nargs="+",
                    help="Override symbol list (e.g. BTC ETH SOL)")
    ap.add_argument("--cooldown", type=int, default=20)
    ap.add_argument("--sl-mult", type=float, default=3.0)
    ap.add_argument("--workers", type=int, default=4,
                    help="Parallel worker processes per scenario (default: 4)")
    ap.add_argument("--scenarios", nargs="+", choices=["A","B","C","D"],
                    default=["A","B","C","D"],
                    help="Subset of scenarios to run (default: all)")
    args = ap.parse_args()

    os.makedirs(REPORT_DIR, exist_ok=True)
    config = TrendCatcherV2Config(
        initial_stop_atr_mult=args.sl_mult,
        cooldown_days=args.cooldown,
    )

    # ── Symbol list ──
    if args.symbols:
        symbols = args.symbols
        print(f"\nSymbols (manual): {symbols}")
    elif args.all:
        print("\nLoading ALL Binance symbols with >=2y data...")
        symbols = get_binance_symbols()
        print(f"  Found {len(symbols)} qualifying symbols")
    else:
        min_bars = int(args.min_years * 365 * 6)
        print(f"\nScanning Binance data for symbols with >={args.min_years:.0f} years "
              f"({min_bars:,} H4 bars)...")
        symbols = get_symbols_8y(min_bars)
        print(f"  Found {len(symbols)} qualifying symbols: {', '.join(symbols[:20])}"
              f"{'...' if len(symbols) > 20 else ''}")

    if not symbols:
        print("ERROR: No symbols found. Check data/binance/ directory.")
        return

    # ── Build BTC lookup (needed for scenarios C & D) ──
    run_with_filter = any(SCENARIOS[ord(s)-ord("A")]["btc_filter"]
                          for s in args.scenarios)
    btc_lookup = None
    if run_with_filter:
        print("\nBuilding BTC Monthly regime lookup (for filter scenarios)...")
        t0 = time.time()
        btc_lookup = build_btc_regime_lookup()
        if btc_lookup:
            bull = sum(1 for v in btc_lookup.values() if v == "bullish")
            bear = sum(1 for v in btc_lookup.values() if v == "bearish")
            neut = sum(1 for v in btc_lookup.values() if v == "neutral")
            n = len(btc_lookup)
            print(f"  BTC regime: {n} days | "
                  f"Bull={bull} ({bull/n*100:.0f}%) "
                  f"Bear={bear} ({bear/n*100:.0f}%) "
                  f"Neutral={neut} ({neut/n*100:.0f}%)  "
                  f"({time.time()-t0:.1f}s)")

    print(f"\n{'=' * 80}")
    print(f"  CONFIG: SL={args.sl_mult}×ATR  Cooldown={args.cooldown}d  "
          f"Fee={FEE_RATE*100:.2f}%/side  Account=${ACCOUNT_SIZE:,.0f}  Risk={RISK_PCT:.0%}")
    print(f"  Symbols: {len(symbols)}  Workers/scenario: {args.workers}")
    print(f"  Scenarios to run: {args.scenarios}")
    print(f"{'=' * 80}")

    # ── Run scenarios ──
    all_portfolio_stats: List[PortfolioStats]         = []
    scenario_results:    Dict[str, List[SpotBacktestResult]] = {}
    scenario_logs:       Dict[str, List[TradeLogEntry]]      = {}

    total_t0 = time.time()

    for sc in SCENARIOS:
        if sc["id"] not in args.scenarios:
            continue

        t_sc = time.time()
        res_list, logs = run_scenario(sc, symbols, btc_lookup, config, args.min_years, workers=args.workers)
        sc_time = time.time() - t_sc

        scenario_results[sc["id"]] = res_list
        scenario_logs[sc["id"]]    = logs

        # Simulate portfolio P&L
        # Sort logs by entry_time for correct equity curve
        logs_sorted = sorted(logs, key=lambda t: t.entry_time)
        ps = simulate_portfolio(
            logs_sorted,
            account_start  = ACCOUNT_SIZE,
            risk_pct       = RISK_PCT,
            fee_rate       = FEE_RATE,
            scenario_id    = sc["id"],
            scenario_label = sc["label"],
        )
        all_portfolio_stats.append(ps)

        print(f"\n  Scenario {sc['id']} done in {sc_time:.0f}s: "
              f"{len(logs)} trades | ${ps.account_end:,.0f} final equity | "
              f"P&L: ${ps.total_pnl_usd:+,.0f} ({ps.total_pnl_usd/ACCOUNT_SIZE*100:+.1f}%) | "
              f"MaxDD: {ps.max_drawdown_pct:.1f}%")

        # Export per-scenario trade log CSV
        logs_with_dollar = logs_sorted  # raw log
        csv_path  = os.path.join(REPORT_DIR, f"scenario_{sc['id']}_trade_log.csv")
        json_path = os.path.join(REPORT_DIR, f"scenario_{sc['id']}_trade_log.json")
        export_trade_log(logs_sorted, csv_path, json_path)

    total_time = time.time() - total_t0
    print(f"\nAll scenarios completed in {total_time:.0f}s")

    # ── Print comparison table ──
    print_comparison_table(all_portfolio_stats)

    # ── Generate comparison report ──
    report_path = os.path.join(REPORT_DIR, "comparison_report.txt")
    generate_comparison_report(
        all_portfolio_stats,
        scenario_results,
        scenario_logs,
        report_path,
    )

    # ── Save portfolio summary JSON ──
    summary_path = os.path.join(REPORT_DIR, "portfolio_summary.json")
    with open(summary_path, "w") as f:
        json.dump({
            "generated": datetime.now().isoformat(),
            "account_size": ACCOUNT_SIZE,
            "risk_pct": RISK_PCT,
            "fee_per_side": FEE_RATE,
            "signal_version": "v3",
            "symbols_tested": symbols,
            "scenarios": [asdict(ps) for ps in all_portfolio_stats],
        }, f, indent=2)
    print(f"  Portfolio summary -> {summary_path}")

    print(f"\n  Output dir: {REPORT_DIR}")


if __name__ == "__main__":
    main()
