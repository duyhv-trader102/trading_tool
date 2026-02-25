"""
Trend Catcher V2 -- Market Filter & Symbol Ranking
===================================================

Reads batch backtest results (``reports/binance_batch_results.json``)
and produces a tiered watchlist of symbols worth trading, scored by
a composite quality metric.

Pipeline::

    backtest_binance.py → binance_batch_results.json → market_filter.py → watchlist.json

Tiers
-----
- **Tier 1 (Elite)**:  Score ≥ 70 — trade with full conviction
- **Tier 2 (Strong)**: Score ≥ 50 — normal position size
- **Tier 3 (Watch)**:  Score ≥ 35 — monitor, smaller size
- **Rejected**:        Below 35  — do not trade

Hard Filters (must pass ALL):
    * Trades ≥ 7
    * Data history ≥ 3 years
    * Profit Factor ≥ 1.3
    * Max Drawdown ≤ 95%

Scoring Dimensions (weighted composite 0-100):
    1. Return/Year    (25%) — annualized profitability
    2. Profit Factor  (25%) — reward-to-risk ratio
    3. Sharpe Ratio   (20%) — risk-adjusted consistency
    4. Win Rate       (10%) — hit rate
    5. Trade Count    (10%) — statistical confidence
    6. Drawdown Risk  (10%) — capital preservation (inverted)

Outputs:
    * Console: tiered report with rankings
    * JSON: ``reports/watchlist.json`` for bot/scanner consumption

Usage::

    python -m EA.macro_trend_catcher.v2.market_filter
    python -m EA.macro_trend_catcher.v2.market_filter --min-trades 8 --min-years 4
    python -m EA.macro_trend_catcher.v2.market_filter --export watchlist.json
"""

import json
import os
import sys
import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

@dataclass
class FilterConfig:
    """Configurable filter thresholds."""

    # ── Hard filters (must pass ALL to be considered) ──
    min_trades: int = 7              # statistical minimum
    min_data_years: float = 3.0      # enough history
    min_profit_factor: float = 1.3   # must have positive edge
    min_total_return: float = 0.0    # at least break-even
    max_drawdown_limit: float = 95.0 # reject symbols that lost almost everything

    # ── Scoring weights (must sum to 1.0) ──
    w_return_per_year: float = 0.25
    w_profit_factor: float = 0.25
    w_sharpe: float = 0.20
    w_win_rate: float = 0.10
    w_trade_count: float = 0.10
    w_drawdown: float = 0.10

    # ── Tier thresholds (composite score 0-100) ──
    tier1_min_score: float = 70.0    # Elite
    tier2_min_score: float = 50.0    # Strong
    tier3_min_score: float = 35.0    # Watch
    # Below tier3 → Rejected

    # ── Bonus / Penalty rules ──
    long_history_bonus_years: float = 8.0   # bonus for >8 years data
    high_dd_penalty_threshold: float = 80.0 # penalty for DD > 80%


# ═══════════════════════════════════════════════════════════════
# Scoring Engine
# ═══════════════════════════════════════════════════════════════

def _normalize(value: float, lo: float, hi: float) -> float:
    """Normalize value to 0-100 range with clipping."""
    if hi <= lo:
        return 50.0
    score = (value - lo) / (hi - lo) * 100.0
    return max(0.0, min(100.0, score))


def _normalize_inverted(value: float, lo: float, hi: float) -> float:
    """Lower is better (e.g., drawdown)."""
    return 100.0 - _normalize(value, lo, hi)


@dataclass
class ScoredSymbol:
    """A symbol with its composite quality score."""
    symbol: str
    tier: str                  # "Tier 1", "Tier 2", "Tier 3", "Rejected"
    composite_score: float     # 0-100
    # Raw metrics
    trades: int = 0
    win_rate: float = 0.0
    total_return: float = 0.0
    return_per_year: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    data_years: float = 0.0
    avg_duration: float = 0.0
    # Sub-scores
    score_return: float = 0.0
    score_pf: float = 0.0
    score_sharpe: float = 0.0
    score_wr: float = 0.0
    score_trades: float = 0.0
    score_dd: float = 0.0
    # Adjustments
    bonus: float = 0.0
    penalty: float = 0.0
    reject_reason: str = ""


def score_symbols(
    results: List[Dict],
    config: FilterConfig,
) -> List[ScoredSymbol]:
    """Score and rank all symbols from backtest results."""

    # ── Step 1: Hard filter ──
    candidates = []
    rejected = []

    for r in results:
        sym = ScoredSymbol(
            symbol=r["symbol"],
            tier="",
            composite_score=0.0,
            trades=r["trades"],
            win_rate=r["win_rate"],
            total_return=r["total_return"],
            return_per_year=r["total_return"] / r["data_years"] if r["data_years"] > 0 else 0,
            max_drawdown=r["max_drawdown"],
            profit_factor=min(r["profit_factor"], 50.0),  # cap outliers
            sharpe_ratio=r["sharpe_ratio"],
            data_years=r["data_years"],
            avg_duration=r.get("avg_duration", 0),
        )

        # Hard rejection checks
        if r.get("error", ""):
            sym.tier = "Rejected"
            sym.reject_reason = f"error: {r['error']}"
            rejected.append(sym)
            continue

        if sym.trades < config.min_trades:
            sym.tier = "Rejected"
            sym.reject_reason = f"too few trades ({sym.trades} < {config.min_trades})"
            rejected.append(sym)
            continue

        if sym.data_years < config.min_data_years:
            sym.tier = "Rejected"
            sym.reject_reason = f"insufficient history ({sym.data_years:.1f}y < {config.min_data_years}y)"
            rejected.append(sym)
            continue

        if sym.profit_factor < config.min_profit_factor:
            sym.tier = "Rejected"
            sym.reject_reason = f"low PF ({sym.profit_factor:.2f} < {config.min_profit_factor})"
            rejected.append(sym)
            continue

        if sym.total_return < config.min_total_return:
            sym.tier = "Rejected"
            sym.reject_reason = f"negative return ({sym.total_return:.1f}%)"
            rejected.append(sym)
            continue

        if sym.max_drawdown > config.max_drawdown_limit:
            sym.tier = "Rejected"
            sym.reject_reason = f"extreme drawdown ({sym.max_drawdown:.1f}%)"
            rejected.append(sym)
            continue

        candidates.append(sym)

    if not candidates:
        return rejected

    # ── Step 2: Calculate normalization ranges from candidates ──
    # Using percentile-based ranges for robustness
    rpy_vals = sorted([s.return_per_year for s in candidates])
    pf_vals = sorted([s.profit_factor for s in candidates])
    sharpe_vals = sorted([s.sharpe_ratio for s in candidates])
    wr_vals = sorted([s.win_rate for s in candidates])
    trade_vals = sorted([s.trades for s in candidates])
    dd_vals = sorted([s.max_drawdown for s in candidates])

    def p(vals, pct):
        idx = min(int(len(vals) * pct), len(vals) - 1)
        return vals[idx]

    # Normalization ranges: [5th percentile, 95th percentile]
    rpy_range = (p(rpy_vals, 0.05), p(rpy_vals, 0.95))
    pf_range = (p(pf_vals, 0.05), p(pf_vals, 0.95))
    sharpe_range = (p(sharpe_vals, 0.05), p(sharpe_vals, 0.95))
    wr_range = (p(wr_vals, 0.05), p(wr_vals, 0.95))
    trade_range = (p(trade_vals, 0.05), p(trade_vals, 0.95))
    dd_range = (p(dd_vals, 0.05), p(dd_vals, 0.95))

    # ── Step 3: Score each candidate ──
    for sym in candidates:
        sym.score_return = _normalize(sym.return_per_year, rpy_range[0], rpy_range[1])
        sym.score_pf = _normalize(sym.profit_factor, pf_range[0], pf_range[1])
        sym.score_sharpe = _normalize(sym.sharpe_ratio, sharpe_range[0], sharpe_range[1])
        sym.score_wr = _normalize(sym.win_rate, wr_range[0], wr_range[1])
        sym.score_trades = _normalize(sym.trades, trade_range[0], trade_range[1])
        sym.score_dd = _normalize_inverted(sym.max_drawdown, dd_range[0], dd_range[1])

        # Weighted composite
        raw_score = (
            sym.score_return * config.w_return_per_year
            + sym.score_pf * config.w_profit_factor
            + sym.score_sharpe * config.w_sharpe
            + sym.score_wr * config.w_win_rate
            + sym.score_trades * config.w_trade_count
            + sym.score_dd * config.w_drawdown
        )

        # ── Bonus: long history adds confidence ──
        if sym.data_years >= config.long_history_bonus_years:
            extra_years = sym.data_years - config.long_history_bonus_years
            sym.bonus = min(extra_years * 1.5, 8.0)  # up to +8 points

        # ── Penalty: extreme drawdown ──
        if sym.max_drawdown > config.high_dd_penalty_threshold:
            excess = sym.max_drawdown - config.high_dd_penalty_threshold
            sym.penalty = min(excess * 0.5, 10.0)  # up to -10 points

        sym.composite_score = max(0.0, min(100.0, raw_score + sym.bonus - sym.penalty))

        # ── Assign tier ──
        if sym.composite_score >= config.tier1_min_score:
            sym.tier = "Tier 1"
        elif sym.composite_score >= config.tier2_min_score:
            sym.tier = "Tier 2"
        elif sym.composite_score >= config.tier3_min_score:
            sym.tier = "Tier 3"
        else:
            sym.tier = "Rejected"
            sym.reject_reason = f"low score ({sym.composite_score:.1f})"

    # Sort by composite score
    candidates.sort(key=lambda s: s.composite_score, reverse=True)
    rejected.sort(key=lambda s: s.composite_score, reverse=True)

    return candidates + rejected


# ═══════════════════════════════════════════════════════════════
# Report Generator
# ═══════════════════════════════════════════════════════════════

def print_report(scored: List[ScoredSymbol], config: FilterConfig):
    """Print a formatted market filter report."""

    tiers = {
        "Tier 1": [s for s in scored if s.tier == "Tier 1"],
        "Tier 2": [s for s in scored if s.tier == "Tier 2"],
        "Tier 3": [s for s in scored if s.tier == "Tier 3"],
        "Rejected": [s for s in scored if s.tier == "Rejected"],
    }

    total = len(scored)
    print()
    print("=" * 90)
    print("  MARKET FILTER — SYMBOL SELECTION REPORT")
    print("=" * 90)
    print(f"  Total symbols analyzed: {total}")
    print(f"  Tier 1 (Elite):   {len(tiers['Tier 1']):>3d}  — trade with full conviction")
    print(f"  Tier 2 (Strong):  {len(tiers['Tier 2']):>3d}  — normal position size")
    print(f"  Tier 3 (Watch):   {len(tiers['Tier 3']):>3d}  — monitor, smaller size")
    print(f"  Rejected:         {len(tiers['Rejected']):>3d}  — do not trade")
    print()
    print(f"  Hard filters: trades>={config.min_trades}, years>={config.min_data_years}, "
          f"PF>={config.min_profit_factor}, DD<={config.max_drawdown_limit}%")
    print(f"  Scoring: Ret/Yr({config.w_return_per_year:.0%}) + PF({config.w_profit_factor:.0%}) "
          f"+ Sharpe({config.w_sharpe:.0%}) + WR({config.w_win_rate:.0%}) "
          f"+ Trades({config.w_trade_count:.0%}) + DD({config.w_drawdown:.0%})")
    print(f"  Tier cutoffs: T1>={config.tier1_min_score}, T2>={config.tier2_min_score}, T3>={config.tier3_min_score}")

    header = (
        f"  {'#':>3s} {'Symbol':<10s} {'Score':>5s} "
        f"{'Ret%':>8s} {'Ret/Yr':>7s} {'PF':>6s} {'Sharpe':>6s} "
        f"{'WR%':>5s} {'Trades':>6s} {'MaxDD%':>7s} {'Years':>5s} {'AvgD':>5s}"
    )

    for tier_name in ["Tier 1", "Tier 2", "Tier 3"]:
        tier_list = tiers[tier_name]
        if not tier_list:
            continue

        emoji = {"Tier 1": "***", "Tier 2": "**", "Tier 3": "*"}[tier_name]
        print()
        print(f"  {'=' * 86}")
        print(f"  {emoji} {tier_name.upper()} ({len(tier_list)} symbols) {emoji}")
        print(f"  {'=' * 86}")
        print(header)
        print(f"  {'-' * 86}")

        for rank, s in enumerate(tier_list, 1):
            pf_str = f"{s.profit_factor:>6.2f}" if s.profit_factor < 50 else "  INF "
            print(
                f"  {rank:>3d} {s.symbol:<10s} {s.composite_score:>5.1f} "
                f"{s.total_return:>+8.1f} {s.return_per_year:>+7.1f} {pf_str} {s.sharpe_ratio:>6.2f} "
                f"{s.win_rate*100:>5.0f} {s.trades:>6d} {s.max_drawdown:>7.1f} {s.data_years:>5.1f} {s.avg_duration:>5.0f}"
            )

    # ── Rejection summary ──
    rej = tiers["Rejected"]
    if rej:
        print()
        print(f"  {'=' * 86}")
        print(f"  REJECTED ({len(rej)} symbols)")
        print(f"  {'=' * 86}")

        # Group by reason
        reasons = {}
        for s in rej:
            key = s.reject_reason.split("(")[0].strip() if s.reject_reason else "unknown"
            reasons.setdefault(key, []).append(s.symbol)

        for reason, syms in sorted(reasons.items(), key=lambda x: -len(x[1])):
            sym_list = ", ".join(sorted(syms)[:15])
            extra = f" +{len(syms)-15} more" if len(syms) > 15 else ""
            print(f"  {reason} ({len(syms)}): {sym_list}{extra}")

    # ── Tier 1 summary for quick reference ──
    t1 = tiers["Tier 1"]
    if t1:
        print()
        print(f"  {'=' * 86}")
        print(f"  QUICK WATCHLIST — TIER 1 ELITE ({len(t1)} symbols)")
        print(f"  {'=' * 86}")
        print(f"  {', '.join(s.symbol for s in t1)}")
        if len(t1) > 0:
            avg_ret = sum(s.return_per_year for s in t1) / len(t1)
            avg_pf = sum(s.profit_factor for s in t1) / len(t1)
            avg_dd = sum(s.max_drawdown for s in t1) / len(t1)
            avg_wr = sum(s.win_rate for s in t1) / len(t1)
            print(f"  Avg Ret/Yr: {avg_ret:+.1f}%  |  Avg PF: {avg_pf:.2f}  |  "
                  f"Avg WR: {avg_wr*100:.0f}%  |  Avg MaxDD: {avg_dd:.1f}%")

    # All tradeable
    tradeable = tiers["Tier 1"] + tiers["Tier 2"] + tiers["Tier 3"]
    if tradeable:
        print()
        print(f"  TOTAL TRADEABLE: {len(tradeable)} symbols")
        print(f"  Recommended focus: Tier 1 + Tier 2 = {len(tiers['Tier 1']) + len(tiers['Tier 2'])} symbols")

    print()


def export_watchlist(scored: List[ScoredSymbol], filepath: str):
    """Export watchlist to JSON for use by bot/scanner."""
    tradeable = [s for s in scored if s.tier in ("Tier 1", "Tier 2", "Tier 3")]

    watchlist = {
        "generated": __import__("datetime").datetime.now().isoformat(),
        "total_tradeable": len(tradeable),
        "tiers": {
            "tier_1": [s.symbol for s in tradeable if s.tier == "Tier 1"],
            "tier_2": [s.symbol for s in tradeable if s.tier == "Tier 2"],
            "tier_3": [s.symbol for s in tradeable if s.tier == "Tier 3"],
        },
        "symbols": [
            {
                "symbol": s.symbol,
                "tier": s.tier,
                "score": round(s.composite_score, 1),
                "return_pct": round(s.total_return, 1),
                "return_per_year": round(s.return_per_year, 1),
                "profit_factor": round(s.profit_factor, 2),
                "sharpe_ratio": round(s.sharpe_ratio, 2),
                "win_rate": round(s.win_rate, 2),
                "trades": s.trades,
                "max_drawdown": round(s.max_drawdown, 1),
                "data_years": round(s.data_years, 1),
                "avg_duration_days": round(s.avg_duration, 1),
            }
            for s in tradeable
        ],
    }

    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(watchlist, f, indent=2)
    print(f"  Watchlist exported -> {filepath}")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Market Filter — Symbol Selection")
    ap.add_argument("--results", type=str,
                    default=os.path.join(os.path.dirname(__file__), "reports", "binance_batch_results.json"),
                    help="Path to backtest results JSON")
    ap.add_argument("--min-trades", type=int, default=7)
    ap.add_argument("--min-years", type=float, default=3.0)
    ap.add_argument("--min-pf", type=float, default=1.3)
    ap.add_argument("--max-dd", type=float, default=95.0)
    ap.add_argument("--tier1", type=float, default=70.0, help="Tier 1 score cutoff")
    ap.add_argument("--tier2", type=float, default=50.0, help="Tier 2 score cutoff")
    ap.add_argument("--tier3", type=float, default=35.0, help="Tier 3 score cutoff")
    ap.add_argument("--export", type=str, default=None,
                    help="Export watchlist JSON (default: reports/watchlist.json)")
    args = ap.parse_args()

    # Load results
    with open(args.results) as f:
        data = json.load(f)

    print(f"  Loaded {len(data['results'])} symbols from {args.results}")
    print(f"  Backtest config: SL={data['config']['sl_mult']}x ATR, "
          f"cooldown={data['config']['cooldown']}d")

    config = FilterConfig(
        min_trades=args.min_trades,
        min_data_years=args.min_years,
        min_profit_factor=args.min_pf,
        max_drawdown_limit=args.max_dd,
        tier1_min_score=args.tier1,
        tier2_min_score=args.tier2,
        tier3_min_score=args.tier3,
    )

    # Score & rank
    scored = score_symbols(data["results"], config)

    # Report
    print_report(scored, config)

    # Export
    export_path = args.export or os.path.join(
        os.path.dirname(__file__), "reports", "watchlist.json"
    )
    export_watchlist(scored, export_path)


if __name__ == "__main__":
    main()
