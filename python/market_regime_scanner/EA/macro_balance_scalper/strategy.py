"""
Macro Balance Scalper Strategy

Core Logic: Trade bounces within Monthly MBA range, targeting Daily MBA (nested balance).
Rule: Imbalance → Balance → Imbalance (I→B→I fractal)

Entry Conditions:
1. Monthly session is in balance (has MBA)
2. Price at MBA edge: > area_high → SELL, < area_low → BUY
3. Weekly shows compression (optional filter)
4. Daily ready signal aligned with edge direction

Exit Conditions:
1. Hit target: Nearest Daily MBA within 1M MBA range
2. Hit stop loss: Beyond MBA edge + buffer
3. Time exit: MAX_HOLD_DAYS exceeded
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import pandas as pd
from datetime import datetime, timedelta

from scripts.mt5.observer import analyze_symbol, connect_mt5
from analytic.tpo_mba.schema import MacroBalanceArea, MBAUnit, MBAMetadata
from infra import mt5 as mt5_infra
from EA.macro_balance_scalper.config import (
    EDGE_THRESHOLD_PCT,
    SL_BUFFER_PCT,
    TP_FALLBACK_PCT,
    MAX_HOLD_DAYS,
    MIN_MBA_AGE_SESSIONS,
    REQUIRE_WEEKLY_COMPRESSION,
)

logger = logging.getLogger(__name__)


@dataclass
class BalanceTradeSignal:
    """Signal data for a balance scalp trade."""
    symbol: str
    direction: str                   # "bullish" or "bearish"
    entry_price: float
    stop_loss: float
    take_profit: float
    monthly_mba_high: float
    monthly_mba_low: float
    target_type: str                 # "daily_mba" or "fallback"
    signal_strength: str             # "STRONG" or "MODERATE"
    timestamp: datetime


class MacroBalanceScalperStrategy:
    """
    Strategy for trading bounces within Monthly MBA range.
    
    Key Concept:
    - Monthly MBA defines the macro balance range
    - Daily MBA units within the 1M range are targets (I→B→I fractal)
    - Buy at low edge, sell at high edge
    """
    
    def __init__(self):
        self.last_signal_time: Dict[str, datetime] = {}
    
    def evaluate(
        self, 
        symbol: str, 
        has_weekend: bool, 
        mt5_connected: bool
    ) -> Optional[BalanceTradeSignal]:
        """
        Evaluate symbol for balance scalp opportunity.
        
        Returns:
            BalanceTradeSignal if entry conditions met, None otherwise.
        """
        try:
            # ═══════════════════════════════════════════════════════════════
            # STEP 1: Get TPO Analysis Results
            # ═══════════════════════════════════════════════════════════════
            symbol_res = analyze_symbol(symbol, has_weekend, mt5_connected)
            if not symbol_res:
                logger.debug(f"{symbol}: No analysis result")
                return None
            
            # Get metadata for each timeframe
            tf_metas = symbol_res.tf_metas
            monthly_meta = tf_metas.get("Monthly")
            weekly_meta = tf_metas.get("Weekly")
            daily_meta = tf_metas.get("Daily")
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 2: Check Monthly MBA Exists (Balance State)
            # ═══════════════════════════════════════════════════════════════
            if not monthly_meta or not monthly_meta.current_mba:
                logger.debug(f"{symbol}: No Monthly MBA - not in balance")
                return None
            
            mba_1m = monthly_meta.current_mba
            mba_high = mba_1m.area_high
            mba_low = mba_1m.area_low
            mba_range = mba_high - mba_low
            
            # Check MBA age (established balance)
            mba_units = mba_1m.all_units or []
            if len(mba_units) < MIN_MBA_AGE_SESSIONS:
                logger.debug(f"{symbol}: MBA too young ({len(mba_units)} units)")
                return None
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 3: Get Current Price & Check Position vs MBA Edge
            # ═══════════════════════════════════════════════════════════════
            rates = mt5_infra.get_historical_data(symbol, "D1", 5)
            if rates is None or len(rates) == 0:
                logger.debug(f"{symbol}: Cannot get current price")
                return None
            
            df = pd.DataFrame(rates)
            current_price = float(df.iloc[-1]['close'])
            
            # Determine direction based on price position
            edge_buffer = mba_range * EDGE_THRESHOLD_PCT
            direction = None
            signal_strength = "WEAK"
            
            # Price near LOW edge → BUY opportunity
            if current_price <= mba_low + edge_buffer:
                direction = "bullish"
                if current_price <= mba_low:  # At or below edge
                    signal_strength = "STRONG"
                else:
                    signal_strength = "MODERATE"
                    
            # Price near HIGH edge → SELL opportunity
            elif current_price >= mba_high - edge_buffer:
                direction = "bearish"
                if current_price >= mba_high:  # At or above edge
                    signal_strength = "STRONG"
                else:
                    signal_strength = "MODERATE"
            
            if direction is None:
                logger.debug(f"{symbol}: Price ${current_price:.4f} not at MBA edge "
                           f"[{mba_low:.4f} - {mba_high:.4f}]")
                return None
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 4: Weekly Compression Filter (Optional)
            # ═══════════════════════════════════════════════════════════════
            if REQUIRE_WEEKLY_COMPRESSION and weekly_meta:
                if not weekly_meta.is_compression:
                    logger.debug(f"{symbol}: No weekly compression")
                    return None
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 5: Daily Ready Signal Confirmation
            # ═══════════════════════════════════════════════════════════════
            if daily_meta:
                # Check if Daily is ready and aligned
                if daily_meta.is_ready:
                    daily_dir = daily_meta.ready_direction
                    if daily_dir and daily_dir != direction:
                        logger.debug(f"{symbol}: Daily ready but opposite ({daily_dir} vs {direction})")
                        return None
                    signal_strength = "STRONG"  # Boost confidence
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 6: Find Target - Nearest Daily MBA within 1M Range
            # ═══════════════════════════════════════════════════════════════
            take_profit = None
            target_type = "fallback"
            
            if daily_meta and daily_meta.current_mba:
                daily_mba = daily_meta.current_mba
                daily_units = daily_mba.all_units or [daily_mba]
                
                # Find Daily MBA units within 1M range
                targets = self._find_daily_targets(
                    daily_units, 
                    mba_high, 
                    mba_low, 
                    current_price, 
                    direction
                )
                
                if targets:
                    # Take nearest target (by edge, not mid)
                    nearest = min(targets, key=lambda t: abs(t["target"] - current_price))
                    take_profit = nearest["target"]
                    target_type = "daily_mba_edge"
                    logger.info(f"{symbol}: Found Daily MBA edge target at {take_profit:.4f}")
            # Fallback: Use percentage of MBA range
            if take_profit is None:
                if direction == "bullish":
                    take_profit = mba_low + (mba_range * TP_FALLBACK_PCT)
                else:
                    take_profit = mba_high - (mba_range * TP_FALLBACK_PCT)
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 7: Calculate Stop Loss
            # ═══════════════════════════════════════════════════════════════
            sl_buffer = mba_range * SL_BUFFER_PCT
            
            if direction == "bullish":
                stop_loss = mba_low - sl_buffer
            else:
                stop_loss = mba_high + sl_buffer
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 8: Build Signal
            # ═══════════════════════════════════════════════════════════════
            signal = BalanceTradeSignal(
                symbol=symbol,
                direction=direction,
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                monthly_mba_high=mba_high,
                monthly_mba_low=mba_low,
                target_type=target_type,
                signal_strength=signal_strength,
                timestamp=datetime.now(),
            )
            
            risk = abs(current_price - stop_loss)
            reward = abs(take_profit - current_price)
            rr_ratio = reward / risk if risk > 0 else 0
            
            logger.info(
                f"[{symbol}] BALANCE SCALP SIGNAL:\n"
                f"  Direction: {direction.upper()}\n"
                f"  Entry: {current_price:.4f}\n"
                f"  SL: {stop_loss:.4f} | TP: {take_profit:.4f}\n"
                f"  R:R = 1:{rr_ratio:.2f}\n"
                f"  MBA: [{mba_low:.4f} - {mba_high:.4f}]\n"
                f"  Target Type: {target_type}\n"
                f"  Strength: {signal_strength}"
            )
            
            return signal
            
        except Exception as e:
            logger.error(f"{symbol}: Strategy evaluation error: {e}")
            return None
    
    def _find_daily_targets(
        self,
        daily_units: List[MBAUnit],
        mba_high: float,
        mba_low: float,
        current_price: float,
        direction: str
    ) -> List[Dict]:
        """
        Find Daily MBA edges within 1M MBA range as targets.
        
        I→B→I (Imbalance → Balance → Imbalance) fractal:
        - Daily MBA forms within Monthly MBA (nested balance)
        - Target is the MBA EDGE (not mid) for liquidity sweep
        - BUY: target = area_high (highest edge)
        - SELL: target = area_low (lowest edge)
        """
        targets = []
        
        for unit in daily_units:
            # Check if Daily MBA is within Monthly MBA range
            unit_high = getattr(unit, 'area_high', None)
            unit_low = getattr(unit, 'area_low', None)
            
            if unit_high is None or unit_low is None:
                continue
            
            # Unit must be completely within 1M MBA
            if unit_high > mba_high or unit_low < mba_low:
                continue
            
            # Target the EDGE for liquidity sweep (quét thanh khoản ở biên)
            # BUY: aim for the HIGH edge of Daily MBA
            # SELL: aim for the LOW edge of Daily MBA
            if direction == "bullish" and unit_high > current_price:
                targets.append({
                    "high": unit_high,
                    "low": unit_low,
                    "target": unit_high,  # Target HIGH edge for BUY
                })
            elif direction == "bearish" and unit_low < current_price:
                targets.append({
                    "high": unit_high,
                    "low": unit_low,
                    "target": unit_low,  # Target LOW edge for SELL
                })
        
        return targets
    
    def should_exit(
        self,
        symbol: str,
        entry_price: float,
        direction: str,
        stop_loss: float,
        take_profit: float,
        entry_time: datetime,
        has_weekend: bool,
        mt5_connected: bool
    ) -> Tuple[bool, str]:
        """
        Check exit conditions for an open position.
        
        Returns:
            (should_exit, reason)
        """
        try:
            # Get current price
            rates = mt5_infra.get_historical_data(symbol, "D1", 1)
            if rates is None:
                return False, ""
            
            df = pd.DataFrame(rates)
            current_price = float(df.iloc[-1]['close'])
            current_high = float(df.iloc[-1]['high'])
            current_low = float(df.iloc[-1]['low'])
            
            # ═══════════════════════════════════════════════════════════════
            # EXIT 1: Take Profit Hit
            # ═══════════════════════════════════════════════════════════════
            if direction == "bullish" and current_high >= take_profit:
                return True, "take_profit"
            elif direction == "bearish" and current_low <= take_profit:
                return True, "take_profit"
            
            # ═══════════════════════════════════════════════════════════════
            # EXIT 2: Stop Loss Hit
            # ═══════════════════════════════════════════════════════════════
            if direction == "bullish" and current_low <= stop_loss:
                return True, "stop_loss"
            elif direction == "bearish" and current_high >= stop_loss:
                return True, "stop_loss"
            
            # ═══════════════════════════════════════════════════════════════
            # EXIT 3: Time-Based Exit
            # ═══════════════════════════════════════════════════════════════
            days_held = (datetime.now() - entry_time).days
            if days_held >= MAX_HOLD_DAYS:
                return True, "time_exit"
            
            # ═══════════════════════════════════════════════════════════════
            # EXIT 4: MBA Break - Monthly balance broken
            # ═══════════════════════════════════════════════════════════════
            symbol_res = analyze_symbol(symbol, has_weekend, mt5_connected)
            if symbol_res:
                monthly_meta = symbol_res.tf_metas.get("Monthly")
                if monthly_meta and not monthly_meta.current_mba:
                    # MBA broken - exit to avoid trend against us
                    return True, "mba_break"
            
            return False, ""
            
        except Exception as e:
            logger.error(f"{symbol}: Exit check error: {e}")
            return False, ""
