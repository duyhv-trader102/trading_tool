import logging
from datetime import datetime, timedelta
import polars as pl
from core.tpo import TPOResult, TPOProfile
from analytic.tpo_mba.tracker import build_mba_context
from analytic.tpo_mba.detector import find_last_directional_move
from analytic.tpo_mba.alignment import build_tf_regime
from viz.tpo_visualizer import visualize_tpo_topdown
from data_providers import get_data as _shared_get_data

logger = logging.getLogger("BaseVizTPOChart")

class BaseVizTPOChart:
    def __init__(self, data_provider, market_name: str, output_dir: str):
        self.data_provider = data_provider
        self.market_name = market_name
        self.output_dir = output_dir

    def build_composite_tpo(self, df: pl.DataFrame, session_period: str, tick_size: float, has_weekend: bool = False) -> list[TPOResult]:
        """Build Composite TPO Sessions using core.tpo.TPOProfile."""
        sessions_dfs = []
        
        def get_period_key(dt, period):
            if period == '1M':
                return dt.year * 100 + dt.month
            elif period == '1W':
                return dt.isocalendar()[0] * 100 + dt.isocalendar()[1]
            return dt.toordinal()

        bar_rows = df.to_dicts()
        current_rows = []
        last_key = None
        
        for bar in bar_rows:
            dt = bar['time']
            key = get_period_key(dt, session_period)
            if last_key is not None and key != last_key:
                if current_rows: sessions_dfs.append(pl.DataFrame(current_rows))
                current_rows = []
            current_rows.append(bar)
            last_key = key
        if current_rows: sessions_dfs.append(pl.DataFrame(current_rows))
            
        tpo_analyzer = TPOProfile(tick_size=tick_size, va_percentage=0.7, ib_bars=2) 
        results = []
        for s_df in sessions_dfs:
            # Pass has_weekend to analyze_session
            s_type = 'M' if session_period == '1M' else ('W' if session_period == '1W' else 'D')
            res = tpo_analyzer.analyze_session(s_df, session_type=s_type, has_weekend=has_weekend)
            dt = res.session_start
            new_start = dt
            if session_period == '1M':
                new_start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            elif session_period == '1W':
                days_to_subtract = dt.weekday()
                new_start = dt - timedelta(days=days_to_subtract)
                new_start = new_start.replace(hour=0, minute=0, second=0, microsecond=0)
            try: res.session_start = new_start
            except: pass
            results.append(res)
        return results

    def generate_tpo_chart(self, symbol: str, tick_size: float = None):
        """Generate Top-Down TPO Chart using analyze_dynamic for consistency with scanner."""
        # Fetch data for each layer with appropriate limits
        # Monthly needs more history to detect the "Anchor" move
        # Determine has_weekend based on market
        has_weekend = self.market_name.upper() in ('COIN', 'BINANCE')

        # Use shared data provider (parquet-first, same as scanner) to ensure
        # chart and scanner produce identical MBA results.
        df_w1 = _shared_get_data(symbol, 'W1', has_weekend=has_weekend)
        df_d1 = _shared_get_data(symbol, 'D1', has_weekend=has_weekend)
        
        if df_w1 is None or df_d1 is None or df_d1.is_empty():
            logger.error(f"Missing data for {symbol}")
            return
        weekend_mode = 'SatSun' if has_weekend else 'Ignore'

        # Use analyze_dynamic (same as scanner) for consistent session types
        tpo_engine = TPOProfile(va_percentage=0.7, ib_bars=2)
        vis_m = tpo_engine.analyze_dynamic(
            df_w1, session_type='M', weekend=weekend_mode,
        )
        vis_w = tpo_engine.analyze_dynamic(
            df_d1, session_type='W', weekend=weekend_mode,
        )

        # Fix session_start dates for display
        for res in vis_m:
            dt = res.session_start
            new_start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            try: res.session_start = new_start
            except: pass
        for res in vis_w:
            dt = res.session_start
            days_to_subtract = dt.weekday()
            new_start = dt - timedelta(days=days_to_subtract)
            new_start = new_start.replace(hour=0, minute=0, second=0, microsecond=0)
            try: res.session_start = new_start
            except: pass
        
        # Slicing logic for MBA — only use closed sessions
        def get_closed_end(sessions):
            if not sessions: return 0
            return len(sessions) - 1 if not sessions[-1].is_closed else len(sessions)

        ce_m = get_closed_end(vis_m)
        ce_w = get_closed_end(vis_w)

        # Build metadata from closed sessions
        meta_m = build_mba_context(vis_m[:ce_m], symbol=symbol, timeframe="Monthly") if ce_m > 0 else None
        meta_w = build_mba_context(vis_w[:ce_w], symbol=symbol, timeframe="Weekly") if ce_w > 0 else None

        # Compute TFRegime (BREAKOUT/IN BALANCE/WAITING) — same logic as scanner
        regime_m = build_tf_regime(meta_m, vis_m)
        regime_w = build_tf_regime(meta_w, vis_w)

        import os
        filename_symbol = symbol.replace("/", "_").replace(":", "_")
        output_file = os.path.join(self.output_dir, f"{filename_symbol}_TPO_TopDown.html")
        
        # Display slices
        disp_m = vis_m[-10:] if len(vis_m) > 10 else vis_m
        disp_w = vis_w[-15:] if len(vis_w) > 15 else vis_w

        # Use the last session's block_size as representative for display
        block_m = vis_m[-1].block_size if vis_m else 1.0
        block_w = vis_w[-1].block_size if vis_w else 1.0

        mtf_results = {
            'Monthly': {
                'results': disp_m, 
                'period': 'W1',
                'block_size': block_m, 
                'mba_metadata': meta_m,
                'tf_regime': regime_m,
                'macro_balance': meta_m.current_mba if meta_m else None,
                'regimes': []
            },
            'Weekly': {
                'results': disp_w, 
                'period': 'D1',
                'block_size': block_w, 
                'mba_metadata': meta_w,
                'tf_regime': regime_w,
                'macro_balance': meta_w.current_mba if meta_w else None,
                'regimes': []
            }
        }

        # Generate HTML in memory.
        html = visualize_tpo_topdown(
            mtf_results=mtf_results, filename=output_file,
            symbol=symbol, return_html=True,
        )

        if not html:
            return None

        # Always write to local disk so the dashboard can link to it directly.
        import os
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as fh:
            fh.write(html)
        logger.info("Chart saved locally: %s", output_file)

        # Also upload to S3 as archival backup (fire-and-forget).
        try:
            from infra.s3_storage import _get_singleton
            s3 = _get_singleton()
            if s3 is not None:
                key = s3._report_key(output_file)
                s3.client.put_object(
                    Bucket=s3._bucket, Key=key,
                    Body=html.encode("utf-8"),
                    ContentType="text/html",
                )
                logger.info("Chart uploaded to S3: %s", key)
        except Exception as exc:
            logger.debug("S3 chart upload failed: %s", exc)

        return None
