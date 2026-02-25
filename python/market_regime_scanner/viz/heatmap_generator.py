import json
import os
from typing import List, Dict

def generate_html_heatmap(data: List[Dict], output_path: str):
    """Generate a premium HTML heatmap dashboard."""
    
    css = """
    :root {
        --bg: #0f172a;
        --card-bg: #1e293b;
        --text: #f8fafc;
        --text-dim: #94a3b8;
        --bullish: #10b981;
        --bearish: #ef4444;
        --balance: #6366f1;
        --ready: #f59e0b;
        --compression: #ec4899;
        --border: #334155;
    }
    body {
        background-color: var(--bg);
        color: var(--text);
        font-family: 'Inter', system-ui, -apple-system, sans-serif;
        margin: 0;
        padding: 40px;
    }
    h1 {
        font-size: 2.5rem;
        font-weight: 800;
        margin-bottom: 30px;
        background: linear-gradient(to right, #6366f1, #ec4899);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
        gap: 24px;
    }
    .card {
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 24px;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        transition: transform 0.2s, border-color 0.2s;
    }
    .card:hover {
        transform: translateY(-4px);
        border-color: #6366f1;
    }
    .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
    }
    .symbol {
        font-size: 1.5rem;
        font-weight: 700;
    }
    .badge {
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
    }
    .badge-STRONG { background: var(--bullish); color: #fff; }
    .badge-MODERATE { background: var(--ready); color: #fff; }
    .badge-NONE { background: var(--border); color: var(--text-dim); }
    
    .tf-grid {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 12px;
    }
    .tf-card {
        background: rgba(15, 23, 42, 0.5);
        padding: 12px;
        border-radius: 8px;
        text-align: center;
    }
    .tf-label {
        font-size: 0.7rem;
        color: var(--text-dim);
        text-transform: uppercase;
        margin-bottom: 8px;
    }
    .tf-regime {
        font-size: 0.9rem;
        font-weight: 600;
    }
    .regime-BALANCE { color: var(--balance); }
    .regime-IMBALANCE { font-weight: 800; }
    .bullish { color: var(--bullish); }
    .bearish { color: var(--bearish); }
    
    .status-icons {
        display: flex;
        justify-content: center;
        gap: 8px;
        margin-top: 8px;
    }
    .icon {
        width: 12px;
        height: 12px;
        border-radius: 50%;
    }
    .icon-ready { background: var(--ready); box-shadow: 0 0 8px var(--ready); }
    .icon-compression { background: var(--compression); box-shadow: 0 0 8px var(--compression); }
    
    .conclusion {
        margin-top: 16px;
        font-size: 0.85rem;
        color: var(--text-dim);
        border-top: 1px solid var(--border);
        padding-top: 12px;
    }
    """
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Macro Swing Heatmap</title>
        <style>{css}</style>
    </head>
    <body>
        <h1>Macro Swing Heatmap</h1>
        <div class="grid">
    """
    
    for item in data:
        status = item["status"]
        direction_class = item["direction"]
        
        cards_html = ""
        for tf in ["Monthly", "Weekly", "Daily"]:
            state = item["tf_states"].get(tf, {})
            regime = state.get("regime", "N/A")
            phase = state.get("phase", "N/A")
            ready = state.get("ready", False)
            comp = state.get("compression", False)
            
            regime_class = f"regime-{regime}"
            icons = ""
            if ready: icons += '<div class="icon icon-ready" title="Ready for Move"></div>'
            if comp: icons += '<div class="icon icon-compression" title="Compression"></div>'
            
            cards_html += f"""
            <div class="tf-card">
                <div class="tf-label">{tf}</div>
                <div class="tf-regime {regime_class} {direction_class if regime == 'IMBALANCE' else ''}">{regime}</div>
                <div style="font-size: 0.7rem; color: var(--text-dim)">{phase}</div>
                <div class="status-icons">{icons}</div>
            </div>
            """
            
        html += f"""
        <div class="card">
            <div class="header">
                <div class="symbol">{item['symbol']}</div>
                <div class="badge badge-{status}">{status}</div>
            </div>
            <div class="tf-grid">
                {cards_html}
            </div>
            <div class="conclusion">{item['conclusion']}</div>
        </div>
        """
        
    html += """
        </div>
    </body>
    </html>
    """
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)


# ... (imports) ...
from core.path_manager import setup_path, get_output_path
setup_path()

# ... (generate_html_heatmap) ...

if __name__ == "__main__":
    input_file = get_output_path("scanner_results.json")
    output_file = get_output_path("heatmap.html")
    
    if os.path.exists(input_file):
        with open(input_file, 'r') as f:
            data = json.load(f)
        generate_html_heatmap(data, output_file)
        print(f"Heatmap generated at {output_file}")
    else:
        print(f"Error: {input_file} not found. Run macro_scanner.py first.")
