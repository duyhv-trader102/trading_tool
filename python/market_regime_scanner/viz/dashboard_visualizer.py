
import os
import json
from datetime import datetime

def generate_dashboard_html(results, output_path):
    """Generate a premium HTML dashboard from scanner results."""
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Define desired group order
    group_order = ["Coins", "Indices", "VN Stocks", "US Stocks", "FX & Metals", "Other"]
    
    # Group results by market/category
    markets = {g: [] for g in group_order}
    for r in results:
        m = r.get('market', 'Other')
        if m not in markets: markets[m] = []
        markets[m].append(r)
    
    # Remove empty groups
    markets = {k: v for k, v in markets.items() if v}

    # CSS for premium look
    css = """
    :root {
        --bg: #0f172a;
        --card-bg: rgba(30, 41, 59, 0.7);
        --text: #f1f5f9;
        --bullish: #10b981;
        --bearish: #ef4444;
        --conflict: #f59e0b;
        --neutral: #64748b;
        --accent: #3b82f6;
    }
    
    body {
        font-family: 'Inter', system-ui, -apple-system, sans-serif;
        background-color: var(--bg);
        background-image: 
            radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.15) 0, transparent 50%),
            radial-gradient(at 100% 0%, rgba(147, 51, 234, 0.15) 0, transparent 50%);
        color: var(--text);
        margin: 0;
        padding: 40px;
        min-height: 100vh;
    }
    
    h1 {
        font-size: 2.5rem;
        font-weight: 800;
        margin-bottom: 0.5rem;
        background: linear-gradient(to right, #60a5fa, #a855f7);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    .meta {
        color: var(--neutral);
        margin-bottom: 2rem;
        font-size: 0.9rem;
    }
    
    .market-section {
        margin-bottom: 3rem;
    }
    
    .market-title {
        font-size: 1.5rem;
        font-weight: 700;
        margin-bottom: 1.5rem;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    
    .market-title::after {
        content: '';
        height: 1px;
        background: linear-gradient(to right, var(--accent), transparent);
        flex-grow: 1;
    }
    
    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 20px;
    }
    
    .card {
        background: var(--card-bg);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 16px;
        padding: 20px;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;
    }
    
    .card:hover {
        transform: translateY(-5px);
        border-color: rgba(59, 130, 246, 0.4);
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
    }
    
    .card-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 20px;
    }
    
    .symbol {
        font-size: 1.25rem;
        font-weight: 700;
        color: #fff;
    }
    
    .status-badge {
        padding: 4px 10px;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    .status-ready { background: rgba(16, 185, 129, 0.2); color: var(--bullish); }
    .status-not-ready { background: rgba(239, 68, 68, 0.2); color: var(--bearish); }
    
    .regime-box {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }
    
    .regime-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    
    .label {
        font-size: 0.8rem;
        color: var(--neutral);
        text-transform: uppercase;
    }
    
    .value {
        font-size: 0.9rem;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    
    .dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
    }
    
    .bullish { color: var(--bullish); }
    .bullish-dot { background: var(--bullish); box-shadow: 0 0 10px var(--bullish); }
    
    .bearish { color: var(--bearish); }
    .bearish-dot { background: var(--bearish); box-shadow: 0 0 10px var(--bearish); }
    
    .conflict { color: var(--conflict); }
    .conflict-dot { background: var(--conflict); }
    
    .neutral { color: var(--neutral); }
    .neutral-dot { background: var(--neutral); }
    
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
    }
    
    .update-time {
        position: absolute;
        bottom: 12px;
        right: 15px;
        font-size: 0.65rem;
        color: var(--neutral);
    }
    """
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Macro Alignment Dashboard</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>{css}</style>
    </head>
    <body>
        <header>
            <h1>Macro Scanner</h1>
            <div class="meta">Last System Check: {timestamp} • Strategy: Monthly/Weekly Alignment</div>
        </header>

        <main>
    """
    
    for market, items in markets.items():
        html += f"""
        <section class="market-section">
            <div class="market-title">{market}</div>
            <div class="grid">
        """
        
        for item in items:
            status_class = "status-ready" if item['status'] == "READY" else "status-not-ready"
            
            mba_dir = item.get('mba_dir', 'neutral')
            w_dir = item.get('weekly_dir', 'neutral')
            
            # MBA Direction label in Vietnamese for clarity if needed, or just standard
            mba_dir_label = f"MBA {mba_dir.upper()}"
            
            html += f"""
            <div class="card">
                <div class="card-header">
                    <span class="symbol">{item['symbol']}</span>
                    <span class="status-badge {status_class}">{item['status']}</span>
                </div>
                <div class="regime-box">
                    <div class="regime-row">
                        <span class="label">MBA Context</span>
                        <span class="value {mba_dir}">
                            <span class="dot {mba_dir}-dot"></span>
                            {item['mba_regime']} ({mba_dir.upper()})
                        </span>
                    </div>
                    <div class="regime-row">
                        <span class="label">Weekly Execute</span>
                        <span class="value {w_dir}">
                            <span class="dot {w_dir}-dot"></span>
                            {item['weekly_regime']}
                        </span>
                    </div>
                </div>
                <div class="update-time">Udpated at {item['last_update']}</div>
            </div>
            """
            
        html += """
            </div>
        </section>
        """
        
    html += """
        </main>
    </body>
    </html>
    """
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard generated: {output_path}")

if __name__ == "__main__":
    # Test generation
    temp_results = [
        {"symbol": "BTCUSDm", "market": "MT5", "monthly_regime": "BULLISH_TREND", "monthly_dir": "bullish", "weekly_regime": "BULLISH_TREND", "weekly_dir": "bullish", "aligned": True, "last_update": "17:45"},
        {"symbol": "XAUUSDm", "market": "MT5", "monthly_regime": "SIDEWAYS", "monthly_dir": "neutral", "weekly_regime": "BEARISH_TREND", "weekly_dir": "bearish", "aligned": False, "last_update": "17:45"},
    ]
    generate_dashboard_html(temp_results, "output_test_dashboard.html")
