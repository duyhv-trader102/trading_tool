import plotly.graph_objects as go
import polars as pl
from datetime import datetime, timedelta

from plotly.subplots import make_subplots

def _add_ob_traces_and_shapes(fig, ohlc_data, ob_list, symbol, timeframe, row=None, col=None):
    df = pl.DataFrame(ohlc_data)
    if 'time' not in df.columns:
        return

    df = df.with_columns(
        pl.from_epoch('time', time_unit='s').alias('date')
    )
    dates = df['date'].to_list()
    
    # Candlestick Trace
    trace = go.Candlestick(
        x=dates,
        open=df['open'].to_list(),
        high=df['high'].to_list(),
        low=df['low'].to_list(),
        close=df['close'].to_list(),
        name=f"{symbol} {timeframe}"
    )
    
    if row is not None and col is not None:
        fig.add_trace(trace, row=row, col=col)
    else:
        fig.add_trace(trace)

    # Calculate bar duration to offset rectangles properly
    bar_duration = timedelta(seconds=0)
    if len(df) > 1:
        diffs = df.select(
            pl.col('date').diff().dt.total_seconds().drop_nulls()
        ).to_series()
        if len(diffs) > 0:
            mode_seconds = diffs.mode().to_list()[0]
            bar_duration = timedelta(seconds=mode_seconds)
    
    half_duration = bar_duration / 2
    last_date = dates[-1]
    
    # Determine axis references
    xref = "x"
    yref = "y"
    if row is not None and row > 1:
        xref = f"x{row}"
        yref = f"y{row}"
    
    for ob in ob_list:
        ob_time = datetime.fromtimestamp(ob['time'])
        
        # Determine end_time and color based on mitigation status
        mit_status = ob.get('mitigation_status', 'N/A')
        mit_time = ob.get('mitigation_time', None)
        mit_type = ob.get('mitigation_type', None)
        
        if mit_status == 'Mitigated' and mit_time:
            end_time = datetime.fromtimestamp(mit_time)
            fill_color = "LightSkyBlue" # Standard mitigated
            line_color = "RoyalBlue"
            if mit_type == 2:
                label = "FU" # Specific label for Funding Candle
                line_color = "Cyan" # Highlight FU color
            else:
                label = f"T{mit_type}" if mit_type else "MIT"
        else:
            end_time = last_date
            fill_color = "Gold" # Acceptance/Unmitigated
            line_color = "Orange"
            label = "ACC"
            
        fig.add_shape(type="rect",
            x0=ob_time - half_duration, 
            y0=ob['low'], 
            x1=end_time + half_duration, 
            y1=ob['high'],
            line=dict(color=line_color, width=1),
            fillcolor=fill_color,
            opacity=0.3,
            layer="below",
            xref=xref, 
            yref=yref
        )
        
        # Add labels for mitigation types
        fig.add_annotation(
            x=end_time, 
            y=ob['high'],
            text=label,
            showarrow=False,
            font=dict(size=10, color=line_color),
            yshift=10,
            xref=xref,
            yref=yref
        )

def plot_obs(ohlc_data, ob_list, symbol="Unknown", timeframe="Unknown", cashflow_status=None, filename='ob_chart.html'):
    fig = go.Figure()
    _add_ob_traces_and_shapes(fig, ohlc_data, ob_list, symbol, timeframe)
    
    title = f"{symbol} {timeframe} - OB Analysis"
    if cashflow_status:
        title += f" | Cashflow: {cashflow_status}"
        
    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=700
    )
    
    # Skip weekend gaps in visualization
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"])  # Hide Saturday to Monday (weekend gap)
        ]
    )
    
    fig.write_html(filename, include_plotlyjs="cdn")
    print(f"Chart saved to {filename}")

def plot_mtf_obs(mtf_data_list, symbol="Unknown", filename='ob_mtf_chart.html'):
    """
    mtf_data_list: list of dicts [{"ohlc_data":..., "ob_list":..., "timeframe":..., "cashflow":...}, ...]
    """
    num_tf = len(mtf_data_list)
    fig = make_subplots(rows=num_tf, cols=1, 
                        shared_xaxes=False, 
                        vertical_spacing=0.05,
                        subplot_titles=[f"{symbol} {d['timeframe']} (Cashflow: {d.get('cashflow','N/A')})" for d in mtf_data_list])
    
    for i, data in enumerate(mtf_data_list):
        _add_ob_traces_and_shapes(fig, data['ohlc_data'], data['ob_list'], symbol, data['timeframe'], row=i+1, col=1)
        
    fig.update_layout(
        title=f"{symbol} Multi-Timeframe OB Analysis",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=500 * num_tf,
        showlegend=False
    )
    
    # Range sliders are annoying in subplots, disable them for all
    # Also skip weekend gaps
    for i in range(1, num_tf + 1):
        fig.update_xaxes(
            rangeslider_visible=False, 
            rangebreaks=[dict(bounds=["sat", "mon"])],
            row=i, col=1
        )

    fig.write_html(filename, include_plotlyjs="cdn")
    print(f"MTF Chart saved to {filename}")
