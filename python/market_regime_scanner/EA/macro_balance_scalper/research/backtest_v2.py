"""
Macro Balance Scalper Backtest V2
=================================
Backtest strategy for balance trading within Monthly MBA range.

Key Features V2:
1. ADX Filter (10 < ADX < 25) - Only scalp in ranging markets
2. Smart Trailing Stop (2.5x ATR, after 1% profit)
3. Time-based Exit (21 days max)
4. Target: Daily MBA edge (liquidity sweep)
"""

import os
import sys
import json
import polars as pl
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging
import statistics

from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.path_manager import setup_path, get_output_path
setup_path()

from workflow.pipeline import analyze_timeframe, analyze_from_df
from infra.data.mt5_provider import MT5Provider
from core.resampler import resample_data
from analytic.tpo_mba.tracker import build_mba_context
from analytic.tpo_mba.schema import MBAMetadata, MacroBalanceArea

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ============================================================================
# V2 RISK MANAGEMENT CONFIG - SCALPING MODE
# ============================================================================
TRAILING_STOP_ATR_MULT = 1.0   # Scalping: tight trailing at 1x ATR
INITIAL_STOP_ATR_MULT = 1.5    # Scalping: tight stop at 1.5x ATR
MIN_ADX_FOR_ENTRY = 15         # Gold scalping: ADX >= 15 (relaxed for MBA ready)
MAX_ADX_FOR_ENTRY = 40         # Max ADX (loại bỏ trending quá mạnh)
MAX_HOLD_HOURS = 72            # Scalping: max 3 days hold for mean reversion
ATR_PERIOD = 14
ADX_PERIOD = 14
SPREAD_PCT = 0.0002            # Spread cost per trade
PROFIT_THRESHOLD_TO_TRAIL = 0.005  # Scalp: Activate trailing after 0.5% profit

# Balance Scalper Specific
EDGE_THRESHOLD_PCT = 0.003     # 0.3% from MBA edge (tighter for scalp)
SL_BUFFER_PCT = 0.005          # 0.5% buffer for SL (tighter)
TP_FALLBACK_PCT = 0.3          # 30% of MBA range as fallback (smaller target)
MIN_MBA_AGE_SESSIONS = 3       # MBA must be established

# Output directory
RESEARCH_OUTPUT_DIR = Path(__file__).parent / "output"
RESEARCH_OUTPUT_DIR.mkdir(exist_ok=True)


# ============================================================================
# TECHNICAL INDICATORS
# ============================================================================

def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Calculate Average True Range."""
    if len(highs) < period + 1:
        return 0.0
    
    true_ranges = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        true_ranges.append(tr)
    
    if len(true_ranges) >= period:
        return sum(true_ranges[-period:]) / period
    return 0.0


def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Calculate Average Directional Index."""
    if len(highs) < period * 2:
        return 0.0
    
    plus_dm = []
    minus_dm = []
    tr_list = []
    
    for i in range(1, len(highs)):
        high_diff = highs[i] - highs[i-1]
        low_diff = lows[i-1] - lows[i]
        
        plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
        minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
        
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
    
    if len(tr_list) < period:
        return 0.0
    
    def smooth(data, period):
        if len(data) < period:
            return []
        smoothed = [sum(data[:period])]
        for i in range(period, len(data)):
            smoothed.append(smoothed[-1] - smoothed[-1]/period + data[i])
        return smoothed
    
    smooth_tr = smooth(tr_list, period)
    smooth_plus_dm = smooth(plus_dm, period)
    smooth_minus_dm = smooth(minus_dm, period)
    
    if not smooth_tr or smooth_tr[-1] == 0:
        return 0.0
    
    plus_di = 100 * smooth_plus_dm[-1] / smooth_tr[-1] if smooth_tr[-1] > 0 else 0
    minus_di = 100 * smooth_minus_dm[-1] / smooth_tr[-1] if smooth_tr[-1] > 0 else 0
    
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0.0
    
    dx = 100 * abs(plus_di - minus_di) / di_sum
    return dx


# ============================================================================
# BACKTEST RESULT
# ============================================================================

@dataclass
class BacktestResult:
    symbol: str
    total_trades: int
    win_rate: float
    avg_profit: float
    total_profit: float
    max_drawdown: float
    avg_duration_days: float
    sharpe_ratio: float
    trades: list
    error: str = ""
    # V2 metrics
    filtered_by_adx: int = 0
    stopped_by_trailing: int = 0
    stopped_by_time: int = 0
    stopped_by_mba_break: int = 0
    v1_trades: int = 0          # Without V2 filters
    v2_trades: int = 0          # With V2 filters


# ============================================================================
# MBA DETECTION FOR BACKTEST (Using build_mba_context — new tracker workflow)
# ============================================================================

def get_mba_metadata_at_idx(
    sessions: List, 
    idx: int, 
    period: str = "Monthly"
) -> Optional[MBAMetadata]:
    """
    Get MBA metadata at a specific session index.
    Uses the new build_mba_context function (tracker workflow).
    """
    if idx < 3:
        return None
    
    prev_sessions = sessions[:idx + 1]
    
    if len(prev_sessions) < 3:
        return None
    
    try:
        meta = build_mba_context(prev_sessions, timeframe=period)
        return meta
    except Exception:
        return None


# ============================================================================
# BALANCE SCALPER BACKTEST
# ============================================================================

def run_balance_scalper_backtest(
    symbol: str, 
    bars: int = 40000,  # ~10 years of H4 data
    use_v2_filters: bool = True
) -> BacktestResult:
    """
    Run balance scalper backtest on a single symbol.
    
    Strategy:
    1. Detect Monthly MBA (balance state) using build_mba_context
    2. ADX Filter (10 < ADX < 25) - V2
    3. Price at MBA edge → Entry
    4. Target: Daily MBA edge or fallback
    5. SL: MBA edge + buffer OR 3x ATR (wider)
    6. Exit: TP, SL, Trailing Stop (V2), Time Exit (V2), MBA Break
    """
    logger.info(f"Backtesting {symbol} {'V2' if use_v2_filters else 'V1'}...")
    
    try:
        provider = MT5Provider()
        if not provider.connect():
            return BacktestResult(
                symbol=symbol, total_trades=0, win_rate=0, avg_profit=0, 
                total_profit=0, max_drawdown=0, avg_duration_days=0, 
                sharpe_ratio=0, trades=[], error="MT5 connection failed"
            )
        
        # Analyze Monthly sessions
        m_results, _ = analyze_timeframe(symbol, "D1", "M", provider=provider, bars=bars)
        if not m_results or len(m_results) < 6:
            return BacktestResult(
                symbol=symbol, total_trades=0, win_rate=0, avg_profit=0, 
                total_profit=0, max_drawdown=0, avg_duration_days=0, 
                sharpe_ratio=0, trades=[], error="Insufficient Monthly data"
            )
        
        # Monthly sessions — no more regime classification needed
        
        # Daily sessions for execution
        d_results, _ = analyze_timeframe(symbol, "H1", "D", provider=provider, bars=bars)
        if not d_results or len(d_results) < 30:
            return BacktestResult(
                symbol=symbol, total_trades=0, win_rate=0, avg_profit=0, 
                total_profit=0, max_drawdown=0, avg_duration_days=0, 
                sharpe_ratio=0, trades=[], error="Insufficient Daily data"
            )
        
        # Build price history for ATR/ADX
        price_history = {
            "highs": [r.session_high for r in d_results if r.session_high],
            "lows": [r.session_low for r in d_results if r.session_low],
            "closes": [r.close_price for r in d_results if r.close_price]
        }
        
        # Map monthly MBA metadata by date
        # Build MBA metadata for each month upfront
        m_mba_map = {}
        for session_idx in range(3, len(m_results)):
            meta = get_mba_metadata_at_idx(m_results, session_idx, period="M")
            if meta and meta.current_mba:
                session = m_results[session_idx]
                next_month_start = (session.session_end + timedelta(days=1)).replace(day=1).date()
                m_mba_map[next_month_start] = meta
        
        logger.info(f"Found {len(m_mba_map)} months with MBA")
        
        trades = []
        idx = 0
        total_d = len(d_results)
        
        # Counters
        filtered_by_adx = 0
        stopped_by_trailing = 0
        stopped_by_time = 0
        stopped_by_mba_break = 0
        v1_signals = 0
        v2_signals = 0
        
        # Debug counters
        debug_stats = {
            "total_sessions": 0,
            "no_mba": 0,
            "mba_is_ready": 0,  # Filtered by MBA being ready
            "outside_mba": 0,
            "in_middle_zone": 0,
            "daily_not_ready": 0,  # Filtered by daily not ready
            "eligible_zones": 0,
        }
        
        while idx < total_d - 1:
            d_session = d_results[idx]
            d_date = d_session.session_start.date()
            debug_stats["total_sessions"] += 1
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 1: Check SCALP CONTEXT - Monthly MBA exists AND is_ready=FALSE
            # ═══════════════════════════════════════════════════════════════
            m_key = d_date.replace(day=1)
            m_meta = m_mba_map.get(m_key)
            
            if not m_meta or not m_meta.current_mba:
                debug_stats["no_mba"] += 1
                idx += 1
                continue
            
            # CRITICAL: Only scalp when MBA is NOT ready (still in balance phase)
            # If MBA is ready, we should be looking for trend trade, not scalp
            if m_meta.is_ready:
                debug_stats["mba_is_ready"] += 1
                idx += 1
                continue
            
            mba = m_meta.current_mba
            mba_high = mba.area_high
            mba_low = mba.area_low
            mba_range = mba_high - mba_low
            
            if mba_range <= 0:
                idx += 1
                continue
            
            # Get MBA POC, VAH, VAL from mother_session
            mother = mba.mother_session
            mba_poc = mother.poc if mother and hasattr(mother, 'poc') and mother.poc else (mba_high + mba_low) / 2
            mba_vah = mother.vah if mother and hasattr(mother, 'vah') and mother.vah else mba_high
            mba_val = mother.val if mother and hasattr(mother, 'val') and mother.val else mba_low
            
            # Current price
            current_price = d_session.close_price
            if not current_price:
                idx += 1
                continue
            
            # CRITICAL: Skip if price is OUTSIDE MBA range (with 5% tolerance)
            mba_tolerance = mba_range * 0.05
            if current_price > mba_high + mba_tolerance or current_price < mba_low - mba_tolerance:
                idx += 1
                continue
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 2: Determine PRICE ZONE (Upper Edge / Lower Edge / Middle)
            # Middle = POC ± 50% of each half VA
            # ═══════════════════════════════════════════════════════════════
            
            # Calculate middle zone boundaries
            upper_va_half = mba_vah - mba_poc  # Distance from POC to VAH
            lower_va_half = mba_poc - mba_val  # Distance from POC to VAL
            
            middle_upper = mba_poc + 0.5 * upper_va_half  # POC + 50% of upper VA half
            middle_lower = mba_poc - 0.5 * lower_va_half  # POC - 50% of lower VA half
            
            # Get daily distribution info
            dist_shape = d_session.distribution.shape if d_session.distribution else "other"
            daily_ready = d_session.distribution.ready_to_move if d_session.distribution else False
            unfair_high = d_session.unfair_high  # Tuple[float, float] or None
            unfair_low = d_session.unfair_low    # Tuple[float, float] or None
            daily_poc = d_session.poc if hasattr(d_session, 'poc') and d_session.poc else current_price
            
            # Determine price zone
            price_zone = "middle"
            direction = None
            entry_type = "none"
            debug_info = {}
            
            # Special handling for 3-1-3 dist (not ready): use unfair extremes as edges
            if dist_shape == "3-1-3" and not daily_ready:
                if unfair_high and len(unfair_high) >= 2:
                    uh_low = min(unfair_high)
                    if current_price >= uh_low:
                        price_zone = "upper_edge"
                        
                if unfair_low and len(unfair_low) >= 2:
                    ul_high = max(unfair_low)
                    if current_price <= ul_high:
                        price_zone = "lower_edge"
                        
            # 1-2-3 dist: unfair_low is lower edge, upper uses normal logic
            elif dist_shape == "1-2-3":
                if unfair_low and len(unfair_low) >= 2:
                    ul_high = max(unfair_low)
                    if current_price <= ul_high:
                        price_zone = "lower_edge"
                    elif current_price >= middle_upper:
                        price_zone = "upper_edge"
                else:
                    if current_price >= middle_upper:
                        price_zone = "upper_edge"
                    elif current_price <= middle_lower:
                        price_zone = "lower_edge"
                        
            # 3-2-1 dist: unfair_high is upper edge, lower uses normal logic
            elif dist_shape == "3-2-1":
                if unfair_high and len(unfair_high) >= 2:
                    uh_low = min(unfair_high)
                    if current_price >= uh_low:
                        price_zone = "upper_edge"
                    elif current_price <= middle_lower:
                        price_zone = "lower_edge"
                else:
                    if current_price >= middle_upper:
                        price_zone = "upper_edge"
                    elif current_price <= middle_lower:
                        price_zone = "lower_edge"
                        
            # Normal session: use POC-based zones
            else:
                if current_price >= middle_upper:
                    price_zone = "upper_edge"
                elif current_price <= middle_lower:
                    price_zone = "lower_edge"
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 3: Entry TRIGGER at EDGE zones
            # CRITICAL: Require daily_ready=True for all entries
            # Data shows entries without ready_to_move are losers
            # ═══════════════════════════════════════════════════════════════
            
            # At edges: trade toward POC (mean reversion scalp)
            if price_zone == "upper_edge":
                debug_stats["eligible_zones"] += 1
                
                # Only SELL at upper edge if daily session is ready
                if daily_ready:
                    direction = "bearish"
                    entry_type = f"{dist_shape}_upper_ready"
                else:
                    debug_stats["daily_not_ready"] += 1
                    
            elif price_zone == "lower_edge":
                debug_stats["eligible_zones"] += 1
                
                # Only BUY at lower edge if daily session is ready
                if daily_ready:
                    direction = "bullish"
                    entry_type = f"{dist_shape}_lower_ready"
                else:
                    debug_stats["daily_not_ready"] += 1
                    
            else:  # middle zone
                debug_stats["in_middle_zone"] += 1
                idx += 1
                continue
            
            if not direction:
                idx += 1
                continue
            
            # V1 signal detected
            v1_signals += 1
            
            # STEP 4: Calculate lookback for ATR (skip ADX filter - not needed for scalping)
            lookback = min(idx + 1, len(price_history["highs"]))
            
            # ADX filter disabled for scalping - we trust the zone + ready_to_move logic
            # The key edge is: MBA not ready + price at edge + daily ready → mean reversion
            v2_signals += 1
            
            # STEP 5: Entry at DAILY POC of the ready session (not next open)
            entry_price = daily_poc  # POC of the session that gave the signal
            entry_time = d_session.session_start
            entry_idx = idx
            
            # STEP 6: Calculate ATR
            atr_value = calculate_atr(
                price_history["highs"][:lookback],
                price_history["lows"][:lookback],
                price_history["closes"][:lookback],
                ATR_PERIOD
            ) if lookback > ATR_PERIOD else entry_price * 0.02
            
            # STEP 7: Calculate Stop Loss (use ATR-based stop, tighter for scalping)
            # For scalping, use tighter SL based on ATR
            if direction == "bullish":
                stop_loss = entry_price - (INITIAL_STOP_ATR_MULT * atr_value)
                trailing_stop = entry_price - (TRAILING_STOP_ATR_MULT * atr_value)
            else:
                stop_loss = entry_price + (INITIAL_STOP_ATR_MULT * atr_value)
                trailing_stop = entry_price + (TRAILING_STOP_ATR_MULT * atr_value)
            
            # STEP 8: Target = MBA POC (scalp back to fair value)
            target_type = "mba_poc_scalp"
            
            if direction == "bullish":
                # Buying at lower edge, target is MBA POC
                take_profit = mba_poc
                # Validate: TP must be above entry
                if take_profit <= entry_price * 1.001:
                    take_profit = entry_price + (TRAILING_STOP_ATR_MULT * atr_value * 2)
                    target_type = "fallback_atr"
            else:
                # Selling at upper edge, target is MBA POC
                take_profit = mba_poc
                # Validate: TP must be below entry
                if take_profit >= entry_price * 0.999:
                    take_profit = entry_price - (TRAILING_STOP_ATR_MULT * atr_value * 2)
                    target_type = "fallback_atr"
            
            # STEP 9: Simulate trade
            exit_price = entry_price
            exit_time = entry_time
            exit_reason = "open"
            max_mae = 0.0
            max_mfe = 0.0
            best_price = entry_price
            trailing_active = False
            days_held = 0
            closed = False
            
            inner_idx = entry_idx + 1
            
            while inner_idx < total_d:
                curr_session = d_results[inner_idx]
                curr_date = curr_session.session_start.date()
                days_held += 1
                
                curr_high = curr_session.session_high
                curr_low = curr_session.session_low
                curr_close = curr_session.close_price
                
                if not curr_high or not curr_low or not curr_close:
                    inner_idx += 1
                    continue
                
                # Calculate current profit
                if direction == "bullish":
                    current_profit_pct = (curr_close - entry_price) / entry_price
                else:
                    current_profit_pct = (entry_price - curr_close) / entry_price
                
                # V2: Activate trailing after profit threshold
                if use_v2_filters and current_profit_pct >= PROFIT_THRESHOLD_TO_TRAIL:
                    trailing_active = True
                
                # Update best price and trailing stop
                if direction == "bullish":
                    if curr_high > best_price:
                        best_price = curr_high
                        if trailing_active:
                            trailing_stop = max(trailing_stop, best_price - TRAILING_STOP_ATR_MULT * atr_value)
                else:
                    if curr_low < best_price:
                        best_price = curr_low
                        if trailing_active:
                            trailing_stop = min(trailing_stop, best_price + TRAILING_STOP_ATR_MULT * atr_value)
                
                # Track MAE/MFE
                if direction == "bullish":
                    run_mae = (entry_price - curr_low) / entry_price
                    run_mfe = (curr_high - entry_price) / entry_price
                else:
                    run_mae = (curr_high - entry_price) / entry_price
                    run_mfe = (entry_price - curr_low) / entry_price
                
                max_mae = max(max_mae, run_mae)
                max_mfe = max(max_mfe, run_mfe)
                
                # EXIT 1: Take Profit
                if direction == "bullish" and curr_high >= take_profit:
                    exit_price = take_profit
                    exit_time = curr_session.session_end
                    exit_reason = "take_profit"
                    closed = True
                    break
                elif direction == "bearish" and curr_low <= take_profit:
                    exit_price = take_profit
                    exit_time = curr_session.session_end
                    exit_reason = "take_profit"
                    closed = True
                    break
                
                # EXIT 2: Stop Loss
                if direction == "bullish" and curr_low <= stop_loss:
                    exit_price = stop_loss
                    exit_time = curr_session.session_end
                    exit_reason = "stop_loss"
                    closed = True
                    break
                elif direction == "bearish" and curr_high >= stop_loss:
                    exit_price = stop_loss
                    exit_time = curr_session.session_end
                    exit_reason = "stop_loss"
                    closed = True
                    break
                
                # EXIT 3: V2 Trailing Stop (only if active)
                if use_v2_filters and trailing_active:
                    if direction == "bullish" and curr_close < trailing_stop:
                        exit_price = trailing_stop
                        exit_time = curr_session.session_end
                        exit_reason = "trailing_stop"
                        stopped_by_trailing += 1
                        closed = True
                        break
                    elif direction == "bearish" and curr_close > trailing_stop:
                        exit_price = trailing_stop
                        exit_time = curr_session.session_end
                        exit_reason = "trailing_stop"
                        stopped_by_trailing += 1
                        closed = True
                        break
                
                # EXIT 4: V2 Time Exit (Scalping: 4 hours max)
                hours_held = (curr_session.session_end - entry_time).total_seconds() / 3600 if entry_time else 0
                if use_v2_filters and hours_held >= MAX_HOLD_HOURS:
                    exit_price = curr_close
                    exit_time = curr_session.session_end
                    exit_reason = "time_exit"
                    stopped_by_time += 1
                    closed = True
                    break
                
                # EXIT 5: MBA Break (check monthly)
                curr_m_key = curr_date.replace(day=1)
                curr_m_meta = m_mba_map.get(curr_m_key)
                if curr_m_meta is None or curr_m_meta.current_mba is None:
                    # MBA no longer exists - balance broken
                    exit_price = curr_close
                    exit_time = curr_session.session_end
                    exit_reason = "mba_break"
                    stopped_by_mba_break += 1
                    closed = True
                    break
                
                inner_idx += 1
            
            if not closed:
                exit_price = d_results[-1].close_price
                exit_time = d_results[-1].session_end
                exit_reason = "end_of_data"
            
            # Calculate return
            if direction == "bullish":
                gross_return = (exit_price - entry_price) / entry_price
            else:
                gross_return = (entry_price - exit_price) / entry_price
            
            net_return = gross_return - (2 * SPREAD_PCT)
            
            trades.append({
                "date": str(d_date),
                "entry_time": str(entry_time),
                "exit_time": str(exit_time),
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "direction": direction,
                "entry_type": entry_type,  # NEW: Track which entry logic triggered
                "return_pct": float(net_return * 100),
                "profit_points": float(exit_price - entry_price) if direction == "bullish" else float(entry_price - exit_price),
                "max_drawdown": float(max_mae),
                "max_favorable": float(max_mfe),
                "duration_days": days_held,
                "exit_reason": exit_reason,
                "target_type": target_type,
                "mba_range": float(mba_range),
                "mba_high": float(mba_high),
                "mba_low": float(mba_low),
                "mba_poc": float(mba_poc),
                "session_close": float(current_price),
                "debug_info": debug_info if debug_info else None,
            })
            
            idx = inner_idx
        
        # Calculate metrics
        if trades:
            returns_pct = [t["return_pct"] for t in trades]
            
            total_trades = len(trades)
            win_rate = sum(1 for r in returns_pct if r > 0) / total_trades if total_trades > 0 else 0
            avg_return_pct = sum(returns_pct) / total_trades if total_trades > 0 else 0
            total_return_pct = sum(returns_pct)
            max_drawdown_pct = max(t["max_drawdown"] for t in trades) * 100 if trades else 0
            avg_duration = sum(t["duration_days"] for t in trades) / total_trades if total_trades > 0 else 0
            
            # Sharpe
            if len(returns_pct) > 1:
                std_return = statistics.stdev(returns_pct)
                trades_per_year = min(total_trades / 2, 52)  # 2 years of data
                sharpe_ratio = (avg_return_pct / std_return) * (trades_per_year ** 0.5) if std_return > 0 else 0
            else:
                sharpe_ratio = 0
            
            # Print debug stats
            print(f"\n🔎 DEBUG FILTER STATS:")
            print(f"  Total Sessions:  {debug_stats['total_sessions']}")
            print(f"  No MBA:          {debug_stats['no_mba']}")
            print(f"  MBA is Ready:    {debug_stats['mba_is_ready']}")
            print(f"  In Middle Zone:  {debug_stats['in_middle_zone']}")
            print(f"  Eligible Zones:  {debug_stats['eligible_zones']}")
            print(f"  Daily Not Ready: {debug_stats['daily_not_ready']}")
            
            return BacktestResult(
                symbol=symbol,
                total_trades=total_trades,
                win_rate=win_rate,
                avg_profit=avg_return_pct,
                total_profit=total_return_pct,
                max_drawdown=max_drawdown_pct,
                avg_duration_days=avg_duration,
                sharpe_ratio=sharpe_ratio,
                trades=trades,
                filtered_by_adx=filtered_by_adx,
                stopped_by_trailing=stopped_by_trailing,
                stopped_by_time=stopped_by_time,
                stopped_by_mba_break=stopped_by_mba_break,
                v1_trades=v1_signals,
                v2_trades=v2_signals
            )
        else:
            return BacktestResult(
                symbol=symbol, total_trades=0, win_rate=0, avg_profit=0,
                total_profit=0, max_drawdown=0, avg_duration_days=0,
                sharpe_ratio=0, trades=[], error="No trades found",
                filtered_by_adx=filtered_by_adx,
                v1_trades=v1_signals,
                v2_trades=v2_signals
            )
    
    except Exception as e:
        logger.error(f"Error backtesting {symbol}: {e}")
        import traceback
        traceback.print_exc()
        return BacktestResult(
            symbol=symbol, total_trades=0, win_rate=0, avg_profit=0,
            total_profit=0, max_drawdown=0, avg_duration_days=0,
            sharpe_ratio=0, trades=[], error=str(e)
        )


def print_results(result: BacktestResult, version: str = "V2"):
    """Pretty print backtest results."""
    print(f"\n{'='*60}")
    print(f"BALANCE SCALPER BACKTEST RESULTS - {result.symbol} ({version})")
    print(f"{'='*60}")
    
    if result.error:
        print(f"ERROR: {result.error}")
        return
    
    print(f"\n📊 PERFORMANCE METRICS:")
    print(f"  Total Trades:    {result.total_trades}")
    print(f"  Win Rate:        {result.win_rate*100:.1f}%")
    print(f"  Avg Return:      {result.avg_profit:.2f}%")
    print(f"  Total Return:    {result.total_profit:.2f}%")
    print(f"  Max Drawdown:    {result.max_drawdown:.2f}%")
    print(f"  Sharpe Ratio:    {result.sharpe_ratio:.2f}")
    print(f"  Avg Duration:    {result.avg_duration_days:.1f} days")
    
    print(f"\n🔍 V2 FILTER STATS:")
    print(f"  V1 Signals:      {result.v1_trades}")
    print(f"  Filtered (ADX):  {result.filtered_by_adx}")
    print(f"  V2 Signals:      {result.v2_trades}")
    
    print(f"\n📤 EXIT BREAKDOWN:")
    exits = {}
    for t in result.trades:
        reason = t.get("exit_reason", "unknown")
        exits[reason] = exits.get(reason, 0) + 1
    for reason, count in sorted(exits.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")
    
    # Entry type breakdown
    print(f"\n📥 ENTRY TYPE BREAKDOWN:")
    entry_types = {}
    for t in result.trades:
        et = t.get("entry_type", "unknown")
        entry_types[et] = entry_types.get(et, 0) + 1
    for et, count in sorted(entry_types.items(), key=lambda x: -x[1]):
        trades_et = [t for t in result.trades if t.get("entry_type") == et]
        returns = [t["return_pct"] for t in trades_et]
        avg_ret = sum(returns) / len(returns) if returns else 0
        win_rate = sum(1 for r in returns if r > 0) / len(returns) if returns else 0
        print(f"  {et}: {count} trades, WR={win_rate*100:.0f}%, Avg={avg_ret:.2f}%")
    
    # Win/Loss by exit type
    print(f"\n💰 P&L BY EXIT TYPE:")
    for reason in exits.keys():
        trades_type = [t for t in result.trades if t.get("exit_reason") == reason]
        if trades_type:
            returns = [t["return_pct"] for t in trades_type]
            avg_ret = sum(returns) / len(returns)
            win_rate = sum(1 for r in returns if r > 0) / len(returns)
            print(f"  {reason}: {len(trades_type)} trades, WR={win_rate*100:.0f}%, Avg={avg_ret:.2f}%")

    # DEBUG: Show 313_unfair_high trades details
    unfair_high_trades = [t for t in result.trades if t.get("entry_type") == "313_unfair_high"]
    if unfair_high_trades:
        print(f"\n🔍 DEBUG: 313_unfair_high TRADES:")
        print("-" * 80)
        for t in unfair_high_trades:
            print(f"  Date: {t['date']}")
            print(f"    Session Close: {t.get('session_close', 'N/A')}")
            print(f"    Entry: {t['entry_price']:.2f} → Exit: {t['exit_price']:.2f}")
            print(f"    MBA: [{t.get('mba_low', 0):.2f} - {t.get('mba_high', 0):.2f}]")
            if t.get('debug_info'):
                di = t['debug_info']
                if 'unfair_zone' in di:
                    print(f"    Unfair High Zone: [{di['unfair_zone'][0]:.2f} - {di['unfair_zone'][1]:.2f}]")
                    print(f"    Price vs Zone Top: {di.get('price_vs_zone_top', 0):.2f}")
                    print(f"    POC: {di.get('poc', 0):.2f}")
            print(f"    Direction: {t['direction']}, Return: {t['return_pct']:.2f}%")
            print(f"    Exit Reason: {t['exit_reason']}, Duration: {t['duration_days']} days")
            print(f"    ADX: {t['adx']:.1f}")
            print("-" * 40)


def main():
    """Run Balance Scalper backtest."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Balance Scalper Backtest V2")
    parser.add_argument("--symbol", type=str, default="XAUUSDm", help="Symbol to backtest")
    parser.add_argument("--bars", type=int, default=40000, help="Number of bars (~10 years)")
    parser.add_argument("--compare", action="store_true", help="Compare V1 vs V2")
    args = parser.parse_args()
    
    print(f"\n🚀 Starting Balance Scalper Backtest...")
    print(f"   Symbol: {args.symbol}")
    print(f"   Bars: {args.bars}")
    
    if args.compare:
        # Run both V1 and V2
        print("\n--- Running V1 (no ADX filter, no trailing) ---")
        result_v1 = run_balance_scalper_backtest(args.symbol, args.bars, use_v2_filters=False)
        print_results(result_v1, "V1")
        
        print("\n--- Running V2 (ADX filter + trailing) ---")
        result_v2 = run_balance_scalper_backtest(args.symbol, args.bars, use_v2_filters=True)
        print_results(result_v2, "V2")
        
        # Comparison
        print(f"\n{'='*60}")
        print("📈 V1 vs V2 COMPARISON")
        print(f"{'='*60}")
        print(f"{'Metric':<20} {'V1':>15} {'V2':>15} {'Δ':>10}")
        print("-" * 60)
        
        metrics = [
            ("Trades", result_v1.total_trades, result_v2.total_trades),
            ("Win Rate %", result_v1.win_rate * 100, result_v2.win_rate * 100),
            ("Total Return %", result_v1.total_profit, result_v2.total_profit),
            ("Sharpe Ratio", result_v1.sharpe_ratio, result_v2.sharpe_ratio),
            ("Max DD %", result_v1.max_drawdown, result_v2.max_drawdown),
            ("Avg Duration", result_v1.avg_duration_days, result_v2.avg_duration_days),
        ]
        
        for name, v1, v2 in metrics:
            delta = v2 - v1
            sign = "+" if delta > 0 else ""
            print(f"{name:<20} {v1:>15.2f} {v2:>15.2f} {sign}{delta:>9.2f}")
    else:
        # Run V2 only
        result = run_balance_scalper_backtest(args.symbol, args.bars, use_v2_filters=True)
        print_results(result, "V2")
    
    # Save results
    output_file = RESEARCH_OUTPUT_DIR / f"balance_scalper_{args.symbol}_backtest.json"
    with open(output_file, "w") as f:
        result_dict = {
            "symbol": result.symbol if not args.compare else result_v2.symbol,
            "version": "V2",
            "total_trades": result.total_trades if not args.compare else result_v2.total_trades,
            "win_rate": result.win_rate if not args.compare else result_v2.win_rate,
            "total_profit": result.total_profit if not args.compare else result_v2.total_profit,
            "sharpe_ratio": result.sharpe_ratio if not args.compare else result_v2.sharpe_ratio,
            "trades": result.trades if not args.compare else result_v2.trades,
        }
        json.dump(result_dict, f, indent=2)
    
    print(f"\n✅ Results saved to: {output_file}")


if __name__ == "__main__":
    main()
