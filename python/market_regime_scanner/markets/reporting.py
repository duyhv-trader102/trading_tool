"""
markets/reporting.py — HTML report generation for market scans.

  DashboardReporter  — combined multi-market dashboard (daily_scan output)
  HTMLReporter       — per-market scan table (legacy, kept for compatibility)
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from markets.utils.html_helpers import sig_cls, sig_key
from markets.utils.formatters import fmt_range


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard (combined all-markets report)
# ─────────────────────────────────────────────────────────────────────────────


class DashboardReporter:
    """
    Generate the combined multi-market HTML dashboard for daily scans.

    Usage::

        from markets.reporting import DashboardReporter
        path = DashboardReporter.generate_dashboard(
            all_results, markets, output_path, market_meta
        )
    """

    @staticmethod
    def generate_dashboard(
        all_results: List[Dict],
        markets: List[str],
        output_path: Path,
        market_meta: Dict[str, Dict[str, str]],
        diff_report=None,
    ) -> Path:
        """
        Write a self-contained HTML dashboard and return its path.

        Args:
            all_results:  Flat list of result dicts (each has a ``market`` key).
            markets:      Ordered list of market keys (for filter bar / cards).
            output_path:  Destination .html file path.
            market_meta:  ``{market: {"label": ..., "color": ...}}`` for styling.
            diff_report:  Optional DiffReport — renders a signal change panel.
        """
        timestamp      = datetime.now().strftime("%Y-%m-%d %H:%M")
        sorted_results = sorted(all_results, key=sig_key)

        rows       = "".join(
            DashboardReporter._build_row(r, market_meta.get(r["market"], {"label": r["market"], "color": "#d4d4d4"}))
            for r in sorted_results
        )
        summary    = DashboardReporter._build_summary_cards(all_results, markets, market_meta)
        filter_bar = DashboardReporter._build_filter_bar(markets, market_meta)
        diff_panel = DashboardReporter._build_diff_panel(diff_report) if diff_report else ""

        html = DashboardReporter._render_html(timestamp, len(all_results), summary, filter_bar, rows, diff_panel)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        return output_path

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_row(r: Dict, meta: Dict) -> str:
        sym       = r["symbol"]
        signal    = r.get("signal") or "-"
        market    = r["market"]
        has_chart = r.get("has_chart", False)

        m         = r["monthly"]
        m_trend   = (m.get("trend") or "").upper()
        m_ready   = "✓" if m["is_ready"] else ""
        if m_trend == "CONFLICT":
            m_ready += " ⚡"
        m_range = (
            f"{fmt_range(m['range_low'])} – "
            f"{fmt_range(m['range_high'])}"
        )

        w         = r["weekly"]
        w_trend   = (w.get("trend") or "").upper()
        w_ready   = "✓" if w["is_ready"] else ""
        if w_trend == "CONFLICT":
            w_ready += " ⚡"
        w_range = (
            f"{fmt_range(w['range_low'])} – "
            f"{fmt_range(w['range_high'])}"
        )

        sig_css, row_cls = sig_cls(signal)

        chart_file = sym.replace("/", "_").replace(":", "_") + "_TPO_TopDown.html"
        chart_rel  = f"{market.lower()}/{chart_file}"
        chart_href = r.get("chart_url") or chart_rel   # presigned S3 URL takes priority
        sym_cell   = (
            f'<a href="{chart_href}" class="chart-link">{sym}</a>'
            if has_chart else sym
        )
        mkt_badge = f'<span class="mkt-badge" style="color:{meta["color"]}">{meta["label"]}</span>'

        return (
            f'<tr data-market="{market}" data-sig="{signal}" class="{row_cls}">'
            f'<td class="sym">{sym_cell}</td>'
            f'<td>{mkt_badge}</td>'
            f'<td class="{sig_css}">{signal}</td>'
            f'<td><span class="tf-status">{m["status"]}</span>'
            f'<br><small>{m_trend} {m_ready}</small>'
            f'<br><small class="rng">{m_range}</small></td>'
            f'<td><span class="tf-status">{w["status"]}</span>'
            f'<br><small>{w_trend} {w_ready}</small>'
            f'<br><small class="rng">{w_range}</small></td>'
            f'</tr>\n'
        )

    @staticmethod
    def _build_summary_cards(all_results: List[Dict], markets: List[str], market_meta: Dict) -> str:
        total = len(all_results)
        ready = sum(1 for r in all_results if r.get("signal") and "READY" in r["signal"])
        wait  = sum(1 for r in all_results if r.get("signal") and "WAIT"  in r["signal"])

        cards = ""
        for mkt in markets:
            meta      = market_meta.get(mkt, {"label": mkt, "color": "#888"})
            mkt_res   = [r for r in all_results if r["market"] == mkt]
            mkt_ready = sum(1 for r in mkt_res if r.get("signal") and "READY" in r["signal"])
            cards += (
                f'<div class="card">'
                f'<div class="card-label" style="color:{meta["color"]}">{meta["label"]}</div>'
                f'<div class="card-count">{len(mkt_res)}</div>'
                f'<div class="card-ready">★ {mkt_ready} ready</div>'
                f'</div>\n'
            )

        return f"""
    <div class="summary-bar">
        <div class="card card-total">
            <div class="card-label">Total</div>
            <div class="card-count">{total}</div>
            <div class="card-ready">★ {ready} ready · ~ {wait} watch</div>
        </div>
        {cards}
    </div>
    """

    @staticmethod
    def _build_diff_panel(report) -> str:
        """Build an HTML panel summarising signal changes vs the previous day."""
        today = report.today_date
        prev  = report.prev_date

        def _dir_badge(sig: str | None) -> str:
            if not sig:
                return ""
            if "BULLISH" in (sig or "").upper():
                return '<span class="dir-bull">BULL</span>'
            if "BEARISH" in (sig or "").upper():
                return '<span class="dir-bear">BEAR</span>'
            return ""

        # ── NEW rows ──────────────────────────────────────────────────────────
        new_rows = ""
        for e in sorted(report.new, key=lambda x: (x.market, x.symbol)):
            badge = _dir_badge(e.today_signal)
            price = f"@ {e.entry_price:.4f}" if e.entry_price else ""
            detail = f'<br><small class="diff-detail">{e.detail}</small>' if e.detail else ""
            new_rows += (
                f'<tr class="diff-new" data-market="{e.market}">'
                f'<td><span class="diff-tag new-tag">NEW</span></td>'
                f'<td class="diff-sym">{e.symbol}</td>'
                f'<td><span class="diff-mkt">{e.market}</span></td>'
                f'<td>{badge} {price}{detail}</td>'
                f'</tr>\n'
            )

        # ── FLIPPED rows ──────────────────────────────────────────────────────
        flip_rows = ""
        for e in sorted(report.flipped, key=lambda x: (x.market, x.symbol)):
            p_badge = _dir_badge(e.prev_signal)
            t_badge = _dir_badge(e.today_signal)
            flip_rows += (
                f'<tr class="diff-flip" data-market="{e.market}">'
                f'<td><span class="diff-tag flip-tag">FLIP</span></td>'
                f'<td class="diff-sym">{e.symbol}</td>'
                f'<td><span class="diff-mkt">{e.market}</span></td>'
                f'<td>{p_badge} &rarr; {t_badge}</td>'
                f'</tr>\n'
            )

        # ── GONE rows ─────────────────────────────────────────────────────────
        gone_rows = ""
        for e in sorted(report.gone, key=lambda x: (x.market, x.symbol)):
            badge = _dir_badge(e.prev_signal)
            gone_rows += (
                f'<tr class="diff-gone" data-market="{e.market}">'
                f'<td><span class="diff-tag gone-tag">GONE</span></td>'
                f'<td class="diff-sym">{e.symbol}</td>'
                f'<td><span class="diff-mkt">{e.market}</span></td>'
                f'<td>{badge}</td>'
                f'</tr>\n'
            )

        all_rows = new_rows + flip_rows + gone_rows
        n_new    = len(report.new)
        n_flip   = len(report.flipped)
        n_gone   = len(report.gone)
        n_held   = len(report.held)

        if not all_rows:
            body = f'<p class="diff-no-change">No changes vs {prev} &mdash; {n_held} signal(s) held.</p>'
        else:
            body = f"""
<table class="diff-table">
  <thead>
    <tr><th></th><th>Symbol</th><th>Market</th><th>Direction</th></tr>
  </thead>
  <tbody>
{all_rows}  </tbody>
</table>"""

        return f"""
<div class="diff-panel" id="diffPanel">
  <div class="diff-header" onclick="toggleDiff()">
    <span class="diff-title">&#9650; Signal Changes vs {prev if prev and prev != "(none)" else "previous scan"}</span>
    <span class="diff-badges">
      <span class="diff-badge new-badge">+{n_new} new</span>
      <span class="diff-badge flip-badge">~{n_flip} flipped</span>
      <span class="diff-badge gone-badge">-{n_gone} gone</span>
      <span class="diff-badge held-badge">{n_held} held</span>
    </span>
  </div>
  <div class="diff-body" id="diffBody">
    {body}
  </div>
</div>
"""

    @staticmethod
    def _build_filter_bar(markets: List[str], market_meta: Dict) -> str:
        btns  = '<button class="filter-btn active" data-filter="ALL">All</button>\n'
        btns += '<button class="filter-btn" data-filter="READY">★ Ready</button>\n'
        for mkt in markets:
            meta = market_meta.get(mkt, {"label": mkt, "color": "#888"})
            btns += f'<button class="filter-btn" data-filter="{mkt}" style="--accent:{meta["color"]}">{meta["label"]}</button>\n'
        return f'<div class="filter-bar">{btns}</div>'

    @staticmethod
    def _render_html(timestamp: str, total: int, summary: str, filter_bar: str, rows: str, diff_panel: str = "") -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Market Dashboard &mdash; {timestamp}</title>
<style>
  :root {{
    --bg: #1e1e1e; --bg2: #252526; --bg3: #2d2d30;
    --border: #3e3e42; --fg: #d4d4d4; --fg2: #808080;
    --rl: #4ec9b0; --rs: #f44747; --wl: #85d9b3; --ws: #f0a0a0;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', sans-serif; background: var(--bg); color: var(--fg); padding: 20px; }}
  h1 {{ color: #4ec9b0; font-size: 1.4em; margin-bottom: 4px; }}
  .meta {{ color: var(--fg2); font-size: 0.85em; margin-bottom: 12px; }}
  .sticky-header {{ position: sticky; top: 0; z-index: 200;
    background: rgba(30,30,30,0.92); backdrop-filter: blur(8px);
    padding: 10px 0 8px; margin: -20px -20px 16px; padding: 12px 20px 10px;
    border-bottom: 1px solid var(--border); }}
  .summary-bar {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 8px; }}
  .card {{ background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 18px; min-width: 120px; }}
  .card-total {{ border-color: #4ec9b0; }}
  .card-label {{ font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.05em; color: var(--fg2); margin-bottom: 4px; }}
  .card-count {{ font-size: 1.8em; font-weight: 700; }}
  .card-ready {{ font-size: 0.8em; color: var(--fg2); margin-top: 2px; }}
  .filter-bar {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 0; }}
  .filter-btn {{ background: var(--bg2); border: 1px solid var(--border); color: var(--fg); padding: 5px 14px; border-radius: 20px; cursor: pointer; font-size: 0.82em; transition: all 0.15s; }}
  .filter-btn:hover {{ background: var(--bg3); }}
  .filter-btn.active {{ background: var(--bg3); border-color: var(--accent, #4ec9b0); color: var(--accent, #4ec9b0); }}
  table {{ width: 100%; border-collapse: collapse; background: var(--bg2); border-radius: 8px; overflow: hidden; }}
  th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }}
  th {{ background: #333; color: #fff; font-size: 0.82em; text-transform: uppercase; letter-spacing: 0.05em; cursor: pointer; }}
  th:hover {{ background: #3c3c3c; }}
  tr:hover {{ background: var(--bg3); }}
  tr.hidden {{ display: none; }}
  .sym {{ font-weight: 700; color: #569cd6; white-space: nowrap; }}
  .sym a.chart-link {{ color: #4ec9b0; text-decoration: none; border-bottom: 1px dashed #4ec9b0; }}
  .sym a.chart-link:hover {{ color: #6ce9d0; border-bottom-style: solid; }}
  .mkt-badge {{ font-size: 0.78em; font-weight: 600; }}
  .sig-rl {{ color: var(--rl); font-weight: 700; font-size: 1em; }}
  .sig-rs {{ color: var(--rs); font-weight: 700; font-size: 1em; }}
  .sig-wl {{ color: var(--wl); }}
  .sig-ws {{ color: var(--ws); }}
  tr.row-bull {{ background: rgba(78,201,176,0.08); }}
  tr.row-bull:hover {{ background: rgba(78,201,176,0.15); }}
  tr.row-bear {{ background: rgba(244,71,71,0.08); }}
  tr.row-bear:hover {{ background: rgba(244,71,71,0.15); }}
  .tf-status {{ font-size: 0.9em; }}
  small {{ color: var(--fg2); font-size: 0.78em; }}
  .rng {{ font-family: monospace; }}
  /* ── diff panel ─────────────────────────────────────────────────────── */
  .diff-panel {{ background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 12px; overflow: hidden; }}
  .diff-header {{ display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 8px 14px; cursor: pointer; user-select: none; }}
  .diff-header:hover {{ background: var(--bg3); }}
  .diff-title {{ font-size: 0.82em; font-weight: 700; color: var(--fg2); text-transform: uppercase; letter-spacing: 0.05em; }}
  .diff-badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin-left: auto; }}
  .diff-badge {{ font-size: 0.78em; font-weight: 600; border-radius: 20px; padding: 2px 10px; border: 1px solid; }}
  .new-badge  {{ background: rgba(78,201,176,0.12); border-color: rgba(78,201,176,0.5); color: #4ec9b0; }}
  .flip-badge {{ background: rgba(220,180,0,0.12);  border-color: rgba(220,180,0,0.45);  color: #dcc060; }}
  .gone-badge {{ background: rgba(244,71,71,0.10);  border-color: rgba(244,71,71,0.40);  color: #f47171; }}
  .held-badge {{ background: rgba(128,128,128,0.10); border-color: rgba(128,128,128,0.3); color: var(--fg2); }}
  .diff-body {{ padding: 0 14px 10px; }}
  .diff-no-change {{ color: var(--fg2); font-size: 0.82em; padding: 6px 0; }}
  .diff-table {{ width: 100%; border-collapse: collapse; background: transparent; border-radius: 0; font-size: 0.82em; margin-top: 4px; }}
  .diff-table th, .diff-table td {{ padding: 5px 10px; border-bottom: 1px solid var(--border); text-align: left; }}
  .diff-table th {{ background: transparent; color: var(--fg2); font-size: 0.78em; text-transform: uppercase; letter-spacing: 0.04em; cursor: default; }}
  .diff-table tr:last-child td {{ border-bottom: none; }}
  .diff-tag {{ font-size: 0.72em; font-weight: 700; border-radius: 4px; padding: 1px 6px; }}
  .new-tag  {{ background: rgba(78,201,176,0.2); color: #4ec9b0; }}
  .flip-tag {{ background: rgba(220,180,0,0.18); color: #dcc060; }}
  .gone-tag {{ background: rgba(244,71,71,0.15); color: #f47171; }}
  .diff-sym {{ font-weight: 700; color: #569cd6; }}
  .diff-mkt {{ font-size: 0.78em; color: var(--fg2); }}
  .diff-detail {{ color: var(--fg2); }}
  .dir-bull {{ color: #4ec9b0; font-weight: 700; }}
  .dir-bear {{ color: #f47171; font-weight: 700; }}
</style>
</head>
<body>
<div class="sticky-header">
<h1>&#128203; Daily Market Dashboard</h1>
<div class="meta">Generated: {timestamp} &middot; {total} symbols scanned</div>
{summary}
{filter_bar}
</div><!-- /sticky-header -->
{diff_panel}
<table id="mainTable">
  <thead>
    <tr>
      <th onclick="sortTable(0)">Symbol</th>
      <th onclick="sortTable(1)">Market</th>
      <th onclick="sortTable(2)">Signal</th>
      <th onclick="sortTable(3)">Monthly</th>
      <th onclick="sortTable(4)">Weekly</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>
<script>
document.querySelectorAll('.filter-btn').forEach(btn => {{
  btn.addEventListener('click', function() {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    this.classList.add('active');
    const f = this.dataset.filter;
    // Filter main table
    document.querySelectorAll('#mainTable tbody tr').forEach(tr => {{
      if (f === 'ALL') {{ tr.classList.remove('hidden'); return; }}
      if (f === 'READY') {{ tr.classList.toggle('hidden', !tr.dataset.sig.includes('READY')); return; }}
      tr.classList.toggle('hidden', tr.dataset.market !== f);
    }});
    // Filter diff panel rows (market filter only; ALL/READY shows all diff rows)
    const diffRows = document.querySelectorAll('.diff-table tbody tr[data-market]');
    diffRows.forEach(tr => {{
      if (f === 'ALL' || f === 'READY') {{ tr.classList.remove('hidden'); }}
      else {{ tr.classList.toggle('hidden', tr.dataset.market !== f); }}
    }});
    // Update diff-no-change message visibility
    const noChange = document.querySelector('.diff-no-change');
    if (noChange) noChange.style.display = '';
  }});
}});
function sortTable(col) {{
  const tbody = document.querySelector('#mainTable tbody');
  const rows  = Array.from(tbody.querySelectorAll('tr'));
  const dir   = tbody.dataset['sortDir' + col] === 'asc' ? -1 : 1;
  tbody.dataset['sortDir' + col] = dir === 1 ? 'asc' : 'desc';
  rows.sort((a, b) => {{
    const x = a.cells[col].innerText.trim().toLowerCase();
    const y = b.cells[col].innerText.trim().toLowerCase();
    return x < y ? -dir : x > y ? dir : 0;
  }});
  rows.forEach(r => tbody.appendChild(r));
}}
function toggleDiff() {{
  const body = document.getElementById('diffBody');
  const title = document.querySelector('.diff-title');
  if (!body) return;
  const hidden = body.style.display === 'none';
  body.style.display = hidden ? '' : 'none';
  const arrow = hidden ? '\u25b2 ' : '\u25bc ';
  title.textContent = arrow + title.textContent.replace(/^[\u25b2\u25bc]\s*/, '');
}}
</script>
</body>
</html>
"""

class HTMLReporter:
    """Generates HTML reports for market scans."""

    @staticmethod
    def generate_report(market_name: str, results: List[Dict[str, Any]], output_dir: str) -> str:
        """
        Generate an HTML report from scan results.
        
        Args:
            market_name: Name of the market (e.g., COIN, VNSTOCK).
            results: List of result dictionaries from scanner.
            output_dir: Directory to save the report.
            
        Returns:
            Path to the generated HTML file.
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        filename = os.path.join(output_dir, f"scan_report_{market_name.lower()}.html")
        
        html_content = HTMLReporter._build_html(market_name, results, timestamp)
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        return filename

    @staticmethod
    def _build_html(market_name: str, results: List[Dict[str, Any]], timestamp: str) -> str:
        rows = ""
        for r in results:
            symbol = r['symbol']
            signal = r['signal'] or "-"
            has_chart = r.get('has_chart', False)
            
            # Formatting Monthly
            m = r['monthly']
            m_status = m['status']
            m_trend = m.get('trend', '') or ""
            m_ready = "YES" if m['is_ready'] else "NO"
            if m_trend == 'conflict': m_ready += " (CONFLICT)"
            m_class = "ready" if m['is_ready'] else ""
            
            # Formatting Weekly
            w = r['weekly']
            w_status = w['status']
            w_trend = w.get('trend', '') or ""
            w_ready = "YES" if w['is_ready'] else "NO"
            if w_trend == 'conflict': w_ready += " (CONFLICT)"
            w_class = "ready" if w['is_ready'] else ""

            # Signal Class
            sig_class = ""
            if "READY" in signal: sig_class = "signal-ready"

            # Symbol cell — clickable link to chart if available
            chart_file = symbol.replace('/', '_').replace(':', '_') + '_TPO_TopDown.html'
            chart_href = r.get('chart_url') or chart_file  # presigned S3 URL takes priority
            if has_chart:
                symbol_cell = f'<a href="{chart_href}" class="chart-link" title="Open TPO Chart">{symbol}</a>'
            else:
                symbol_cell = symbol

            rows += f"""
            <tr>
                <td class="symbol">{symbol_cell}</td>
                <td class="{sig_class}">{signal}</td>
                <td class="{m_class}">
                    <div class="status">{m_status}</div>
                    <div class="sub-info">{m_trend.upper()} | Ready: {m_ready}</div>
                    <div class="sub-info">Range: {m['range_low'] or 0:.2f} - {m['range_high'] or 0:.2f}</div>
                </td>
                <td class="{w_class}">
                    <div class="status">{w_status}</div>
                    <div class="sub-info">{w_trend.upper()} | Ready: {w_ready}</div>
                    <div class="sub-info">Range: {w['range_low'] or 0:.2f} - {w['range_high'] or 0:.2f}</div>
                </td>
            </tr>
            """

        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{market_name} Market Scan Report</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #1e1e1e;
            color: #d4d4d4;
            margin: 0;
            padding: 20px;
        }}
        h1 {{ color: #4ec9b0; }}
        .meta {{ color: #808080; font-size: 0.9em; margin-bottom: 20px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background-color: #252526;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }}
        th, td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #3e3e42;
        }}
        th {{
            background-color: #333333;
            color: #ffffff;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.85em;
            cursor: pointer;
        }}
        th:hover {{ background-color: #3c3c3c; }}
        tr:hover {{ background-color: #2d2d30; }}
        
        .symbol {{ font-weight: bold; color: #569cd6; }}
        .symbol a.chart-link {{
            color: #4ec9b0;
            text-decoration: none;
            border-bottom: 1px dashed #4ec9b0;
            transition: all 0.2s;
        }}
        .symbol a.chart-link:hover {{
            color: #6ce9d0;
            border-bottom-style: solid;
            text-shadow: 0 0 8px rgba(78, 201, 176, 0.4);
        }}
        .signal-ready {{ color: #b5cea8; font-weight: bold; }}
        
        .status {{ font-weight: 500; margin-bottom: 4px; }}
        .sub-info {{ font-size: 0.8em; color: #808080; }}
        
        .ready .status {{ color: #ce9178; }} /* Highlight ready timeframes */
        
        /* Specific Status Colors */
        td:contains("BREAKOUT") {{ color: #c586c0; }}
    </style>
</head>
<body>
    <h1>{market_name} Market Regime Report</h1>
    <div class="meta">Generated: {timestamp}</div>
    
    <table id="scanTable">
        <thead>
            <tr>
                <th onclick="sortTable(0)">Symbol</th>
                <th onclick="sortTable(1)">Signal</th>
                <th onclick="sortTable(2)">Monthly Status</th>
                <th onclick="sortTable(3)">Weekly Status</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>

    <script>
        function sortTable(n) {{
            var table, rows, switching, i, x, y, shouldSwitch, dir, switchcount = 0;
            table = document.getElementById("scanTable");
            switching = true;
            dir = "asc";
            while (switching) {{
                switching = false;
                rows = table.rows;
                for (i = 1; i < (rows.length - 1); i++) {{
                    shouldSwitch = false;
                    x = rows[i].getElementsByTagName("TD")[n];
                    y = rows[i + 1].getElementsByTagName("TD")[n];
                    if (dir == "asc") {{
                        if (x.innerHTML.toLowerCase() > y.innerHTML.toLowerCase()) {{
                            shouldSwitch = true;
                            break;
                        }}
                    }} else if (dir == "desc") {{
                        if (x.innerHTML.toLowerCase() < y.innerHTML.toLowerCase()) {{
                            shouldSwitch = true;
                            break;
                        }}
                    }}
                }}
                if (shouldSwitch) {{
                    rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                    switching = true;
                    switchcount ++;
                }} else {{
                    if (switchcount == 0 && dir == "asc") {{
                        dir = "desc";
                        switching = true;
                    }}
                }}
            }}
        }}
    </script>
</body>
</html>
        """
