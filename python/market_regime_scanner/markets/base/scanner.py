import logging
from datetime import datetime
import polars as pl
from typing import Optional, List

from core.tpo import TPOResult, TPOProfile
from analytic.tpo_mba.tracker import build_mba_context
from analytic.tpo_mba.alignment import (
    build_tf_regime, evaluate_overall_signal, TFRegime, SignalResult,
)
from data_providers import get_data as _dp_get_data

logger = logging.getLogger("BaseScanner")

class BaseScanner:
    def __init__(self, provider=None, market_name: str = "FX"):
        self.provider = provider          # kept for backward-compat (legacy callers)
        self.market_name = market_name

    def analyze_timeframe(self, symbol: str, session_period: str):
        """Analyze a timeframe (Monthly, Weekly, or Daily).

        Data source — via UnifiedDataProvider (parquet-first, MT5 fallback):
          Monthly → W1 native bars
          Weekly  → D1 native bars
          Daily   → H4 bars
        No auto-resample: if W1/D1 unavailable the call returns None.
        """
        if session_period == '1M':
            bar_tf = 'W1'
        elif session_period == '1W':
            bar_tf = 'D1'
        else:
            bar_tf = 'H4'

        has_weekend = self.market_name.upper() in ('COIN', 'BINANCE')
        df = _dp_get_data(symbol, bar_tf, has_weekend=has_weekend)

        if df is None or df.is_empty():
            return None, None, 0

        tpo_engine = TPOProfile(va_percentage=0.7, ib_bars=2)
        sessions = tpo_engine.analyze_dynamic(
            df,
            session_type=session_period.replace('1', ''),
            weekend='SatSun' if has_weekend else 'Ignore'
        )
        
        if not sessions:
            return None, None, 0

        # 1. Determine closed_end for MBA calculation
        closed_end = len(sessions)
        if not sessions[-1].is_closed:
            closed_end = len(sessions) - 1

        # 2. Build MBA metadata using ONLY closed sessions (new tracker workflow)
        p_code = 'M' if session_period == '1M' else 'W'
        
        if closed_end > 0:
            metadata = build_mba_context(
                sessions[:closed_end],
                symbol=symbol,
                timeframe=p_code,
            )
        else:
            metadata = None

        return metadata, sessions, closed_end

    def get_regime_details(self, metadata, regime: TFRegime, label: str, sessions: list[TPOResult]) -> dict:
        """Build display-friendly dict from TFRegime + raw metadata/sessions.

        Core regime state (status, trend, readiness) comes from the
        centralised ``TFRegime``.  Display-only fields (MBA range,
        mother date, trigger session) are extracted here.
        """
        details = {
            "period": label,
            "status": regime.status,
            "trend": regime.trend,
            "range_low": None,
            "range_high": None,
            "mother_date": None,
            "continuity": 0,
            "is_ready": regime.is_ready,
            "ready_direction": regime.ready_direction,
            "ready_reason": "",
            "trigger_session_date": None,
        }

        if not metadata:
            return details

        mba = metadata.current_mba
        if mba and sessions:
            details["range_low"] = mba.area_low
            details["range_high"] = mba.area_high
            details["mother_date"] = mba.mother_session.session_start.date()
            if mba.mother_session in sessions:
                details["continuity"] = len(sessions) - 1 - sessions.index(mba.mother_session)

        # Ready display info
        if regime.is_ready and metadata:
            details["ready_reason"] = metadata.ready_reason or ""
            if metadata.trigger_session_index is not None and sessions:
                ti = metadata.trigger_session_index
                closed_sessions = [s for s in sessions if s.is_closed]
                if 0 <= ti < len(closed_sessions):
                    details["trigger_session_date"] = closed_sessions[ti].session_start.date()

        return details

    def analyze_symbol(self, symbol: str, print_report: bool = True) -> dict:
        """Analyze a symbol and return summary data."""
        meta_m, sess_m, count_m = self.analyze_timeframe(symbol, '1M')
        meta_w, sess_w, count_w = self.analyze_timeframe(symbol, '1W')

        # Build standardised TFRegimes using shared logic
        regime_m = build_tf_regime(meta_m, sess_m)
        regime_w = build_tf_regime(meta_w, sess_w)

        # Build display details
        details_m = self.get_regime_details(meta_m, regime_m, "MONTHLY", sess_m)
        details_w = self.get_regime_details(meta_w, regime_w, "WEEKLY", sess_w)

        if not details_m or not details_w:
            if print_report:
                print(f"\n[!] WARNING: Analysis failed for {symbol}")
                if not details_m: print(f"    - Missing Monthly context (Check W1 data)")
                if not details_w: print(f"    - Missing Weekly execution (Check D1 data)")
            return None

        # Evaluate overall signal using centralised logic
        result = evaluate_overall_signal(regime_m, regime_w)

        # Entry price = close of last closed weekly session (D1 bar)
        entry_price = None
        if sess_w and count_w > 0:
            last_closed = sess_w[count_w - 1]
            entry_price = getattr(last_closed, 'close_price', None)

        summary = {
            "symbol": symbol,
            "monthly": details_m,
            "weekly": details_w,
            "signal": result.signal,
            "entry_price": entry_price,
        }

        if print_report:
            self._print_single_report(summary)
            
        return summary

    def _print_single_report(self, s):
        print(f"\n{'='*60}")
        print(f"{self.market_name} REPORT: {s['symbol']}")
        print(f"{'='*60}")
        if s['signal']:
            print(f"*** SIGNAL: {s['signal']} ***")
        
        for p in ['monthly', 'weekly']:
            d = s[p]
            trend_display = d['trend'].upper() if d['trend'] != 'conflict' else 'CONFLICT'
            print(f"\n[{d['period']}]")
            print(f"  Status: {d['status']}")
            print(f"  Trend: {trend_display}")
            if d['range_low']:
                print(f"  Range: {d['range_low']:.2f} - {d['range_high']:.2f}")
                print(f"  Mother: {d['mother_date']} ({d['continuity']} bars)")
            print(f"  Ready: {'YES' if d['is_ready'] else 'NO'}")
            if d['is_ready']:
                print(f"    Reason: {d.get('ready_reason', '')}")
                if d.get('trigger_session_date'):
                    print(f"    Trigger Session: {d['trigger_session_date']}")
        print(f"{'='*60}\n")

    def print_table(self, results):
        if not results:
            print(f"\n[!] NO VALID RESULTS FOUND FOR {self.market_name.upper()}")
            print("-" * 40)
            return
        print("\n" + "="*150)

        print(f"{self.market_name} MARKET REGIME REPORT ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
        print("="*150)
        print(f"{'SYMBOL':<12} | {'SIGNAL':<18} | {'MONTHLY':<25} | {'WEEKLY':<25} | {'READY DETAIL':<40}")
        print("-" * 150)
        for r in results:
            sig = r['signal'] or "-"
            m_trend = r['monthly']['trend'].upper() if r['monthly']['trend'] != 'conflict' else 'CONFLICT'
            w_trend = r['weekly']['trend'].upper() if r['weekly']['trend'] != 'conflict' else 'CONFLICT'
            m_stat = f"{r['monthly']['status']} | {m_trend}"
            w_stat = f"{r['weekly']['status']} | {w_trend}"
            
            # Build ready detail string
            ready_parts = []
            for tf_key, tf_label in [('monthly', 'M'), ('weekly', 'W')]:
                d = r[tf_key]
                if d['is_ready']:
                    reason = d.get('ready_reason', '')
                    tdate = d.get('trigger_session_date', '')
                    # Extract short signal from reason, e.g. "READY bullish [normal_session] ..." -> "normal_session"
                    short_reason = ''
                    if '[' in reason and ']' in reason:
                        short_reason = reason[reason.index('[')+1:reason.index(']')]
                    direction = d['ready_direction'] or '?'
                    dir_label = 'Bull' if direction == 'bullish' else 'Bear' if direction == 'bearish' else '?'
                    detail = f"{tf_label}:READY({dir_label})"
                    if short_reason:
                        detail += f" [{short_reason}]"
                    if tdate:
                        detail += f" @{tdate}"
                    ready_parts.append(detail)
            ready_detail = " | ".join(ready_parts) if ready_parts else "-"
            
            print(f"{r['symbol']:<12} | {sig:<18} | {m_stat:<25} | {w_stat:<25} | {ready_detail}")
        print("="*150 + "\n")
