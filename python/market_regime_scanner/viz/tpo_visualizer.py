"""
TPO Visualizer - Chart generation for TPO Profile analysis.
"""

from typing import Dict, List, Optional
from datetime import datetime
import math
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from core.tpo import TPOResult, SessionType, calc_block_size

# =============================================================================
# Constants
# =============================================================================

from viz.utils.tpo_viz_utils import (
    label_color, sort_labels, get_last_label, filter_labels, aggregate_profile
)


# =============================================================================
# Drawing Functions
# =============================================================================

class TPOChart:
    """TPO chart builder."""
    
    def __init__(self, fig: go.Figure, block_size: float, row: Optional[int] = None, letter_spacing: float = 1.5):
        self.fig = fig
        self.block_size = block_size
        self.row = row  # None = no subplots
        self.spacing = letter_spacing
    
    def snap(self, price: float) -> float:
        """Snap price to block grid."""
        return round(price / self.block_size) * self.block_size
    
    def _add_trace(self, trace):
        """Add trace with or without row/col."""
        if self.row is not None:
            self.fig.add_trace(trace, row=self.row, col=1)
        else:
            self.fig.add_trace(trace)
    
    def _add_shape(self, **kwargs):
        """Add shape with or without row/col."""
        if self.row is not None:
            self.fig.add_shape(**kwargs, row=self.row, col=1)
        else:
            self.fig.add_shape(**kwargs)
    
    def _add_annotation(self, **kwargs):
        """Add annotation with or without row/col."""
        if self.row is not None:
            self.fig.add_annotation(**kwargs, row=self.row, col=1)
        else:
            self.fig.add_annotation(**kwargs)
    
    def add_tpo_letters(self, x_base: float, profile: Dict[float, List[str]], 
                        poc: float, vah: float, val: float, name: str):
        """Add TPO letter scatter trace (Optimized with Scattergl)."""
        poc_b = self.snap(poc)
        vah_b = self.snap(vah)
        val_b = self.snap(val)
        
        x, y, texts, colors = [], [], [], []
        for price in sorted(profile.keys()):
            for i, label in enumerate(profile[price]):
                x.append(x_base + i * self.spacing)
                y.append(price)
                texts.append(label)
                
                if price == poc_b:
                    colors.append('yellow')
                elif val_b <= price <= vah_b:
                    colors.append('lime')
                else:
                    colors.append(label_color(label))
        
        # USE SCATTER (Safe Mode) - Scattergl can be buggy
        self._add_trace(
            go.Scatter(x=x, y=y, mode='text', text=texts,
                      textfont=dict(size=14, color=colors), name=name, showlegend=False)
        )
        max_count = max(len(profile.get(p, [])) for p in profile) if profile else 1
        return max_count * self.spacing
    
    def add_poc_line(self, x_base: float, poc: float, width: float):
        """Add POC dashed line."""
        poc_b = self.snap(poc)
        self._add_shape(
            type="line", x0=x_base, y0=poc_b, x1=x_base + min(width, 30), y1=poc_b,
            line=dict(color='yellow', width=2, dash='dash')
        )
    
    def add_va_box(self, x_base: float, vah: float, val: float, width: float):
        """Add Value Area box."""
        self._add_shape(
            type="rect", x0=x_base, y0=self.snap(val), x1=x_base + min(width, 30), y1=self.snap(vah),
            fillcolor="rgba(0, 255, 0, 0.1)", line=dict(color='green', width=1)
        )
    
    def add_ib_line(self, x_base: float, ib_high: float, ib_low: float):
        """Add Initial Balance vertical line."""
        if ib_high <= 0 or ib_low <= 0:
            return
        self._add_shape(
            type="line", x0=x_base - 1, y0=ib_low,
            x1=x_base - 1, y1=ib_high,
            line=dict(color='cyan', width=3)
        )
    
    def add_unfair_line(self, x_base: float, zone: tuple, color: str):
        """Add unfair extreme vertical line."""
        if not zone:
            return
        self._add_shape(
            type="line", x0=x_base - 0.5, y0=self.snap(zone[0]),
            x1=x_base - 0.5, y1=self.snap(zone[1]),
            line=dict(color=color, width=3)
        )
    
    def add_minus_dev_zone(self, x_base: float, zone: tuple, end_x: float):
        """Add minus development zone rectangle."""
        self._add_shape(
            type="rect", x0=x_base, y0=zone[0], x1=end_x, y1=zone[1],
            fillcolor="rgba(255, 165, 0, 0.15)", line=dict(color='orange', width=1, dash='dot')
        )

    def add_balance_area_band(self, area_high: float, area_low: float, source: str,
                              x0: float, x1: float, is_current: bool = True, mother_date: datetime = None):
        """Add macro balance area as a horizontal band.

        Args:
            is_current: True for the active (latest) MBA, False for historical units.
            mother_date: Date of the mother candle that started this MBA.
        """
        if is_current:
            color = 'rgba(0, 200, 255, 0.12)' if source == 'unfair_extremes' else 'rgba(180, 130, 255, 0.12)'
            border = '#00C8FF' if source == 'unfair_extremes' else '#B482FF'
            dash = 'dashdot'
            width = 1.5
        else:
            # Historical units — dimmer, thinner
            color = 'rgba(180, 130, 255, 0.06)'
            border = 'rgba(180, 130, 255, 0.35)'
            dash = 'dot'
            width = 1.0

        self._add_shape(
            type="rect",
            x0=x0, y0=self.snap(area_low),
            x1=x1, y1=self.snap(area_high),
            fillcolor=color,
            line=dict(color=border, width=width, dash=dash),
            layer='below',
        )
        # Label at right edge
        mid = (self.snap(area_high) + self.snap(area_low)) / 2
        if is_current:
            tag = 'UE' if source == 'unfair_extremes' else 'VA'
            date_str = mother_date.strftime('%Y-%m-%d') if mother_date else ""
            self._add_annotation(
                x=x1 - 5, y=mid,
                text=f"MBA {date_str} ({tag})",
                showarrow=False,
                font=dict(size=9, color=border, family='monospace'),
                bgcolor='rgba(0,0,0,0.6)',
                borderpad=2,
            )
        else:
            self._add_annotation(
                x=x1 - 5, y=mid,
                text="MBA",
                showarrow=False,
                font=dict(size=8, color=border, family='monospace'),
                bgcolor='rgba(0,0,0,0.4)',
                borderpad=1,
            )

    def add_imbalance_marker(self, x_pos: float, y_low: float, y_high: float,
                             direction: str, session_date: str):
        """Add vertical line marking the TREND (imbalance) session.

        This marks where the imbalance (TREND) occurred that started
        the current balance area cycle.
        """
        # Direction arrow and color
        if direction == "bullish":
            color = '#00FF7F'  # spring green
            arrow = '▲'
        else:
            color = '#FF6B6B'  # coral red
            arrow = '▼'

        # Vertical dashed line through the session
        self._add_shape(
            type="line",
            x0=x_pos, y0=y_low,
            x1=x_pos, y1=y_high,
            line=dict(color=color, width=2, dash='dash'),
            layer='below',
        )

        # Label at top
        self._add_annotation(
            x=x_pos, y=y_high,
            text=f"{arrow}IMB",
            showarrow=False,
            font=dict(size=9, color=color, family='monospace'),
            bgcolor='rgba(0,0,0,0.7)',
            borderpad=2,
            yanchor='bottom',
        )
    
    def add_label(self, x: float, y: float, text: str):
        """Add text annotation."""
        self._add_annotation(
            x=x, y=y, text=text, showarrow=False,
            font=dict(size=14, color='white'),
            yanchor='bottom',
        )
    
    def add_regime_marker(self, x_base: float, low: float, width: float, 
                          regime: str, confidence=None, direction: str = None,
                          rules: list = None, ready: bool = False, conflict: bool = False):
        """Add regime classification marker with rules at bottom of session."""
        if regime == "BREAKOUT":
            color = '#FF4444'
            marker = '▲'
        elif regime == "BALANCE":
            color = '#00FF00'
            marker = '◆'
        else:
            color = '#FF6600'
            marker = '▲'
        dir_str = f" ({direction})" if direction else ''
        conf_str = f" {confidence:.0%}" if confidence is not None else ''
        
        # Add READY / CONFLICT badges
        status_badges = []
        if ready:
            status_badges.append("<span style='color:#00FFFF'>[READY]</span>")
        if conflict:
            status_badges.append("<span style='color:#FF00FF'>[CONFLICT]</span>")
        badge_str = " " + " ".join(status_badges) if status_badges else ""

        marker_y = self.snap(low) - self.block_size * 2
        short_regime = {'BALANCE': 'BAL', 'BREAKOUT': 'BRK'}.get(regime, regime[:3])
        self._add_annotation(
            x=x_base + width / 2, y=marker_y,
            text=f"{marker} {short_regime}{conf_str}{dir_str}{badge_str}",
            showarrow=False,
            font=dict(size=13, color=color, family='monospace'),
            bgcolor='rgba(0,0,0,0.7)',
            bordercolor=color, borderwidth=1, borderpad=3
        )
        if rules:
            short = []
            for r in rules[:3]:
                if len(r) > 50:
                    r = r[:47] + "..."
                short.append(r)
            self._add_annotation(
                x=x_base + width / 2, y=marker_y - self.block_size * 2,
                text="<br>".join(short),
                showarrow=False,
                font=dict(size=7, color='#AAAAAA', family='monospace'),
                align='left',
            )

    def render_session(self, r: 'TPOResult', x_base: float, session_width: float,
                       sessions: list, sess_idx: int, date_fmt: str = '%m-%d',
                       regime_info=None, x_offset: float = 0):
        """
        Render a single TPO session: letters, levels, label, and optional regime marker.
        
        Args:
            r: TPOResult to render
            x_base: X offset for this session
            session_width: Width allocated per session
            sessions: Full list of sessions (for minus-dev zone extension)
            sess_idx: Index of this session in the list
            date_fmt: strftime format for session label
            regime_info: RegimeResult or dict with regime/confidence/direction/phase (optional)
            x_offset: Global X offset for all sessions (used for pan-to-history)
        """
        # Use session's own block_size if available (dynamic analysis),
        # otherwise fall back to chart-level block_size
        agg_block = getattr(r, 'block_size', 0) or self.block_size
        profile = aggregate_profile(r.profile, agg_block)
        
        # TPO letters + key levels
        max_tpo = self.add_tpo_letters(x_base, profile, r.poc, r.vah, r.val,
                                       f"TPO {r.session_start.strftime('%m-%d')}")
        self.add_poc_line(x_base, r.poc, max_tpo)
        self.add_va_box(x_base, r.vah, r.val, max_tpo)
        self.add_ib_line(x_base, r.ib_high, r.ib_low)
        
        # Unfair extremes
        self.add_unfair_line(x_base, r.unfair_high, 'red')
        self.add_unfair_line(x_base, r.unfair_low, 'blue')
        
        # Minus development zones (extend until cut by future session)
        for zone in r.minus_development:
            # Default: extend to end of all sessions (with x_offset)
            zone_end = x_offset + len(sessions) * session_width
            for fut_idx in range(sess_idx + 1, len(sessions)):
                fut = sessions[fut_idx]
                if fut.session_low <= zone[1] and fut.session_high >= zone[0]:
                    zone_end = x_offset + fut_idx * session_width
                    break
            self.add_minus_dev_zone(x_base, zone, zone_end)
        
        # Session label
        high = max(profile.keys()) if profile else r.session_high
        low = min(profile.keys()) if profile else r.session_low
        SESSION_ABBR = {
            SessionType.NORMAL: 'N', 
            SessionType.NORMAL_VARIATION: 'NV', 
            SessionType.NEUTRAL: 'Nt', 
            SessionType.TREND: 'T',
            SessionType.UNKNOWN: '?',
        }
        session_abbr = SESSION_ABBR.get(r.session_type, '?')
        dist_type = r.distribution_type
        dist_tag = f" {dist_type}" if dist_type else ""
        tpo_bal = r.tpo_balance
        tpo_str = f"↑{tpo_bal[0]}↓{tpo_bal[1]}" if r.session_type != SessionType.TREND else ''
        tr_val = r.target_rows if r.target_rows > 0 else '?'
        # Format POC with precision derived from block_size (e.g. 0.0002 → 4 dp)
        _dec = max(0, -int(math.floor(math.log10(r.block_size)))) if r.block_size > 0 else 5
        poc_str = f"{r.poc:.{_dec}f}"
        label = f"{r.session_start.strftime(date_fmt)}<br>POC:{poc_str} [{session_abbr}{dist_tag}]"
        if tpo_str:
            label += f"<br>{tpo_str} TR:{tr_val}"
        else:
            label += f"<br>TR:{tr_val}"
        self.add_label(x_base + 4, high + self.block_size * 4, label)
        
        # Regime marker
        if regime_info is not None:
            # Support TFRegime, RegimeResult, dict, and MBAMetadata objects.
            # TFRegime (from alignment.py) has .status ("IN BALANCE"/"BREAKOUT"/"WAITING FOR DATA")
            if hasattr(regime_info, 'status') and hasattr(regime_info, 'trend'):
                # TFRegime object — most informative source
                st = regime_info.status
                if st == "IN BALANCE":
                    regime = "BALANCE"
                elif st == "BREAKOUT":
                    regime = "BREAKOUT"
                elif st == "WAITING FOR DATA":
                    regime = ""
                else:
                    regime = st
            elif hasattr(regime_info, 'regime'):
                regime = regime_info.regime
            elif isinstance(regime_info, dict):
                regime = regime_info.get('regime', '')
            elif hasattr(regime_info, 'has_mba'):
                # MBAMetadata: derive regime from MBA state
                regime = 'BALANCE' if regime_info.has_mba else ''
            else:
                regime = ''

            if hasattr(regime_info, 'confidence'):
                confidence = regime_info.confidence
            elif isinstance(regime_info, dict):
                confidence = regime_info.get('confidence', 0)
            else:
                confidence = None  # MBAMetadata has no confidence

            # Direction: prefer ready_direction (canonical for MBAMetadata/TFRegime),
            # fall back to .trend (TFRegime) or .direction (legacy RegimeResult).
            if hasattr(regime_info, 'ready_direction') and regime_info.ready_direction:
                direction = regime_info.ready_direction
            elif hasattr(regime_info, 'trend') and regime_info.trend and regime_info.trend != 'neutral':
                direction = regime_info.trend
            elif hasattr(regime_info, 'direction'):
                direction = regime_info.direction
            elif isinstance(regime_info, dict):
                direction = regime_info.get('ready_direction') or regime_info.get('direction')
            else:
                direction = None

            if hasattr(regime_info, 'rules_triggered'):
                rules = regime_info.rules_triggered
            elif isinstance(regime_info, dict):
                rules = regime_info.get('rules_triggered', [])
            else:
                rules = []
            
            # Check for ready/conflict status in regime result
            ready = getattr(regime_info, 'ready_to_move', False)
            if not ready:
                ready = getattr(regime_info, 'is_ready', False)
            if not ready and isinstance(regime_info, dict):
                ready = regime_info.get('ready_to_move', False)
            
            conflict = False
            if hasattr(regime_info, 'uncertain_because') and regime_info.uncertain_because:
                conflict = "CONFLICT" in regime_info.uncertain_because.upper()
            elif isinstance(regime_info, dict) and regime_info.get('uncertain_because'):
                conflict = "CONFLICT" in regime_info['uncertain_because'].upper()

            self.add_regime_marker(x_base, low, max_tpo, regime, confidence, direction, rules, ready, conflict)
        
        return max_tpo


# =============================================================================
# Main Visualization Functions
# =============================================================================

def visualize_tpo_blocks(
    results: List[TPOResult], 
    block_size: Optional[float] = None,
    target_rows: int = 40,
    n_sessions: int = 5,
    filename: str = 'tpo_blocks.html',
    regime_results: Optional[List] = None,
) -> Optional[str]:
    """
    Visualize TPO with block aggregation and optional regime markers.
    
    Args:
        results: List of TPOResult sessions.
        block_size: Override block size (auto-calculated if None).
        target_rows: Target number of price rows for auto block_size.
        n_sessions: Number of recent sessions to display.
        filename: Output HTML file path.
        regime_results: Optional list of RegimeResult (or dicts) to show markers.
    """
    sessions = results[-n_sessions:] if len(results) >= n_sessions else results
    if not sessions:
        return None
    
    if block_size is None:
        max_range = max(r.range for r in sessions)
        block_size = calc_block_size(max_range, target_rows)
    
    fig = go.Figure()
    chart = TPOChart(fig, block_size)
    session_width = 45

    # Find the index of the last closed session to place the marker
    last_closed_idx = -1
    for i in range(len(sessions)-1, -1, -1):
        if sessions[i].is_closed:
            last_closed_idx = i
            break

    for idx, r in enumerate(sessions):
        # Determine regime info — show marker ONLY on the last closed session
        regime_info = None
        if idx == last_closed_idx and regime_results:
            regime_info = regime_results[-n_sessions:][idx] if len(regime_results) >= n_sessions else regime_results[idx]
            
        chart.render_session(r, idx * session_width, session_width,
                             sessions, idx, '%m-%d', regime_info)
    
    title = f"TPO Profile (block_size={block_size})"
    if regimes:
        title = f"TPO Regime Analysis (block_size={block_size})"
        fig.add_annotation(
            x=0, y=1.05, xref='paper', yref='paper',
            text="<b>Legend:</b> ◆ BALANCE | ▲ IMBALANCE | <span style='color:cyan'>█</span> IB | <span style='color:green'>█</span> VA | <span style='color:yellow'>---</span> POC",
            showarrow=False, font=dict(size=11, color='white'), xanchor='left'
        )
    
    fig.update_layout(
        title=title,
        template="plotly_dark", height=1000,
        xaxis=dict(showticklabels=False, showgrid=False),
        yaxis=dict(title="Price", dtick=block_size * 5)
    )
    fig.write_html(filename, include_plotlyjs="cdn")
    return filename


def visualize_tpo_topdown(
    mtf_results: dict,
    target_rows: int = 30,
    filename: str = 'tpo_topdown.html',
    trades: Optional[List[Dict]] = None,
    symbol: str = '',
    return_html: bool = False,
) -> Optional[str]:
    """
    Visualize multi-timeframe TPO (top-down analysis).

    Args:
        mtf_results: dict keyed by timeframe (e.g. 'Monthly', 'Weekly').
        trades:      Optional list of trade dicts to overlay on the chart.
        symbol:      Symbol name shown in the title.
        return_html: If True, return the HTML as a string instead of writing
                     to *filename*.  The caller is responsible for writing or
                     uploading the content.  *filename* is ignored in this mode.
    
    Returns:
        If return_html=True:  the full HTML string.
        If return_html=False: *filename* (written to disk), or None on error.
    """
    timeframes = list(mtf_results.keys())
    n_tf = len(timeframes)
    if n_tf == 0:
        return None
    
    # Map period codes to display labels
    PERIOD_LABELS = {'W1': '1W bar', 'D1': '1D bar', 'H4': '4H bar', 'H1': '1H bar', 'M15': '15m bar'}
    
    def get_subplot_title(tf: str) -> str:
        period = mtf_results[tf].get('period', '')
        period_label = PERIOD_LABELS.get(period, f'{period} bar')
        return f"{tf} ({period_label})"
    
    fig = make_subplots(
        rows=n_tf, cols=1,
        subplot_titles=[get_subplot_title(tf) for tf in timeframes],
        vertical_spacing=0.08
    )
    
    DATE_FMTS = {'Monthly': '%m-%Y', 'Weekly': 'W%V-%G'}
    
    # Fixed session width for consistent display
    session_width = 45
    
    for row_idx, tf in enumerate(timeframes, 1):
        sessions = mtf_results[tf].get('results', [])
        if not sessions:
            continue
        
        block_size = mtf_results[tf].get('block_size')
        if block_size is None:
            max_range = max(r.range for r in sessions)
            block_size = calc_block_size(max_range, target_rows)
        
        chart = TPOChart(fig, block_size, row_idx)
        regimes = mtf_results[tf].get('regimes', [])
        # Determine date format loosely
        date_fmt = '%m-%d'
        for key, fmt in DATE_FMTS.items():
            if key in tf:
                date_fmt = fmt
                break
        
        # All sessions start at x=0, no offset
        total_sessions = len(sessions)
        x_offset = 0
        
        # Collect tick positions and labels for x-axis
        tick_vals = []
        tick_texts = []
        
        # Find the index of the last closed session to place the marker
        last_closed_idx = -1
        for i in range(len(sessions)-1, -1, -1):
            if sessions[i].is_closed:
                last_closed_idx = i
                break

        for sess_idx, r in enumerate(sessions):
            # For dashboards, show current regime marker ONLY on the last closed session
            regime_info = None
            if sess_idx == last_closed_idx:
                # Prefer TFRegime (has BREAKOUT/IN BALANCE status + trend)
                # over raw MBAMetadata (only knows has_mba).
                regime_info = mtf_results[tf].get('tf_regime') or mtf_results[tf].get('mba_metadata')
            
            x_pos = x_offset + sess_idx * session_width
            chart.render_session(r, x_pos, session_width,
                                 sessions, sess_idx, date_fmt, regime_info, x_offset=x_offset)
            # Tick at left side of session (where TPO letters start + small offset)
            tick_vals.append(x_pos + 8)
            tick_texts.append(r.session_start.strftime(date_fmt))
        
        # Macro Balance Area bands — Render full history of zones
        # Prioritize 'mba_metadata' which contains full history
        mba_meta = mtf_results[tf].get('mba_metadata')
        mba_current = mtf_results[tf].get('macro_balance')
        
        history_units = []
        if mba_meta and hasattr(mba_meta, 'history'):
            # Flatten all units from all historical MBAs
            for area in mba_meta.history:
                history_units.extend(area.all_units)
            # Also add current active MBA units
            if mba_meta.current_mba:
                history_units.extend(mba_meta.current_mba.all_units)
        elif mba_current and hasattr(mba_current, 'all_units'):
            # Fallback to current MBA's history if metadata not available
            history_units = mba_current.all_units
        
        if history_units:
            # Map displayed sessions to timestamps for fast lookup
            d_sess_map = {s.session_start: k for k, s in enumerate(sessions)}
            
            for unit_idx, unit in enumerate(history_units):
                is_current = False
                if mba_current:
                     if unit_idx == len(history_units) - 1:
                         is_current = True
                
                u_mother_start = getattr(unit, 'mother_start', None)
                u_end_start = getattr(unit, 'end_start', None)
                
                if not u_mother_start:
                   continue

                idx0 = d_sess_map.get(u_mother_start, -1)
                idx1 = d_sess_map.get(u_end_start, -1) if u_end_start else -1
                
                # Determine X coordinates
                # x0: if mother is before display window, start at 0
                x0 = x_offset + (idx0 * session_width if idx0 >= 0 else 0)
                
                # x1: if end is after display window or missing, end at last closed session
                if idx1 >= 0:
                    x1 = x_offset + (idx1 + 1) * session_width
                else:
                    if u_end_start and u_end_start < sessions[0].session_start:
                        continue # Unit is entirely before window
                    
                    # Find last closed session to stop the band there
                    last_closed_idx = -1
                    for i in range(len(sessions)-1, -1, -1):
                        if sessions[i].is_closed:
                            last_closed_idx = i
                            break
                    
                    if last_closed_idx >= 0:
                        x1 = x_offset + (last_closed_idx + 1) * session_width
                    else:
                        # Fallback for sessions where none are closed? (unlikely for MBA)
                        x1 = x_offset + total_sessions * session_width
                
                # Use source from unit if available, else generic
                src = getattr(unit, 'source', 'value_area')
                
                chart.add_balance_area_band(
                    unit.area_high, unit.area_low, src,
                    x0=x0, x1=x1, is_current=is_current,
                    mother_date=unit.mother_start
                )

        # Draw imbalance (TREND) marker if present in current MBA
        if mba_current and mba_current.imbalance_session is not None:
            imb_sess = mba_current.imbalance_session
            imb_start = imb_sess.session_start
            display_idx_imb = d_sess_map.get(imb_start, -1)
            
            if display_idx_imb >= 0:
                imb_x = x_offset + display_idx_imb * session_width + session_width / 2
                chart.add_imbalance_marker(
                    x_pos=imb_x,
                    y_low=imb_sess.session_low,
                    y_high=imb_sess.session_high,
                    direction=mba_current.imbalance_direction or "neutral",
                    session_date=imb_sess.session_start.strftime(date_fmt),
                )

        # Set x-axis range to show all sessions with time labels
        x_range = [-session_width * 0.5, total_sessions * session_width]
        fig.update_xaxes(
            showticklabels=True, showgrid=False,
            tickmode='array',
            tickvals=tick_vals,
            ticktext=tick_texts,
            tickangle=45,
            tickfont=dict(size=10),
            range=x_range,
            row=row_idx, col=1
        )
        fig.update_yaxes(title_text="Price", row=row_idx, col=1)
    
    # PLOT TRADES (if provided) on the last timeframe (Execution layer)
    if trades and n_tf > 0:
        exec_full_sessions = mtf_results[timeframes[-1]].get('results', [])
        exec_row = n_tf
        
        # Map session start to index for X positioning
        print(f"Plotting {len(trades)} trades on execution timeframe...")
        
        for trade in trades:
            entry_time = trade.get("entry_time")
            exit_time = trade.get("exit_time")
            entry_price = trade.get("entry_price")
            exit_price = trade.get("exit_price")
            direction = trade.get("d_dir")
            date_label = trade.get("date")
            pnl = trade.get("swing_profit", 0)
            
            # Find session index by checking if trade time falls within session range
            e_idx = next((i for i, s in enumerate(exec_full_sessions) 
                         if s.session_start <= entry_time <= s.session_end), None)
            
            ex_idx = next((i for i, s in enumerate(exec_full_sessions) 
                          if exit_time and s.session_start <= exit_time <= s.session_end), None)
            
            # Only plot if entry is in the visible range
            if e_idx is None: continue
            
            x_entry = e_idx * session_width + 12
            x_exit = (ex_idx if ex_idx is not None else (len(exec_full_sessions)-1)) * session_width + 12
            
            color = "#00FF7F" if direction == "bullish" else "#FF6B6B"
            symbol = "triangle-up" if direction == "bullish" else "triangle-down"
            
            # Entry Marker - S A F E   M O D E (Scatter)
            fig.add_trace(go.Scatter(
                x=[x_entry], y=[entry_price],
                mode="markers",
                marker=dict(symbol=symbol, size=14, color=color, line=dict(width=1, color="white")),
                name="Entry", showlegend=False,
                hovertext=f"ENTRY {direction}<br>Price: {entry_price}<br>Date: {date_label}",
                textposition="top center"
            ), row=exec_row, col=1)
            
            # Exit Marker - S A F E   M O D E (Scatter)
            fig.add_trace(go.Scatter(
                x=[x_exit], y=[exit_price],
                mode="markers",
                marker=dict(symbol="x", size=10, color="orange"),
                name="Exit", showlegend=False,
                hovertext=f"EXIT<br>Price: {exit_price}<br>PnL: {pnl:.2f}"
            ), row=exec_row, col=1)

            # Draw Connection Line
            fig.add_shape(type="line",
                x0=x_entry, y0=entry_price, x1=x_exit, y1=exit_price,
                line=dict(color=color, width=1, dash="dot"),
                row=exec_row, col=1
            )

    # Build title with symbol name
    tf_flow = ' -> '.join(timeframes)
    title = f"<b>{symbol}</b> — TPO Top-Down Analysis ({tf_flow})" if symbol else f"TPO Top-Down Analysis ({tf_flow})"
    
    fig.update_layout(
        title=dict(text=title, font=dict(size=20)),
        template="plotly_dark", height=900 * n_tf, showlegend=False,
        dragmode='pan',  # Enable pan mode
        autosize=True,
    )
    
    # Custom HTML with fixed modebar (floating toolbar at top-right)
    html_content = fig.to_html(
        include_plotlyjs='cdn',
        full_html=False,
        config={
            'scrollZoom': True,
            'displayModeBar': True,
            'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
            'responsive': True,
            'displaylogo': False,
        }
    )
    
    # Wrap with custom CSS for floating toolbar
    full_html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{symbol or "TPO Analysis"}</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{ margin: 0; padding: 0; background: #111; }}
        .modebar {{ position: fixed !important; top: 10px !important; right: 10px !important; z-index: 1000 !important; }}
        .modebar-container {{ position: fixed !important; top: 10px !important; right: 10px !important; z-index: 1000 !important; }}
        .js-plotly-plot .plotly .modebar {{ background: rgba(30, 30, 30, 0.9) !important; border-radius: 4px; padding: 4px; }}
    </style>
</head>
<body>
{html_content}
</body>
</html>'''
    
    if return_html:
        return full_html

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(full_html)

    print(f"Top-down chart saved: {filename}")
    return filename


def print_profile(result: TPOResult, max_lines: int = 30):
    """Print TPO profile to console."""
    print(f"\n{'='*60}")
    print(f"TPO Profile - {result.session_start.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    print(f"Range: {result.session_low:.2f} - {result.session_high:.2f} ({result.range:.2f})")
    print(f"POC: {result.poc:.2f} | VAH: {result.vah:.2f} | VAL: {result.val:.2f}")
    print(f"IB: {result.ib_low:.2f} - {result.ib_high:.2f}")

    print("-" * 60)
    for price in sorted(result.profile.keys(), reverse=True)[:max_lines]:
        marker = ""
        if price == result.poc:     marker = " <-- POC"
        elif price == result.vah:   marker = " <-- VAH"
        elif price == result.val:   marker = " <-- VAL"
        elif price in result.single_prints: marker = " (SP)"
        print(f"{price:>10.2f} | {''.join(result.profile[price])}{marker}")
