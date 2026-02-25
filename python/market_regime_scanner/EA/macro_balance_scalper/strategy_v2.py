"""
Macro Balance Scalper Strategy V2
=================================
V2 Improvements:
1. ADX Filter (10 < ADX < 25) - Only scalp in ranging markets
2. Smart Trailing Stop (2.5x ATR, activate ONLY after 1% profit)
3. Time-based Exit (21 days max)
4. Enhanced SL: MBA edge + buffer OR 3x ATR (whichever is wider)

Note: Balance scalper uses INVERTED ADX logic vs Trend Catcher:
- Trend Catcher: ADX > 18 (want strong trend)
- Balance Scalper: 10 < ADX < 25 (want ranging/consolidation)
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from scripts.mt5.observer import analyze_symbol, connect_mt5
from analytic.tpo_mba.schema import MacroBalanceArea, MBAUnit, MBAMetadata
from infra import mt5 as mt5_infra
from EA.macro_balance_scalper.config_v2 import (
    EDGE_THRESHOLD_PCT,
    SL_BUFFER_PCT,
    TP_FALLBACK_PCT,
    MAX_HOLD_HOURS,
    MIN_MBA_AGE_SESSIONS,
    REQUIRE_WEEKLY_COMPRESSION,
    MIN_ADX_FOR_ENTRY,
    MAX_ADX_FOR_ENTRY,
    TRAILING_STOP_ATR_MULT,
    INITIAL_STOP_ATR_MULT,
    PROFIT_THRESHOLD_TO_TRAIL,
    ATR_PERIOD,
    ADX_PERIOD,
    MIN_PROFIT_PCT_FOR_HOLD,
)

logger = logging.getLogger(__name__)


@dataclass
class BalanceTradeSignalV2:
    """V2 Signal data with enhanced risk management."""
    symbol: str
    direction: str                   # "bullish" or "bearish"
    entry_price: float
    stop_loss: float                 # Initial SL (MBA edge + buffer OR 3x ATR)
    take_profit: float
    trailing_stop: float             # For smart trailing (2.5x ATR)
    monthly_mba_high: float
    monthly_mba_low: float
    target_type: str                 # "daily_mba_edge" or "fallback"
    signal_strength: str             # "STRONG" or "MODERATE"
    timestamp: datetime
    # V2 fields
    atr: float
    adx: float
    risk_pct: float
    trailing_active: bool = False
    version: str = "V2"


class MacroBalanceScalperStrategyV2:
    """
    V2 Strategy for trading bounces within Monthly MBA range.
    
    Key Differences from V1:
    - ADX filter for ranging market confirmation (10 < ADX < 25)
    - Smart trailing stop only activates after 1% profit
    - Enhanced stop loss logic (wider of MBA edge or 3x ATR)
    """
    
    def __init__(self):
        self.last_signal_time: Dict[str, datetime] = {}
    
    def _calculate_adx(self, df: pd.DataFrame, period: int = ADX_PERIOD) -> float:
        """Calculate ADX (Average Directional Index)."""
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            
            # True Range
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(period).mean()
            
            # Directional Movement
            plus_dm = high.diff()
            minus_dm = -low.diff()
            plus_dm[plus_dm < 0] = 0
            minus_dm[minus_dm < 0] = 0
            plus_dm[(plus_dm < minus_dm)] = 0
            minus_dm[(minus_dm < plus_dm)] = 0
            
            # Smoothed DI
            plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
            minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
            
            # ADX
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
            adx = dx.rolling(period).mean()
            
            return float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0.0
        except Exception:
            return 0.0

    def _calculate_atr(self, df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
        """Calculate ATR for stop loss calculation."""
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(period).mean()
            
            return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.0
        except Exception:
            return 0.0

    def check_adx_filter(self, symbol: str, df: pd.DataFrame = None) -> Tuple[bool, float]:
        """
        V2 ADX Filter for balance trading.
        
        INVERTED from Trend Catcher:
        - Want 10 < ADX < 25 (ranging market, not trending)
        - If ADX too high → skip (trending, use Trend Catcher instead)
        - If ADX too low → skip (dead market)
        """
        if df is None:
            rates = mt5_infra.get_historical_data(symbol, "D1", 50)
            if rates is None:
                return False, 0.0
            df = pd.DataFrame(rates)
        
        adx = self._calculate_adx(df)
        
        # For balance trading: want RANGING market (low-mid ADX)
        passes = MIN_ADX_FOR_ENTRY <= adx <= MAX_ADX_FOR_ENTRY
        return passes, adx

    def calculate_stops(
        self, 
        direction: str, 
        entry_price: float, 
        mba_high: float, 
        mba_low: float, 
        atr: float
    ) -> Dict:
        """
        Calculate stop loss levels.
        
        V2 Logic:
        - Primary SL: MBA edge + buffer
        - Fallback SL: 3x ATR if MBA edge is too tight
        - Use WIDER of the two for safety
        """
        mba_range = mba_high - mba_low
        sl_buffer = mba_range * SL_BUFFER_PCT
        
        # MBA edge-based SL
        if direction == "bullish":
            mba_stop = mba_low - sl_buffer
            atr_stop = entry_price - (INITIAL_STOP_ATR_MULT * atr)
            # Use the LOWER stop (wider protection for buy)
            initial_stop = min(mba_stop, atr_stop)
            trailing_stop = entry_price - (TRAILING_STOP_ATR_MULT * atr)
        else:
            mba_stop = mba_high + sl_buffer
            atr_stop = entry_price + (INITIAL_STOP_ATR_MULT * atr)
            # Use the HIGHER stop (wider protection for sell)
            initial_stop = max(mba_stop, atr_stop)
            trailing_stop = entry_price + (TRAILING_STOP_ATR_MULT * atr)
        
        risk_pct = abs(entry_price - initial_stop) / entry_price * 100
        
        return {
            "initial_stop": initial_stop,
            "trailing_stop": trailing_stop,
            "mba_stop": mba_stop,
            "atr_stop": atr_stop,
            "risk_pct": risk_pct
        }

    def evaluate(
        self, 
        symbol: str, 
        has_weekend: bool, 
        mt5_connected: bool
    ) -> Optional[BalanceTradeSignalV2]:
        """
        V2 Evaluation with ADX Filter and enhanced risk management.
        
        Entry Conditions:
        1. Monthly MBA exists (balance state)
        2. ADX in range 10-25 (ranging, not trending)
        3. Price at MBA edge
        4. Weekly compression (optional)
        5. Daily ready confirmation
        """
        try:
            # ═══════════════════════════════════════════════════════════════
            # STEP 1: Get TPO Analysis Results
            # ═══════════════════════════════════════════════════════════════
            symbol_res = analyze_symbol(symbol, has_weekend, mt5_connected)
            if not symbol_res:
                logger.debug(f"{symbol}: No analysis result")
                return None
            
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
            
            mba_units = mba_1m.all_units or []
            if len(mba_units) < MIN_MBA_AGE_SESSIONS:
                logger.debug(f"{symbol}: MBA too young ({len(mba_units)} units)")
                return None
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 3: Get Price Data & Calculate Indicators
            # ═══════════════════════════════════════════════════════════════
            rates = mt5_infra.get_historical_data(symbol, "D1", 50)
            if rates is None or len(rates) == 0:
                logger.debug(f"{symbol}: Cannot get price data")
                return None
            
            df = pd.DataFrame(rates)
            current_price = float(df.iloc[-1]['close'])
            atr = self._calculate_atr(df)
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 4: V2 ADX Filter (Ranging Market Only)
            # ═══════════════════════════════════════════════════════════════
            adx_pass, adx_value = self.check_adx_filter(symbol, df)
            if not adx_pass:
                if adx_value > MAX_ADX_FOR_ENTRY:
                    logger.debug(f"[V2] Skipping {symbol}: ADX too high ({adx_value:.1f} > {MAX_ADX_FOR_ENTRY}) - use Trend Catcher")
                else:
                    logger.debug(f"[V2] Skipping {symbol}: ADX too low ({adx_value:.1f} < {MIN_ADX_FOR_ENTRY})")
                return None
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 5: Check Price Position vs MBA Edge
            # ═══════════════════════════════════════════════════════════════
            edge_buffer = mba_range * EDGE_THRESHOLD_PCT
            direction = None
            signal_strength = "WEAK"
            
            if current_price <= mba_low + edge_buffer:
                direction = "bullish"
                signal_strength = "STRONG" if current_price <= mba_low else "MODERATE"
            elif current_price >= mba_high - edge_buffer:
                direction = "bearish"
                signal_strength = "STRONG" if current_price >= mba_high else "MODERATE"
            
            if direction is None:
                logger.debug(f"{symbol}: Price {current_price:.4f} not at MBA edge [{mba_low:.4f} - {mba_high:.4f}]")
                return None
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 6: Weekly Compression Filter (Optional)
            # ═══════════════════════════════════════════════════════════════
            if REQUIRE_WEEKLY_COMPRESSION and weekly_meta:
                if not weekly_meta.is_compression:
                    logger.debug(f"{symbol}: No weekly compression")
                    return None
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 7: Daily Ready Confirmation
            # ═══════════════════════════════════════════════════════════════
            if daily_meta and daily_meta.is_ready:
                daily_dir = daily_meta.ready_direction
                if daily_dir and daily_dir != direction:
                    logger.debug(f"{symbol}: Daily opposite ({daily_dir} vs {direction})")
                    return None
                signal_strength = "STRONG"
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 8: Find Target - Daily MBA Edge
            # ═══════════════════════════════════════════════════════════════
            take_profit = None
            target_type = "fallback"
            
            if daily_meta and daily_meta.current_mba:
                daily_mba = daily_meta.current_mba
                daily_units = daily_mba.all_units or [daily_mba]
                
                targets = self._find_daily_targets(
                    daily_units, mba_high, mba_low, current_price, direction
                )
                
                if targets:
                    nearest = min(targets, key=lambda t: abs(t["target"] - current_price))
                    take_profit = nearest["target"]
                    target_type = "daily_mba_edge"
                    logger.info(f"{symbol}: Found Daily MBA edge at {take_profit:.4f}")
            
            if take_profit is None:
                if direction == "bullish":
                    take_profit = mba_low + (mba_range * TP_FALLBACK_PCT)
                else:
                    take_profit = mba_high - (mba_range * TP_FALLBACK_PCT)
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 9: Calculate Stop Losses (V2 Enhanced)
            # ═══════════════════════════════════════════════════════════════
            stops = self.calculate_stops(direction, current_price, mba_high, mba_low, atr)
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 10: Build V2 Signal
            # ═══════════════════════════════════════════════════════════════
            signal = BalanceTradeSignalV2(
                symbol=symbol,
                direction=direction,
                entry_price=current_price,
                stop_loss=stops["initial_stop"],
                take_profit=take_profit,
                trailing_stop=stops["trailing_stop"],
                monthly_mba_high=mba_high,
                monthly_mba_low=mba_low,
                target_type=target_type,
                signal_strength=signal_strength,
                timestamp=datetime.now(),
                atr=atr,
                adx=adx_value,
                risk_pct=stops["risk_pct"],
                trailing_active=False,
                version="V2"
            )
            
            risk = abs(current_price - stops["initial_stop"])
            reward = abs(take_profit - current_price)
            rr_ratio = reward / risk if risk > 0 else 0
            
            logger.info(
                f"[{symbol}] V2 BALANCE SCALP SIGNAL:\n"
                f"  Direction: {direction.upper()}\n"
                f"  Entry: {current_price:.4f}\n"
                f"  SL: {stops['initial_stop']:.4f} (Risk: {stops['risk_pct']:.1f}%)\n"
                f"  TP: {take_profit:.4f}\n"
                f"  Trailing: {stops['trailing_stop']:.4f} (activate after 1% profit)\n"
                f"  R:R = 1:{rr_ratio:.2f}\n"
                f"  ADX: {adx_value:.1f} | ATR: {atr:.4f}\n"
                f"  MBA: [{mba_low:.4f} - {mba_high:.4f}]\n"
                f"  Target: {target_type} | Strength: {signal_strength}"
            )
            
            return signal
            
        except Exception as e:
            logger.error(f"{symbol}: V2 Strategy error: {e}")
            return None

    def _find_daily_targets(
        self,
        daily_units: List,
        mba_high: float,
        mba_low: float,
        current_price: float,
        direction: str
    ) -> List[Dict]:
        """Find Daily MBA edges within 1M MBA range as targets."""
        targets = []
        
        for unit in daily_units:
            unit_high = getattr(unit, 'area_high', None)
            unit_low = getattr(unit, 'area_low', None)
            
            if unit_high is None or unit_low is None:
                continue
            
            if unit_high > mba_high or unit_low < mba_low:
                continue
            
            if direction == "bullish" and unit_high > current_price:
                targets.append({"target": unit_high})
            elif direction == "bearish" and unit_low < current_price:
                targets.append({"target": unit_low})
        
        return targets

    def check_trailing_activation(
        self, 
        direction: str, 
        entry_price: float, 
        current_price: float
    ) -> bool:
        """Check if profit threshold met to activate trailing stop."""
        if direction == "bullish":
            profit_pct = (current_price - entry_price) / entry_price
        else:
            profit_pct = (entry_price - current_price) / entry_price
        
        return profit_pct >= PROFIT_THRESHOLD_TO_TRAIL

    def update_trailing_stop(
        self, 
        symbol: str, 
        direction: str, 
        entry_price: float,
        current_trailing: float,
        trailing_active: bool = False
    ) -> Tuple[float, bool]:
        """
        V2 Smart Trailing Stop Update.
        Only moves in favorable direction after profit threshold met.
        """
        rates = mt5_infra.get_historical_data(symbol, "D1", 20)
        if rates is None:
            return current_trailing, trailing_active
        
        df = pd.DataFrame(rates)
        current_close = float(df.iloc[-1]['close'])
        atr = self._calculate_atr(df)
        
        if not trailing_active:
            trailing_active = self.check_trailing_activation(direction, entry_price, current_close)
            if trailing_active:
                logger.info(f"[V2] Trailing ACTIVATED for {symbol} at {current_close:.2f}")
        
        if not trailing_active:
            return current_trailing, False
        
        if direction == "bullish":
            new_trailing = current_close - (TRAILING_STOP_ATR_MULT * atr)
            final_trailing = max(new_trailing, current_trailing) if current_trailing else new_trailing
        else:
            new_trailing = current_close + (TRAILING_STOP_ATR_MULT * atr)
            final_trailing = min(new_trailing, current_trailing) if current_trailing else new_trailing
        
        return final_trailing, True

    def should_exit(
        self,
        symbol: str,
        entry_price: float,
        direction: str,
        stop_loss: float,
        take_profit: float,
        trailing_stop: float,
        trailing_active: bool,
        entry_time: datetime,
        has_weekend: bool,
        mt5_connected: bool
    ) -> Tuple[bool, str]:
        """
        V2 Enhanced Exit Logic:
        1. Take Profit hit
        2. Initial Stop Loss hit
        3. Smart Trailing Stop (only if active)
        4. Time-based Exit (21 days)
        5. MBA Break (monthly balance broken)
        """
        try:
            rates = mt5_infra.get_historical_data(symbol, "D1", 5)
            if rates is None:
                return False, ""
            
            df = pd.DataFrame(rates)
            current_close = float(df.iloc[-1]['close'])
            current_high = float(df.iloc[-1]['high'])
            current_low = float(df.iloc[-1]['low'])
            
            # 1. Take Profit
            if direction == "bullish" and current_high >= take_profit:
                return True, "TAKE_PROFIT"
            elif direction == "bearish" and current_low <= take_profit:
                return True, "TAKE_PROFIT"
            
            # 2. Initial Stop Loss
            if direction == "bullish" and current_low <= stop_loss:
                return True, "STOP_LOSS"
            elif direction == "bearish" and current_high >= stop_loss:
                return True, "STOP_LOSS"
            
            # 3. V2 Smart Trailing Stop (only if active)
            if trailing_active and trailing_stop is not None:
                if direction == "bullish" and current_close < trailing_stop:
                    logger.info(f"[V2] TRAILING STOP {symbol}: {current_close:.2f} < {trailing_stop:.2f}")
                    return True, "TRAILING_STOP"
                elif direction == "bearish" and current_close > trailing_stop:
                    logger.info(f"[V2] TRAILING STOP {symbol}: {current_close:.2f} > {trailing_stop:.2f}")
                    return True, "TRAILING_STOP"
            
            # 4. V2 Time-based Exit (Scalping: max 4 hours)
            if entry_time:
                hours_held = (datetime.now() - entry_time).total_seconds() / 3600
                if hours_held > MAX_HOLD_HOURS:
                    if direction == "bullish":
                        profit_pct = (current_close - entry_price) / entry_price * 100
                    else:
                        profit_pct = (entry_price - current_close) / entry_price * 100
                    
                    if profit_pct < MIN_PROFIT_PCT_FOR_HOLD:
                        logger.info(f"[V2] TIME EXIT {symbol}: {hours_held:.1f}h, {profit_pct:.2f}% profit")
                        return True, "TIME_EXIT"
            
            # 5. MBA Break
            symbol_res = analyze_symbol(symbol, has_weekend, mt5_connected)
            if symbol_res:
                monthly_meta = symbol_res.tf_metas.get("Monthly")
                if monthly_meta and not monthly_meta.current_mba:
                    return True, "MBA_BREAK"
            
            return False, ""
            
        except Exception as e:
            logger.error(f"{symbol}: V2 Exit check error: {e}")
            return False, ""

    def get_position_status(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        entry_time: datetime,
        current_trailing: float,
        trailing_active: bool
    ) -> Dict:
        """Get comprehensive position status for monitoring."""
        rates = mt5_infra.get_historical_data(symbol, "D1", 20)
        if rates is None:
            return {}
        
        df = pd.DataFrame(rates)
        current_close = float(df.iloc[-1]['close'])
        atr = self._calculate_atr(df)
        adx = self._calculate_adx(df)
        
        if direction == "bullish":
            profit_pct = (current_close - entry_price) / entry_price * 100
            profit_r = (current_close - entry_price) / (INITIAL_STOP_ATR_MULT * atr) if atr > 0 else 0
        else:
            profit_pct = (entry_price - current_close) / entry_price * 100
            profit_r = (entry_price - current_close) / (INITIAL_STOP_ATR_MULT * atr) if atr > 0 else 0
        
        hours_held = (datetime.now() - entry_time).total_seconds() / 3600 if entry_time else 0
        
        return {
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "current_price": current_close,
            "profit_pct": profit_pct,
            "profit_r": profit_r,
            "hours_held": hours_held,
            "trailing_stop": current_trailing,
            "trailing_active": trailing_active,
            "atr": atr,
            "adx": adx,
            "hours_remaining": MAX_HOLD_HOURS - hours_held,
            "version": "V2"
        }
