"""
markets.utils.html_helpers — Shared HTML/CSS/JS helpers for dashboards.

Extracted from reporting.py (signal classification) and pnl_tracker.py
(cell renderers, CSS, JS) into one reusable module.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from markets.utils.constants import MARKET_META
from markets.utils.formatters import fmt_price, fmt_pct

# ── Signal classification ────────────────────────────────────────

SIGNAL_PRIORITY: Dict[str, int] = {
    "READY_LONG": 0,  "READY (BULLISH)": 0,  "BULL": 0,
    "READY_SHORT": 1, "READY (BEARISH)": 1,  "BEAR": 1,
    "WAIT_LONG":  2, "WAIT_SHORT":  3,
}


def sig_cls(signal: str) -> Tuple[str, str]:
    """Return (css_class, row_class) for a signal string."""
    up = signal.upper()
    if "READY" in up and ("BULLISH" in up or "LONG" in up):
        return "sig-rl", "row-bull"
    if "READY" in up and ("BEARISH" in up or "SHORT" in up):
        return "sig-rs", "row-bear"
    if "WAIT" in up and ("BULLISH" in up or "LONG" in up):
        return "sig-wl", ""
    if "WAIT" in up and ("BEARISH" in up or "SHORT" in up):
        return "sig-ws", ""
    return "", ""


def sig_key(r: Dict) -> int:
    """Sort key for result dicts — READY first, then WAIT, then others."""
    sig = (r.get("signal") or "").upper()
    if "READY" in sig and ("BULLISH" in sig or "LONG" in sig):  return 0
    if "READY" in sig and ("BEARISH" in sig or "SHORT" in sig): return 1
    if "READY" in sig: return 2
    if "WAIT"  in sig and ("BULLISH" in sig or "LONG" in sig):  return 3
    if "WAIT"  in sig and ("BEARISH" in sig or "SHORT" in sig): return 4
    return 99


# ── Cell renderers ───────────────────────────────────────────────

def change_cell(val) -> str:
    """Render a % change value as an HTML span with colour."""
    if val is None:
        return '<span class="dim">-</span>'
    cls = "chg-up" if val >= 0 else "chg-down"
    return f'<span class="{cls}">{fmt_pct(val)}</span>'


def range_bar_html(pos) -> str:
    """Render a range-position indicator as an HTML bar + label."""
    if pos is None:
        return '<span class="dim">-</span>'
    clamped = max(0, min(100, pos))
    if pos < 0:
        label_cls = "range-below"
        label = f"Below ({pos:.0f}%)"
    elif pos > 100:
        label_cls = "range-above"
        label = f"Above ({pos:.0f}%)"
    else:
        label_cls = ""
        label = f"{pos:.0f}%"
    # Colour: red < 30%, yellow 30-70%, green > 70%
    if clamped < 30:
        fill_color = "var(--red)"
    elif clamped < 70:
        fill_color = "var(--yellow)"
    else:
        fill_color = "var(--green)"
    return f"""<div class="range-wrap {label_cls}">
        <div class="range-bar"><div class="range-fill" style="width:{clamped}%;background:{fill_color}"></div></div>
        <span class="range-label">{label}</span>
    </div>"""


def trend_badge_cls(trend: str) -> str:
    """Return the CSS class for a trend badge."""
    t = trend.lower()
    if t == "bullish":
        return "tb-bull"
    if t == "bearish":
        return "tb-bear"
    if t == "conflict":
        return "tb-conflict"
    return "tb-neutral"


def build_trade_history_html(trades: List[Dict]) -> str:
    """Build the HTML section for closed trade history."""
    if not trades:
        return ""

    t_with_pnl = [t for t in trades if t.get("pnl_pct") is not None]
    t_wins = [t for t in t_with_pnl
              if (t.get("direction") == "LONG" and t["pnl_pct"] >= 0)
              or (t.get("direction") == "SHORT" and t["pnl_pct"] <= 0)]
    t_losses = [t for t in t_with_pnl if t not in t_wins]
    t_wr = len(t_wins) / len(t_with_pnl) * 100 if t_with_pnl else 0
    t_avg = sum(abs(t["pnl_pct"]) * (1 if t in t_wins else -1)
                for t in t_with_pnl) / len(t_with_pnl) if t_with_pnl else 0

    # Stats strip
    stats = f"""
    <div class="trade-stats">
        <span>{len(trades)} trades</span>
        <span class="win">{len(t_wins)}W</span> /
        <span class="lose">{len(t_losses)}L</span>
        <span>&middot; WR: {t_wr:.0f}%</span>
        <span>&middot; Avg PnL: <span class="{'win' if t_avg >= 0 else 'lose'}">{fmt_pct(t_avg)}</span></span>
    </div>"""

    # Table rows
    trows = ""
    for t in reversed(trades):  # newest first
        d = t.get("direction", "?")
        pnl = t.get("pnl_pct")
        is_win = (d == "LONG" and pnl is not None and pnl >= 0) or \
                 (d == "SHORT" and pnl is not None and pnl <= 0)
        pnl_cls = "pnl-win" if is_win else "pnl-lose" if pnl is not None else ""
        pnl_icon = ""
        if is_win:
            pnl_icon = '<span class="dm-icon win">&#10003;</span>'
        elif pnl is not None:
            pnl_icon = '<span class="dm-icon lose">&#10007;</span>'
        pnl_html = f'{fmt_pct(pnl)} {pnl_icon}' if pnl is not None else "-"

        dir_cls = "bullish" if d == "LONG" else "bearish"
        days = t.get("days_held", "-")
        days_str = str(days) if days is not None else "-"
        mkt = t.get("market", "")
        meta = MARKET_META.get(mkt, {"color": "#d4d4d4"})

        trows += f"""
        <tr>
            <td class="sym">{t.get('symbol','')}</td>
            <td><span style="color:{meta['color']};font-size:0.75rem">{mkt}</span></td>
            <td><span class="signal-badge {dir_cls}">{d}</span></td>
            <td class="num dim">{t.get('entry_date','')}</td>
            <td class="num dim">{t.get('exit_date','')}</td>
            <td class="num">{fmt_price(t.get('entry_price'))}</td>
            <td class="num">{fmt_price(t.get('exit_price'))}</td>
            <td class="num {pnl_cls}">{pnl_html}</td>
            <td class="num dim">{days_str}</td>
        </tr>"""

    return f"""
<h2 class="section-title" style="margin-top:40px">Trade History (Closed)</h2>
{stats}
<div class="table-wrap">
<table class="trade-table">
<thead><tr>
    <th>Symbol</th>
    <th>Market</th>
    <th>Direction</th>
    <th class="num-hdr">Entry Date</th>
    <th class="num-hdr">Exit Date</th>
    <th class="num-hdr">Entry Price</th>
    <th class="num-hdr">Exit Price</th>
    <th class="num-hdr">PnL%</th>
    <th class="num-hdr">Days</th>
</tr></thead>
<tbody>{trows}
</tbody>
</table>
</div>"""


# ── CSS ──────────────────────────────────────────────────────────

def dashboard_css() -> str:
    """Return the shared dark-theme CSS used by pnl_tracker dashboards."""
    return """
    :root {
        --bg: #0f172a;
        --surface: rgba(30,41,59,0.8);
        --border: rgba(255,255,255,0.08);
        --text: #e2e8f0;
        --dim: #64748b;
        --green: #10b981;
        --red: #ef4444;
        --blue: #3b82f6;
        --purple: #a855f7;
        --yellow: #f59e0b;
        --accent: #38bdf8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    .sticky-header {
        position: sticky; top: 0; z-index: 200;
        background: rgba(15,23,42,0.95);
        backdrop-filter: blur(12px);
        padding: 20px 40px 12px;
        margin: -32px -40px 16px;
        border-bottom: 1px solid var(--border);
    }
    body {
        font-family: 'Inter', system-ui, sans-serif;
        background: var(--bg);
        background-image:
            radial-gradient(at 0% 0%, rgba(59,130,246,0.12) 0, transparent 50%),
            radial-gradient(at 100% 0%, rgba(168,85,247,0.12) 0, transparent 50%);
        color: var(--text);
        padding: 32px 40px;
        min-height: 100vh;
    }
    h1 {
        font-size: 2rem; font-weight: 800;
        background: linear-gradient(135deg,#60a5fa,#a855f7);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 4px;
    }
    .meta { color: var(--dim); font-size: 0.85rem; margin-bottom: 8px; }
    .first-run-note {
        background: rgba(56,189,248,0.1); border: 1px solid rgba(56,189,248,0.3);
        border-radius: 8px; padding: 8px 16px; margin-bottom: 20px;
        font-size: 0.82rem; color: var(--accent);
    }

    /* stats */
    .stats-strip { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
    .stat-box {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: 12px; padding: 14px 22px; min-width: 120px;
    }
    .stat-label { font-size: 0.72rem; color: var(--dim); text-transform: uppercase; letter-spacing: 0.05em; }
    .stat-value { font-size: 1.5rem; font-weight: 700; margin-top: 2px; }
    .stat-value.win, .win { color: var(--green); }
    .stat-value.lose, .lose { color: var(--red); }

    /* market cards */
    .market-cards { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
    .summary-card {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: 10px; padding: 10px 16px; cursor: pointer;
        transition: all 0.2s; min-width: 100px;
    }
    .summary-card:hover, .summary-card.active {
        border-color: var(--blue); box-shadow: 0 0 16px rgba(59,130,246,0.15);
        transform: translateY(-2px);
    }
    .card-label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.04em; }
    .card-value { font-size: 1.2rem; font-weight: 700; color: var(--text); }
    .card-sub { font-size: 0.68rem; }

    /* filter */
    .filter-bar { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
    .filter-btn {
        background: var(--surface); border: 1px solid var(--border);
        color: var(--dim); padding: 5px 12px; border-radius: 8px;
        cursor: pointer; font-size: 0.78rem; transition: all 0.2s;
    }
    .filter-btn:hover, .filter-btn.active {
        color: #fff; border-color: var(--blue); background: rgba(59,130,246,0.15);
    }

    /* table */
    .table-wrap {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: 12px; overflow-x: auto;
    }
    table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
    thead th {
        background: rgba(15,23,42,0.9); padding: 10px 12px;
        text-align: left; font-weight: 600; font-size: 0.72rem;
        color: var(--dim); text-transform: uppercase; letter-spacing: 0.05em;
        border-bottom: 1px solid var(--border); position: sticky; top: 0;
        cursor: pointer; user-select: none; white-space: nowrap;
    }
    .num-hdr { text-align: right; }
    tbody td { padding: 8px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }
    tbody tr:hover { background: rgba(59,130,246,0.06); }
    tbody tr:last-child td { border-bottom: none; }
    .market-group-row td { cursor: default; }
    .market-group-row:hover td { background: rgba(59,130,246,0.06) !important; }
    .win-row { background: rgba(16,185,129,0.03); }
    .lose-row { background: rgba(239,68,68,0.03); }

    .sym { font-weight: 600; color: #fff; white-space: nowrap; }
    .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .dim { color: var(--dim); }
    .signal-badge {
        padding: 2px 8px; border-radius: 4px; font-size: 0.7rem;
        font-weight: 600; white-space: nowrap;
    }
    .signal-badge.bullish { background: rgba(16,185,129,0.12); color: var(--green); }
    .signal-badge.bearish { background: rgba(239,68,68,0.12); color: var(--red); }

    /* PnL */
    .pnl-win { color: var(--green); font-weight: 600; }
    .pnl-lose { color: var(--red); font-weight: 600; }
    .dm-icon { font-size: 0.7rem; margin-left: 2px; }
    .dm-icon.win { color: var(--green); }
    .dm-icon.lose { color: var(--red); }

    /* changes */
    .chg-up { color: var(--green); }
    .chg-down { color: var(--red); }

    /* range bar */
    .range-td { min-width: 90px; }
    .range-wrap { display: flex; flex-direction: column; gap: 2px; align-items: flex-start; }
    .range-bar {
        width: 70px; height: 6px; background: rgba(100,116,139,0.25);
        border-radius: 3px; overflow: visible; position: relative;
    }
    .range-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
    .range-label { font-size: 0.68rem; color: var(--dim); }
    .range-below .range-label { color: var(--red); }
    .range-above .range-label { color: var(--green); }

    /* regime badges */
    .regime-cell { text-align: center; }
    .regime-badge {
        display: inline-block; padding: 2px 6px; border-radius: 4px;
        font-size: 0.72rem; font-weight: 600; font-family: 'Fira Code', monospace;
        letter-spacing: 0.02em;
    }
    .tb-bull { background: rgba(16,185,129,0.12); color: var(--green); }
    .tb-bear { background: rgba(239,68,68,0.12); color: var(--red); }
    .tb-conflict { background: rgba(245,158,11,0.12); color: var(--yellow); }
    .tb-neutral { background: rgba(100,116,139,0.1); color: var(--dim); }
    .regime-changed { box-shadow: 0 0 0 1.5px var(--accent); }

    /* realtime badge */
    .rt-badge {
        display: inline-block; font-size: 0.55rem; font-weight: 700;
        background: rgba(56,189,248,0.15); color: var(--accent);
        padding: 1px 4px; border-radius: 3px; vertical-align: middle;
        margin-left: 3px; letter-spacing: 0.04em;
    }

    /* closed signals */
    .closed-row { opacity: 0.55; }
    .closed-row:hover { opacity: 0.85; }
    .closed-badge {
        display: inline-block; font-size: 0.55rem; font-weight: 700;
        background: rgba(100,116,139,0.2); color: var(--dim);
        padding: 1px 4px; border-radius: 3px; vertical-align: middle;
        margin-left: 3px; letter-spacing: 0.04em;
    }

    /* trade history section */
    .section-title {
        color: var(--text); font-size: 1.1rem; font-weight: 700;
        margin-bottom: 8px;
    }
    .trade-stats {
        font-size: 0.82rem; color: var(--dim); margin-bottom: 12px;
        display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
    }
    .trade-table { width: 100%; }
    .trade-table th { font-size: 0.72rem; }
    .trade-table td { font-size: 0.80rem; padding: 6px 10px; }

    @media (max-width: 1100px) {
        body { padding: 16px; }
        table { font-size: 0.76rem; }
    }
    """


# ── JS ───────────────────────────────────────────────────────────

def dashboard_js() -> str:
    """Return the shared JS used by pnl_tracker dashboards."""
    return r"""
    function filterTable(key) {
        const rows = document.querySelectorAll('tbody tr');
        const btns = document.querySelectorAll('.filter-btn');
        const cards = document.querySelectorAll('.summary-card');
        btns.forEach(b => b.classList.remove('active'));
        cards.forEach(c => c.classList.remove('active'));

        if (key === 'ALL') {
            rows.forEach(r => r.style.display = '');
            document.querySelector('[data-filter="ALL"]').classList.add('active');
        } else if (key === 'WINNING') {
            rows.forEach(r => {
                if (r.classList.contains('market-group-row')) {
                    const mkt = r.dataset.market;
                    const has = document.querySelector(`tbody tr[data-market="${mkt}"][data-dm="1"]`);
                    r.style.display = has ? '' : 'none';
                } else {
                    r.style.display = r.dataset.dm === '1' ? '' : 'none';
                }
            });
            document.querySelector('[data-filter="WINNING"]').classList.add('active');
        } else if (key === 'LOSING') {
            rows.forEach(r => {
                if (r.classList.contains('market-group-row')) {
                    const mkt = r.dataset.market;
                    const has = document.querySelector(`tbody tr[data-market="${mkt}"][data-dm="0"]`);
                    r.style.display = has ? '' : 'none';
                } else {
                    r.style.display = r.dataset.dm === '0' ? '' : 'none';
                }
            });
            document.querySelector('[data-filter="LOSING"]').classList.add('active');
        } else if (key === 'ACTIVE') {
            rows.forEach(r => {
                if (r.classList.contains('market-group-row')) {
                    const mkt = r.dataset.market;
                    const has = document.querySelector(`tbody tr[data-market="${mkt}"][data-closed="0"]`);
                    r.style.display = has ? '' : 'none';
                } else {
                    r.style.display = r.dataset.closed === '0' ? '' : 'none';
                }
            });
            document.querySelector('[data-filter="ACTIVE"]').classList.add('active');
        } else if (key === 'CLOSED') {
            rows.forEach(r => {
                if (r.classList.contains('market-group-row')) {
                    const mkt = r.dataset.market;
                    const has = document.querySelector(`tbody tr[data-market="${mkt}"][data-closed="1"]`);
                    r.style.display = has ? '' : 'none';
                } else {
                    r.style.display = r.dataset.closed === '1' ? '' : 'none';
                }
            });
            document.querySelector('[data-filter="CLOSED"]').classList.add('active');
        } else {
            rows.forEach(r => {
                r.style.display = r.dataset.market === key ? '' : 'none';
            });
            const card = document.querySelector(`.summary-card[data-market="${key}"]`);
            if (card) card.classList.add('active');
            const btn = document.querySelector(`[data-filter="${key}"]`);
            if (btn) btn.classList.add('active');
        }
    }

    function sortCol(idx) {
        const tbody = document.querySelector('tbody');
        const dataRows = Array.from(tbody.querySelectorAll('tr:not(.market-group-row)'));
        const th = document.querySelectorAll('thead th')[idx];
        const asc = th.dataset.dir !== 'asc';
        document.querySelectorAll('thead th').forEach(h => h.dataset.dir = '');
        th.dataset.dir = asc ? 'asc' : 'desc';

        // For PnL column (4), sort numerically via data-pnl
        const numCols = new Set([2, 3, 4, 5, 6, 11]);
        dataRows.sort((a, b) => {
            let va, vb;
            if (idx === 4) {
                va = parseFloat(a.dataset.pnl) || 0;
                vb = parseFloat(b.dataset.pnl) || 0;
            } else if (numCols.has(idx)) {
                va = parseFloat(a.children[idx]?.textContent.replace(/[^\d.\-]/g, '')) || 0;
                vb = parseFloat(b.children[idx]?.textContent.replace(/[^\d.\-]/g, '')) || 0;
            } else {
                va = a.children[idx]?.textContent.trim() || '';
                vb = b.children[idx]?.textContent.trim() || '';
                return asc ? va.localeCompare(vb) : vb.localeCompare(va);
            }
            return asc ? va - vb : vb - va;
        });
        dataRows.forEach(r => tbody.appendChild(r));
    }
    """
