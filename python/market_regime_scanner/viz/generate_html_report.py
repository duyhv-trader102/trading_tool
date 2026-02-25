
import os
import json
import glob
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime
from core.path_manager import setup_path, get_output_path, OUTPUT_DIR

setup_path()

from analytic.performance.analytics import (
    monte_carlo_simulation, 
    risk_of_ruin, 
    equity_correlation,
    calculate_regime_decay,
    calculate_sharpe_sortino,
    ulcer_index
)

def generate_consolidated_report():
    # 1. Load Data
    json_pattern = os.path.join(OUTPUT_DIR, "macro_trades_*.json")
    files = glob.glob(json_pattern)
    
    results = []
    equity_series_dict = {}
    
    # --- PROCESS TRADES ---
    for f in files:
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                symbol = data.get('symbol', 'Unknown')
                trades = data.get('trades', [])
                if not trades: continue
                
                df = pd.DataFrame(trades)
                
                # Basic Metrics
                total_trades = len(df)
                wins = df[df['swing_profit'] > 0]
                losses = df[df['swing_profit'] <= 0]
                win_rate = len(wins) / total_trades if total_trades > 0 else 0
                
                avg_win = wins['swing_profit'].mean() if not wins.empty else 0
                avg_loss = abs(losses['swing_profit'].mean()) if not losses.empty else 1.0
                payoff = avg_win / avg_loss if avg_loss > 0 else 0
                
                total_return = df['swing_profit'].sum()
                
                # Advanced Analytics
                r_multiples = (df['swing_profit'] / avg_loss) * 0.02 if avg_loss > 0 else df['swing_profit'] * 0
                mc_stats = monte_carlo_simulation(r_multiples.tolist())
                mc_worst_dd = mc_stats.get("worst_case_dd", 0) * 100
                
                stressed_wr = max(0, win_rate - 0.10)
                ror = risk_of_ruin(stressed_wr, payoff, 0.02) * 100
                
                results.append({
                    "symbol": symbol,
                    "trades": total_trades,
                    "win_rate": win_rate,
                    "payoff": payoff,
                    "avg_profit": df['swing_profit'].mean(),
                    "total_return": total_return,
                    "mc_worst_dd": mc_worst_dd,
                    "risk_of_ruin": ror,
                    "raw_data": df.to_dict(orient='records')
                })
                
                # Correlation Prep
                df['exit_time'] = pd.to_datetime(df['exit_time'])
                df['profit_cumsum'] = df['swing_profit'].cumsum()
                df = df.set_index('exit_time')
                daily_eq = df['profit_cumsum'].resample('D').last()
                equity_series_dict[symbol] = daily_eq
                
        except Exception as e:
            print(f"Error loading {f}: {e}")

    # --- REGIME DECAY ANALYSIS ---
    regime_pattern = os.path.join(OUTPUT_DIR, "macro_regimes_*.json")
    r_files = glob.glob(regime_pattern)
    regime_html = ""
    
    if r_files:
        regime_html = "<div class='card'><h2>Regime Stability (Decay Analysis)</h2>"
        for f in r_files:
            try:
                with open(f, 'r') as file:
                    r_data = json.load(file)
                    sym = r_data.get('symbol', 'Unknown')
                    m_stats = calculate_regime_decay(r_data.get('monthly', []))
                    if not m_stats: continue

                    regime_html += f"<h3>{sym} - Monthly Context</h3>"
                    regime_html += "<table><thead><tr><th>Regime</th><th>Avg Duration</th><th>Max Duration</th><th>P(End @ 1)</th></tr></thead><tbody>"
                    
                    for reg, stat in m_stats.items():
                        prob_1 = stat['decay_prob'].get(1, 0.0) 
                        regime_html += f"<tr><td>{reg}</td><td>{stat['avg_duration']}</td><td>{stat['max']}</td><td>{prob_1:.2f}</td></tr>"
                    regime_html += "</tbody></table>"
            except: pass
        regime_html += "</div>"

    # --- CORRELATION MATRIX ---
    corr_html = "<p>Not enough assets for correlation.</p>"
    if len(equity_series_dict) > 1:
        df_corr = pd.DataFrame(equity_series_dict).ffill().fillna(0).diff().fillna(0)
        # FIX: Use asset_returns keyword
        corr_matrix = equity_correlation(asset_returns=df_corr)
        
        corr_html = "<table><thead><tr><th></th>"
        for col in corr_matrix.columns:
            corr_html += f"<th>{col}</th>"
        corr_html += "</tr></thead><tbody>"
        
        for idx, row in corr_matrix.iterrows():
            corr_html += f"<tr><td><strong>{idx}</strong></td>"
            for val in row:
                bg_color = "transparent"
                if val > 0.7 and val < 0.99: bg_color = "rgba(255, 99, 71, 0.2)"
                elif val < 0.3: bg_color = "rgba(46, 204, 113, 0.2)"
                corr_html += f"<td style='background:{bg_color}'>{val:.2f}</td>"
            corr_html += "</tr>"
        corr_html += "</tbody></table>"

    # --- GENERATE HTML ---
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Position Strategy Advanced Report</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; background: #1e1e1e; color: #e0e0e0; margin: 0; padding: 20px; }}
            h1 {{ color: #4facfe; }}
            h2 {{ color: #7cfc00; border-bottom: 1px solid #444; padding-bottom: 5px; }}
            .card {{ background: #2d2d2d; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #444; }}
            th {{ background: #333; color: #aaa; }}
            tr:hover {{ background: #383838; }}
            .metric-val {{ font-size: 1.2em; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1>Position Strategy Advanced Analytics</h1>
        <p>Generated: {timestamp}</p>
        
        <div class="card">
            <h2>Performance & Risk Summary</h2>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th><th>Trades</th><th>Win Rate</th><th>Payoff</th><th>Total Return</th><th>MC Worst DD</th><th>Risk of Ruin</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    for r in results:
        wr_color = "#00fa9a" if r['win_rate'] >= 0.5 else "#ff6b6b"
        ror_color = "#00fa9a" if r['risk_of_ruin'] < 1 else "#ff6b6b"
        html += f"""
        <tr>
            <td><strong>{r['symbol']}</strong></td>
            <td>{r['trades']}</td>
            <td style="color:{wr_color}">{r['win_rate']:.1%}</td>
            <td>{r['payoff']:.2f}</td>
            <td class="metric-val">{r['total_return']:,.0f}</td>
            <td>{r['mc_worst_dd']:.1f}%</td>
            <td style="color:{ror_color}">{r['risk_of_ruin']:.1f}%</td>
        </tr>"""
        
    html += f"""</tbody></table></div>
        
        <div class="card">
            <h2>Portfolio Correlation Matrix</h2>
            <p>Based on Daily PnL. High Correlation (>0.7) increases portfolio risk.</p>
            {corr_html}
        </div>
        
        {regime_html}
        
        <div class="card">
            <h2>Equity Curves</h2>
            <div id="equity_chart" style="width:100%;height:500px;"></div>
        </div>
        
        <script>
            var data = [];
    """
    
    for r in results:
        df = pd.DataFrame(r['raw_data'])
        df['equity'] = df['swing_profit'].cumsum()
        x_vals = [t['exit_time'] for t in r['raw_data']]
        y_vals = df['equity'].tolist()
        html += f"""
            var trace_{r['symbol']} = {{ x: {x_vals}, y: {y_vals}, mode: 'lines', name: '{r['symbol']}' }};
            data.push(trace_{r['symbol']});
        """
        
    html += """
            var layout = {
                title: 'Cumulative Returns (Points)',
                paper_bgcolor: '#2d2d2d', plot_bgcolor: '#2d2d2d',
                font: { color: '#e0e0e0' },
                xaxis: { gridcolor: '#444' }, yaxis: { gridcolor: '#444' }
            };
            Plotly.newPlot('equity_chart', data, layout);
        </script>
    </body>
    </html>
    """
    
    output_path = get_output_path("position_strategy_report.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Report generated: {output_path}")

    # Export CSV
    all_trades = []
    for r in results:
        for t in r['raw_data']:
            t['symbol'] = r['symbol']
            all_trades.append(t)
    if all_trades:
        csv_path = get_output_path("consolidated_position_trades.csv")
        pd.DataFrame(all_trades).to_csv(csv_path, index=False)
        print(f"CSV exported: {csv_path}")

if __name__ == "__main__":
    generate_consolidated_report()
