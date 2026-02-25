
import json
import os
import sys
import glob
from datetime import datetime
import pandas as pd
import numpy as np

# Add project root to path via relative import or assume running from module
try:
    from core.path_manager import setup_path, get_output_path, OUTPUT_DIR
    setup_path()
except ImportError:
    # Fallback if running as script from viz/
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from core.path_manager import setup_path, get_output_path, OUTPUT_DIR
    setup_path()

from analytic.performance.analytics import (
    monte_carlo_simulation, 
    risk_of_ruin, 
    calculate_regime_decay
)

def load_trades():
    # Use standardized output directory
    search_pattern = os.path.join(OUTPUT_DIR, "macro_trades*.json")
    files = glob.glob(search_pattern)
    
    # Deduplicate files by absolute path
    files = list(set([os.path.abspath(f) for f in files]))
    
    print(f"Scanning for trades in: {OUTPUT_DIR}")
    print(f"Found {len(files)} trade files.")
    
    all_data = {}
    
    for f in files:
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                symbol = data.get('symbol', 'Unknown')
                trades = data.get('trades', [])
                if trades:
                    all_data[symbol] = pd.DataFrame(trades)
        except Exception as e:
            print(f"Error loading {f}: {e}")
                
    return all_data

def calculate_metrics(df, start_capital=10000, risk_per_trade=0.02):
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    df = df.sort_values('exit_time')
    
    equity = start_capital
    equity_curve = [start_capital]
    pnls = [] 
    
    commits = [] # To store R-multiples for Monte Carlo
    
    wins = 0
    losses = 0
    
    # Calculate Average Loss (1R proxy)
    negative_trades = df[df['swing_profit'] < 0]
    if len(negative_trades) > 0:
        avg_loss = abs(negative_trades['swing_profit'].mean())
    else:
        avg_loss = 1.0 
        
    for _, row in df.iterrows():
        pnl = row['swing_profit']
        r_multiple = pnl / avg_loss
        commits.append(r_multiple * risk_per_trade) # % return
        
        risk_amount = equity * risk_per_trade
        profit_amount = risk_amount * r_multiple
        
        equity += profit_amount
        equity_curve.append(equity)
        pnls.append(profit_amount)
        
        if pnl > 0: wins += 1
        else: losses += 1

    total_return_pct = (equity - start_capital) / start_capital * 100
    
    # Max Drawdown
    peak = start_capital
    max_dd = 0
    for e in equity_curve:
        if e > peak: peak = e
        dd = (peak - e) / peak
        if dd > max_dd: max_dd = dd
        
    # Advanced Stats
    win_rate = wins / len(df) if len(df) > 0 else 0
    avg_win = df[df['swing_profit'] > 0]['swing_profit'].mean() if wins > 0 else 0
    payoff = avg_win / avg_loss if avg_loss > 0 else 0
    

    mc_stats = monte_carlo_simulation(commits)
    # Risk of Ruin (Win rate drops 10%)
    stress_wr = max(0, win_rate - 0.10)
    ror = risk_of_ruin(stress_wr, payoff, risk_per_trade)
    
    # Create Equity Series for Correlation
    equity_series = pd.Series(data=equity_curve[1:], index=df['exit_time']) 
    
    return {
        "trades": len(df),
        "total_return": total_return_pct,
        "max_drawdown": max_dd * 100,
        "final_equity": equity,
        "avg_loss_points": avg_loss,
        "win_rate": win_rate,
        "payoff": payoff,
        "mc_worst_dd": mc_stats.get("worst_case_dd", 0) * 100,
        "mc_p95_dd": mc_stats.get("p95_max_dd", 0) * 100,
        "risk_of_ruin": ror * 100,
        "equity_curve": equity_series
    }

def generate_report():
    data = load_trades()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    report = []
    report.append(f"MACRO SYSTEM ADVANCED REPORT Generated: {timestamp}\n")
    report.append("ASSUMPTIONS - Start Capital: 10,000 - Risk per trade: 2%")
    report.append("-" * 60)
    
    sorted_symbols = sorted(data.keys())
    
    equity_curves = {}
    
    for symbol in sorted_symbols:
        df = data[symbol]
        m = calculate_metrics(df.copy())
        
        clean_sym = symbol.replace("USDm", "").replace("USD", "")
        
        report.append(f"\n>>> ASSET: {clean_sym} ({m['trades']} trades)")
        report.append(f"Performance: Return +{m['total_return']:,.0f}% | WR {m['win_rate']:.1%} | Payoff {m['payoff']:.1f}")
        report.append(f"Drawdown:    Max {m['max_drawdown']:.1f}% | MC (95%) {m['mc_p95_dd']:.1f}% | Worst {m['mc_worst_dd']:.1f}%")
        report.append(f"Stress Test: Risk of Ruin (WR-10%): {m['risk_of_ruin']:.1f}%")
        
        # Store for Correlation
        equity_curves[clean_sym] = m['equity_curve']
        
    # Correlation Analysis
    if len(equity_curves) > 1:
        report.append("\n" + "="*60)
        report.append("CORRELATION MATRIX (Daily Equity Returns)")
        report.append("="*60)
        
        # 1. Resample to Daily and Align
        # Combine all series into a DF, resample 'D', ffill
        pd_dict = {}
        for sym, ser in equity_curves.items():
            # Handle duplicate timestamps by taking last
            ser = ser.groupby(ser.index).last()
            if not ser.empty:
                pd_dict[sym] = ser
            
        df_equity = pd.DataFrame(pd_dict)
        # Resample to daily, forward fill (since equity stays constant if no trade)
        df_daily = df_equity.resample('D').ffill()
        
        # Drop rows where we don't have valid data for ALL assets? 
        # Or just pairwise? Correlation handles NaN pairwise.
        # But if we want a matrix, better to have a common period.
        # Let's try filling leading NaNs with start_capital (10000)?
        df_daily = df_daily.fillna(10000)
        
        # Calculate Correlation of Changes (Daily Returns / PnL)
        # We correlate the *changes* in equity, not the raw equity values (which are non-stationary)
        df_returns = df_daily.pct_change().replace([np.inf, -np.inf], 0).fillna(0)
        
        corr_matrix = df_returns.corr()
        
        # Format table
        # Header
        headers = list(corr_matrix.columns)
        header_row = "      " + "".join([f"{h:>8}" for h in headers])
        report.append(header_row)
        
        for row_label, row in corr_matrix.iterrows():
            line = f"{row_label:<6}" + "".join([f"{val:>8.2f}" for val in row])
            report.append(line)
            
        report.append("\nInterpretation: High correlation (>0.7) implies assets move together.")
        report.append("Diversification is best achieved with low or negative correlation.")

    report.append("\n" + "="*60)
    report.append("End of Report")
    
    report_content = "\n".join(report)
    print(report_content)
    
    output_path = get_output_path("normalized_report.txt")
    with open(output_path, "w") as f:
        f.write(report_content)
    print(f"Report saved to: {output_path}")

if __name__ == "__main__":
    generate_report()
