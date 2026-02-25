"""
Commodity Soft-SL vs Hard-SL Analysis
======================================
Compare V3 backtest results on XAUUSDm, XAGUSDm, USOILm
- Hard SL: 3×ATR Daily stop-loss + Monthly flip exit
- Soft SL: No hard stop-loss, exit ONLY on Monthly direction flip

Usage:
    python EA/macro_trend_catcher/reports/analyze_commodity_softsl.py
"""

import json
import os
import sys

REPORT_DIR = os.path.dirname(__file__)


def load_trades(json_path):
    with open(json_path) as f:
        return json.load(f)


def analyze_trades(trades, label):
    """Analyze a list of trade dicts."""
    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"{'='*80}")

    by_symbol = {}
    for t in trades:
        sym = t["symbol"]
        if sym not in by_symbol:
            by_symbol[sym] = []
        by_symbol[sym].append(t)

    # Per-symbol breakdown
    print(f"\n  {'Symbol':<12s} {'Trades':>6s} {'L':>3s} {'S':>3s} {'WR%':>6s} "
          f"{'Net%':>10s} {'MaxWin%':>10s} {'MaxLoss%':>10s} {'AvgDur':>7s} {'SL Hits':>8s}")
    print(f"  {'-'*12} {'-'*6} {'-'*3} {'-'*3} {'-'*6} {'-'*10} {'-'*10} {'-'*10} {'-'*7} {'-'*8}")

    total_equity = {}
    for sym, sym_trades in sorted(by_symbol.items()):
        n = len(sym_trades)
        longs = sum(1 for t in sym_trades if t["direction"] == "bullish")
        shorts = n - longs
        wins = sum(1 for t in sym_trades if t["net_return_pct"] > 0)
        wr = wins / n * 100 if n else 0
        rets = [t["net_return_pct"] for t in sym_trades]
        max_win = max(rets) if rets else 0
        max_loss = min(rets) if rets else 0
        avg_dur = sum(t["duration_days"] for t in sym_trades) / n
        sl_hits = sum(1 for t in sym_trades if t["exit_reason"] == "stop_loss")

        # Compound equity
        eq = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in rets:
            eq *= (1 + r / 100)
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)
        total_equity[sym] = {"final": eq, "max_dd": max_dd, "trades": n}

        net_pct = (eq - 1) * 100
        print(f"  {sym:<12s} {n:>6d} {longs:>3d} {shorts:>3d} {wr:>5.1f}% "
              f"{net_pct:>+9.1f}% {max_win:>+9.1f}% {max_loss:>+9.1f}% {avg_dur:>6.0f}d {sl_hits:>8d}")

    # Portfolio simulation (equal weight, 2% risk per trade)
    print(f"\n  PORTFOLIO SIMULATION (2% risk / trade)")
    print(f"  {'-'*60}")
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    all_trades_sorted = sorted(trades, key=lambda t: t["entry_time"])

    trade_results = []
    for t in all_trades_sorted:
        net_r = t["net_return_pct"]
        sl_dist = t["sl_distance_pct"]
        if sl_dist > 0:
            risk_reward = net_r / sl_dist
            position_return = 0.02 * risk_reward  # 2% risk * R multiple
        else:
            position_return = net_r / 100 * 0.02

        old_eq = equity
        equity *= (1 + position_return)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)
        trade_results.append({
            "symbol": t["symbol"],
            "entry": t["entry_time"],
            "exit": t["exit_time"],
            "dir": t["direction"][:1].upper(),
            "net_pct": net_r,
            "R_mult": net_r / sl_dist if sl_dist > 0 else 0,
            "eq_before": old_eq,
            "eq_after": equity,
        })

    print(f"\n  {'#':>3s} {'Symbol':<10s} {'Entry':>10s} {'Exit':>10s} {'Dir':>3s} "
          f"{'Net%':>9s} {'R-Mult':>7s} {'Equity':>8s}")
    print(f"  {'-'*3} {'-'*10} {'-'*10} {'-'*10} {'-'*3} {'-'*9} {'-'*7} {'-'*8}")
    for i, tr in enumerate(trade_results, 1):
        print(f"  {i:>3d} {tr['symbol']:<10s} {tr['entry']:>10s} {tr['exit']:>10s} {tr['dir']:>3s} "
              f"{tr['net_pct']:>+8.2f}% {tr['R_mult']:>+6.2f}R {tr['eq_after']:>7.4f}")

    # Data period
    first_entry = min(t["entry_time"] for t in trades)
    last_exit = max(t["exit_time"] for t in trades)
    from datetime import datetime
    d0 = datetime.strptime(first_entry, "%Y-%m-%d")
    d1 = datetime.strptime(last_exit, "%Y-%m-%d")
    years = (d1 - d0).days / 365.25

    total_return = (equity - 1) * 100
    cagr = (equity ** (1 / years) - 1) * 100 if years > 0 else 0

    print(f"\n  SUMMARY")
    print(f"  {'-'*60}")
    print(f"  Period:           {first_entry} → {last_exit} ({years:.1f} years)")
    print(f"  Total trades:     {len(trades)}")
    print(f"  Final equity:     {equity:.4f} ({total_return:+.1f}%)")
    print(f"  CAGR:             {cagr:.1f}%")
    print(f"  Max Drawdown:     {max_dd:.1f}%")

    # Wins/losses
    wins = [t for t in trades if t["net_return_pct"] > 0]
    losses = [t for t in trades if t["net_return_pct"] <= 0]
    print(f"  Win Rate:         {len(wins)}/{len(trades)} ({len(wins)/len(trades)*100:.1f}%)")
    if wins:
        print(f"  Avg Win:          {sum(t['net_return_pct'] for t in wins)/len(wins):+.2f}%")
    if losses:
        print(f"  Avg Loss:         {sum(t['net_return_pct'] for t in losses)/len(losses):+.2f}%")

    # Direction breakdown
    longs = [t for t in trades if t["direction"] == "bullish"]
    shorts = [t for t in trades if t["direction"] == "bearish"]
    print(f"\n  Direction:        LONG={len(longs)} SHORT={len(shorts)}")
    if longs:
        l_wins = sum(1 for t in longs if t["net_return_pct"] > 0)
        print(f"  LONG WR:          {l_wins}/{len(longs)} ({l_wins/len(longs)*100:.1f}%)")
    if shorts:
        s_wins = sum(1 for t in shorts if t["net_return_pct"] > 0)
        print(f"  SHORT WR:         {s_wins}/{len(shorts)} ({s_wins/len(shorts)*100:.1f}%)")

    # Exit reason
    reasons = {}
    for t in trades:
        r = t["exit_reason"]
        reasons[r] = reasons.get(r, 0) + 1
    print(f"\n  Exit reasons:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        wins_r = sum(1 for t in trades if t["exit_reason"] == r and t["net_return_pct"] > 0)
        print(f"    {r:<20s} {c:>3d} trades, {wins_r} wins ({wins_r/c*100:.0f}%)")

    # Growth projections
    print(f"\n  GROWTH PROJECTIONS (based on CAGR {cagr:.1f}%)")
    print(f"  {'-'*60}")
    print(f"  {'Starting':>12s} {'1 Year':>12s} {'3 Years':>12s} {'5 Years':>12s} {'10 Years':>12s}")
    for start in [1000, 5000, 10000, 50000]:
        y1 = start * (1 + cagr/100)**1
        y3 = start * (1 + cagr/100)**3
        y5 = start * (1 + cagr/100)**5
        y10 = start * (1 + cagr/100)**10
        print(f"  ${start:>10,d}  ${y1:>10,.0f}  ${y3:>10,.0f}  ${y5:>10,.0f}  ${y10:>10,.0f}")

    return {
        "equity": equity, "total_return": total_return, "cagr": cagr,
        "max_dd": max_dd, "trades": len(trades), "years": years,
    }


def main():
    softsl_path = os.path.join(REPORT_DIR, "mt5_v21_trade_log_v3_softsl.json")
    hardsl_path = os.path.join(REPORT_DIR, "mt5_v21_trade_log_v3.json")

    # Load both if available
    if os.path.exists(softsl_path):
        softsl_trades = load_trades(softsl_path)
        soft_result = analyze_trades(softsl_trades, "SOFT-SL (No hard SL — exit on Monthly direction flip only)")
    else:
        print("Soft-SL trade log not found!")
        soft_result = None

    if os.path.exists(hardsl_path):
        # Filter to only XAUUSDm, XAGUSDm, USOILm
        hardsl_all = load_trades(hardsl_path)
        hardsl_trades = [t for t in hardsl_all if t["symbol"] in ("XAUUSDm", "XAGUSDm", "USOILm")]
        hard_result = analyze_trades(hardsl_trades, "HARD-SL (3×ATR Daily stop-loss + Monthly flip)")
    else:
        print("Hard-SL trade log not found!")
        hard_result = None

    # Comparison
    if soft_result and hard_result:
        print(f"\n{'='*80}")
        print(f"  HARD-SL vs SOFT-SL COMPARISON")
        print(f"{'='*80}")
        print(f"\n  {'Metric':<25s} {'Hard-SL':>15s} {'Soft-SL':>15s} {'Diff':>15s}")
        print(f"  {'-'*25} {'-'*15} {'-'*15} {'-'*15}")

        metrics = [
            ("Trades",       f"{hard_result['trades']}",        f"{soft_result['trades']}"),
            ("Total Return",  f"{hard_result['total_return']:+.1f}%", f"{soft_result['total_return']:+.1f}%"),
            ("CAGR",          f"{hard_result['cagr']:.1f}%",     f"{soft_result['cagr']:.1f}%"),
            ("Max Drawdown",  f"{hard_result['max_dd']:.1f}%",   f"{soft_result['max_dd']:.1f}%"),
            ("Final Equity",  f"{hard_result['equity']:.4f}",    f"{soft_result['equity']:.4f}"),
        ]
        for name, h, s in metrics:
            print(f"  {name:<25s} {h:>15s} {s:>15s}")

        # Verdict
        print(f"\n  VERDICT:")
        if soft_result['cagr'] > hard_result['cagr']:
            improvement = soft_result['cagr'] - hard_result['cagr']
            print(f"  → SOFT-SL wins! CAGR improvement: +{improvement:.1f}% per year")
            print(f"  → Commodity trend-following benefits from letting winners run")
            print(f"  → Hard SL on commodities cuts winning trades prematurely")
        else:
            print(f"  → HARD-SL wins — tighter risk control is better for this data")

        if soft_result['max_dd'] > hard_result['max_dd']:
            print(f"  → BUT Soft-SL has higher drawdown ({soft_result['max_dd']:.1f}% vs {hard_result['max_dd']:.1f}%)")
        else:
            print(f"  → Soft-SL also has LOWER drawdown ({soft_result['max_dd']:.1f}% vs {hard_result['max_dd']:.1f}%)")

    print(f"\n{'='*80}")
    print(f"  DONE")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
