"""Quick analysis of MT5 V3 backtest results."""
import json
import statistics
import os

REPORT_DIR = os.path.dirname(__file__)

with open(os.path.join(REPORT_DIR, "mt5_v21_backtest_results_v3.json")) as f:
    data = json.load(f)

results = [r for r in data["results"] if r["trades"] >= 1 and not r["error"]]
results.sort(key=lambda r: r["total_return"], reverse=True)

print("=" * 90)
print("  MT5 V3 BACKTEST — PER-SYMBOL RESULTS (LONG+SHORT)")
print("=" * 90)
print(f"  {'Symbol':15s} {'Trades':>6} {'WR%':>6} {'Net%':>9} {'PF':>7} {'DD%':>7} {'Sharpe':>7} {'AvgDur':>7}")
print(f"  {'-'*15} {'-'*6} {'-'*6} {'-'*9} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")
for r in results:
    print(f"  {r['symbol']:15s} {r['trades']:>6d} {r['win_rate']:>5.1f}% "
          f"{r['total_return']:>+8.1f}% {r['profit_factor']:>7.2f} "
          f"{r['max_drawdown']:>6.1f}% {r['sharpe_ratio']:>7.2f} {r['avg_duration']:>6.0f}d")

rets = [r["total_return"] for r in results]
print(f"\n{'='*90}")
print("  PORTFOLIO ANALYSIS")
print(f"{'='*90}")
print(f"  Total symbols:     {len(results)}")
print(f"  Total trades:      {sum(r['trades'] for r in results)}")
print(f"  Avg return/symbol: {statistics.mean(rets):+.1f}%")
print(f"  Median return:     {statistics.median(rets):+.1f}%")
print(f"  StdDev:            {statistics.stdev(rets):.1f}%")
print(f"  Profitable:        {sum(1 for r in rets if r > 0)}/{len(rets)} ({sum(1 for r in rets if r > 0)/len(rets)*100:.0f}%)")

# Data duration
data_years = statistics.mean([r["data_years"] for r in results])
print(f"  Avg data years:    {data_years:.1f}")

# === Portfolio Simulations ===

# 1. Equal-weight buy-and-hold allocation
capital = 10000
n = len(results)
alloc = capital / n
total_end = sum(alloc * (1 + r["total_return"] / 100) for r in results)
eq_ret = (total_end / capital - 1) * 100
cagr = ((total_end / capital) ** (1 / data_years) - 1) * 100

print(f"\n  EQUAL-WEIGHT PORTFOLIO:")
print(f"  $10,000 -> ${total_end:,.0f} ({eq_ret:+.1f}%) over ~{data_years:.1f} years")
print(f"  CAGR: {cagr:.1f}%")

# 2. Sequential compound (all trades sorted by date)
with open(os.path.join(REPORT_DIR, "mt5_v21_trade_log_v3.json")) as f:
    trades = json.load(f)

trades.sort(key=lambda t: t["entry_time"])
equity = 1.0
peak = 1.0
max_dd = 0.0
risk_pct = 0.02  # 2% risk per trade

for t in trades:
    ret = t["net_return_pct"] / 100
    equity *= (1 + risk_pct * ret / (t["sl_distance_pct"] / 100) if t["sl_distance_pct"] > 0 else 1 + ret * risk_pct)
    peak = max(peak, equity)
    dd = (peak - equity) / peak * 100
    max_dd = max(max_dd, dd)

print(f"\n  SEQUENTIAL COMPOUND (2% risk/trade, all 94 trades):")
print(f"  Equity: 1.0 -> {equity:.4f} ({(equity - 1) * 100:+.1f}%)")
print(f"  Max drawdown: {max_dd:.1f}%")

# 3. Simple equity: each trade uses fixed 2% risk
equity2 = 1.0
peak2 = 1.0
max_dd2 = 0.0
for t in trades:
    # At 2% risk and SL distance = sl_distance_pct, 
    # actual return on equity = 2% * (net_return / sl_distance)
    sl_pct = t["sl_distance_pct"]
    net_pct = t["net_return_pct"]
    if sl_pct > 0:
        equity_impact = 0.02 * (net_pct / sl_pct)
    else:
        equity_impact = 0
    equity2 *= (1 + equity_impact)
    peak2 = max(peak2, equity2)
    dd2 = (peak2 - equity2) / peak2 * 100
    max_dd2 = max(max_dd2, dd2)

first_date = trades[0]["entry_time"]
last_date = trades[-1]["exit_time"]
print(f"\n  FIXED 2% RISK MODEL ({first_date} to {last_date}):")
print(f"  Equity: 1.0 -> {equity2:.4f} ({(equity2 - 1) * 100:+.1f}%)")
print(f"  Max drawdown: {max_dd2:.1f}%")
if equity2 > 1:
    years_span = (int(last_date[:4]) - int(first_date[:4])) + (int(last_date[5:7]) - int(first_date[5:7])) / 12
    if years_span > 0:
        cagr2 = (equity2 ** (1 / years_span) - 1) * 100
        print(f"  CAGR: {cagr2:.1f}% over {years_span:.1f} years")

# 4. Growth projection
print(f"\n{'='*90}")
print("  GROWTH PROJECTIONS (based on backtest)")
print(f"{'='*90}")

yearly_return = (equity2 ** (1 / max(years_span, 1)) - 1) if equity2 > 1 else 0
for starting_cap in [5000, 10000, 20000, 50000]:
    proj = []
    eq = starting_cap
    for yr in range(1, 11):
        eq *= (1 + yearly_return)
        proj.append(eq)
    print(f"\n  Starting $  {starting_cap:>7,d}")
    for yr, val in enumerate(proj, 1):
        marker = " <---" if yr in (1, 3, 5, 10) else ""
        print(f"    Year {yr:2d}: ${val:>12,.0f}{marker}")

# Win rate by direction
longs = [t for t in trades if t["direction"] == "bullish"]
shorts = [t for t in trades if t["direction"] == "bearish"]
long_wins = sum(1 for t in longs if t["is_win"])
short_wins = sum(1 for t in shorts if t["is_win"])
print(f"\n  DIRECTION BREAKDOWN:")
print(f"  LONG:  {len(longs)} trades, {long_wins} wins ({long_wins/max(len(longs),1)*100:.0f}% WR)")
print(f"  SHORT: {len(shorts)} trades, {short_wins} wins ({short_wins/max(len(shorts),1)*100:.0f}% WR)")
long_avg = statistics.mean([t["net_return_pct"] for t in longs]) if longs else 0
short_avg = statistics.mean([t["net_return_pct"] for t in shorts]) if shorts else 0
print(f"  LONG avg return:  {long_avg:+.2f}%")
print(f"  SHORT avg return: {short_avg:+.2f}%")

# By asset class
fx_majors = ["EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCADm", "USDCHFm", "NZDUSDm"]
fx_crosses = ["GBPJPYm", "EURJPYm", "EURGBPm", "AUDJPYm", "CADJPYm", "CHFJPYm", "GBPAUDm", "EURAUDm"]
commodities = ["XAUUSDm", "XAGUSDm", "USOILm"]

print(f"\n  BY ASSET CLASS:")
for group_name, group_syms in [("FX Majors", fx_majors), ("FX Crosses", fx_crosses), ("Commodities", commodities)]:
    group_results = [r for r in results if r["symbol"] in group_syms]
    if group_results:
        gr = [r["total_return"] for r in group_results]
        print(f"  {group_name:15s}: {len(group_results)} symbols, avg={statistics.mean(gr):+.1f}%, "
              f"profitable={sum(1 for r in gr if r > 0)}/{len(gr)}")
