"""
EA Manager - Macro Balance Scalper

Orchestrates:
1. Symbol analysis and signal generation
2. Position sizing based on 2% risk
3. Order execution and state management
4. Exit monitoring
"""
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from EA.macro_balance_scalper.config import (
    TRADING_CONFIG, 
    STATE_FILE, 
    DEFAULT_MAGIC,
    ACCOUNT_BALANCE,
    RISK_PERCENT,
    MAX_RISK_USD,
    COOLDOWN_DAYS,
)
from EA.macro_balance_scalper.strategy import MacroBalanceScalperStrategy, BalanceTradeSignal
from infra import mt5 as mt5_infra

logger = logging.getLogger(__name__)


class BalanceScalperManager:
    """
    Manages the Macro Balance Scalper EA lifecycle.
    
    Position Sizing:
    - Risk per trade: 2% of account balance
    - lot_size = (risk_amount / (SL_distance * pip_value))
    """
    
    def __init__(self, account_balance: float = None):
        self.strategy = MacroBalanceScalperStrategy()
        self.state = self._load_state()
        self.account_balance = account_balance or ACCOUNT_BALANCE
        self.risk_per_trade = self.account_balance * RISK_PERCENT
        
        logger.info(f"Balance Scalper Manager initialized")
        logger.info(f"  Account Balance: ${self.account_balance:.2f}")
        logger.info(f"  Risk per Trade: ${self.risk_per_trade:.2f} ({RISK_PERCENT*100:.1f}%)")
    
    def _load_state(self) -> Dict:
        """Load persistent state from file."""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load state: {e}")
        return {
            "active_trades": {},
            "cooldowns": {},
            "stats": {"total_trades": 0, "wins": 0, "losses": 0}
        }
    
    def _save_state(self):
        """Persist state to file."""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)
    
    def calculate_lot_size(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float
    ) -> float:
        """
        Calculate position size based on 2% risk model.
        
        Formula:
            lot_size = risk_amount / (SL_distance * pip_value * contract_size)
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price
            stop_loss: Stop loss price
            
        Returns:
            Lot size (rounded to symbol's lot step)
        """
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance == 0:
            logger.warning(f"{symbol}: SL distance is 0, cannot calculate lot size")
            return 0.0
        
        # Get symbol info from MT5
        symbol_info = mt5_infra.get_symbol_info(symbol)
        if symbol_info is None:
            logger.error(f"{symbol}: Cannot get symbol info")
            return 0.0
        
        contract_size = symbol_info.trade_contract_size
        tick_size = symbol_info.trade_tick_size
        tick_value = symbol_info.trade_tick_value
        lot_min = symbol_info.volume_min
        lot_max = symbol_info.volume_max
        lot_step = symbol_info.volume_step
        
        # Calculate pip value per lot
        # pip_value = tick_value / tick_size  # Value per price unit per lot
        if tick_size > 0:
            pip_value_per_lot = tick_value / tick_size
        else:
            pip_value_per_lot = contract_size
        
        # Required lot size for risk
        # risk_amount = lot_size * sl_distance * pip_value_per_lot
        # lot_size = risk_amount / (sl_distance * pip_value_per_lot)
        lot_size = self.risk_per_trade / (sl_distance * pip_value_per_lot)
        
        # Round to lot step
        lot_size = max(lot_min, min(lot_max, lot_size))
        lot_size = round(lot_size / lot_step) * lot_step
        lot_size = round(lot_size, 2)  # Clean up floating point
        
        # Calculate actual risk for this lot size
        actual_risk = lot_size * sl_distance * pip_value_per_lot
        
        logger.info(
            f"[{symbol}] POSITION SIZING:\n"
            f"  SL Distance: {sl_distance:.5f}\n"
            f"  Pip Value/Lot: ${pip_value_per_lot:.2f}\n"
            f"  Target Risk: ${self.risk_per_trade:.2f}\n"
            f"  Calculated Lot: {lot_size:.2f}\n"
            f"  Actual Risk: ${actual_risk:.2f}"
        )
        
        return lot_size
    
    def _check_cooldown(self, symbol: str) -> bool:
        """Check if symbol is in cooldown period after a loss."""
        cooldowns = self.state.get("cooldowns", {})
        if symbol in cooldowns:
            cooldown_end = datetime.fromisoformat(cooldowns[symbol])
            if datetime.now() < cooldown_end:
                remaining = (cooldown_end - datetime.now()).days
                logger.debug(f"{symbol}: In cooldown for {remaining} more days")
                return True
            else:
                # Cooldown expired, remove it
                del cooldowns[symbol]
        return False
    
    def _set_cooldown(self, symbol: str):
        """Set cooldown period for symbol after a loss."""
        cooldown_end = datetime.now() + timedelta(days=COOLDOWN_DAYS)
        if "cooldowns" not in self.state:
            self.state["cooldowns"] = {}
        self.state["cooldowns"][symbol] = cooldown_end.isoformat()
        logger.info(f"{symbol}: Cooldown set until {cooldown_end.date()}")
    
    def run_tick(self):
        """Run one iteration of the EA loop."""
        logger.info(f"═══ Balance Scalper Tick: {datetime.now().strftime('%Y-%m-%d %H:%M')} ═══")
        
        # 1. Connect MT5
        from scripts.mt5.observer import connect_mt5, ensure_data, TIMEFRAMES
        if not connect_mt5():
            logger.error("MT5 Connection failed")
            return
        
        # 2. Ensure data availability for all symbols
        symbols_list = [
            {"symbol": sym, "has_weekend": cfg.get("has_weekend", False)} 
            for sym, cfg in TRADING_CONFIG.items()
        ]
        ensure_data(symbols_list, TIMEFRAMES)
        
        # 3. Process each symbol
        for symbol, config in TRADING_CONFIG.items():
            self._process_symbol(symbol, config)
        
        self._save_state()
        logger.info(f"═══ Tick Complete ═══")
    
    def _process_symbol(self, symbol: str, config: Dict):
        """Process one symbol - check exits or entries."""
        has_weekend = config.get("has_weekend", False)
        
        # ═══════════════════════════════════════════════════════════════
        # A. Sync state with MT5
        # ═══════════════════════════════════════════════════════════════
        open_positions = mt5_infra.get_open_positions(symbol)
        active_trade = self.state["active_trades"].get(symbol)
        
        # If state says we have a position but MT5 doesn't, clear state
        if active_trade:
            ticket = active_trade.get("ticket")
            if not any(p.ticket == ticket for p in open_positions):
                logger.warning(f"{symbol}: Position {ticket} closed externally")
                self.state["active_trades"].pop(symbol, None)
                active_trade = None
        
        # ═══════════════════════════════════════════════════════════════
        # B. If we have a position, check for EXIT
        # ═══════════════════════════════════════════════════════════════
        if active_trade:
            self._check_position_exit(symbol, active_trade, has_weekend)
            return
        
        # ═══════════════════════════════════════════════════════════════
        # C. If no position, check for ENTRY
        # ═══════════════════════════════════════════════════════════════
        
        # Check cooldown
        if self._check_cooldown(symbol):
            return
        
        # Get signal from strategy
        signal = self.strategy.evaluate(symbol, has_weekend, True)
        if signal is None:
            return
        
        # Execute trade
        self._execute_entry(symbol, signal, config)
    
    def _check_position_exit(
        self, 
        symbol: str, 
        trade_info: Dict, 
        has_weekend: bool
    ):
        """Check if open position should be exited."""
        entry_time = datetime.fromisoformat(trade_info["entry_time"])
        
        should_exit, reason = self.strategy.should_exit(
            symbol=symbol,
            entry_price=trade_info["entry_price"],
            direction=trade_info["direction"],
            stop_loss=trade_info["stop_loss"],
            take_profit=trade_info["take_profit"],
            entry_time=entry_time,
            has_weekend=has_weekend,
            mt5_connected=True
        )
        
        if should_exit:
            ticket = trade_info["ticket"]
            logger.info(f"[{symbol}] Closing position {ticket}: {reason}")
            
            if mt5_infra.close_position(ticket, comment=f"Balance Scalper - {reason}"):
                # Update stats
                if reason == "take_profit":
                    self.state["stats"]["wins"] += 1
                elif reason == "stop_loss":
                    self.state["stats"]["losses"] += 1
                    self._set_cooldown(symbol)
                
                self.state["stats"]["total_trades"] += 1
                self.state["active_trades"].pop(symbol, None)
                
                self._log_stats()
    
    def _execute_entry(
        self, 
        symbol: str, 
        signal: BalanceTradeSignal, 
        config: Dict
    ):
        """Execute entry order based on signal."""
        # Calculate position size
        lot_size = self.calculate_lot_size(
            symbol=symbol,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss
        )
        
        if lot_size <= 0:
            logger.error(f"{symbol}: Invalid lot size calculated")
            return
        
        # Execute order
        if signal.direction == "bullish":
            order_type = "buy"
        else:
            order_type = "sell"
        
        result = mt5_infra.place_order(
            symbol=symbol,
            order_type=order_type,
            lot=lot_size,
            sl=signal.stop_loss,
            tp=signal.take_profit,
            comment=f"BalanceScalper-{signal.signal_strength}",
            magic=DEFAULT_MAGIC
        )
        
        if result and result.retcode == mt5_infra.TRADE_RETCODE_DONE:
            ticket = result.order
            logger.info(f"[{symbol}] Order executed: Ticket {ticket}, {lot_size} lots")
            
            # Save to state
            self.state["active_trades"][symbol] = {
                "ticket": ticket,
                "direction": signal.direction,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "lot_size": lot_size,
                "entry_time": signal.timestamp.isoformat(),
                "target_type": signal.target_type,
                "mba_high": signal.monthly_mba_high,
                "mba_low": signal.monthly_mba_low,
            }
        else:
            error_code = result.retcode if result else "N/A"
            logger.error(f"{symbol}: Order failed - Error code: {error_code}")
    
    def _log_stats(self):
        """Log trading statistics."""
        stats = self.state["stats"]
        total = stats["total_trades"]
        wins = stats["wins"]
        losses = stats["losses"]
        
        if total > 0:
            win_rate = (wins / total) * 100
            logger.info(
                f"═══ STATS ═══\n"
                f"  Total Trades: {total}\n"
                f"  Wins: {wins} | Losses: {losses}\n"
                f"  Win Rate: {win_rate:.1f}%"
            )
    
    def get_status(self) -> Dict:
        """Get current EA status for monitoring."""
        return {
            "account_balance": self.account_balance,
            "risk_per_trade": self.risk_per_trade,
            "active_trades": len(self.state["active_trades"]),
            "total_trades": self.state["stats"]["total_trades"],
            "win_rate": (
                self.state["stats"]["wins"] / self.state["stats"]["total_trades"] * 100
                if self.state["stats"]["total_trades"] > 0 else 0
            ),
            "positions": list(self.state["active_trades"].keys()),
        }


def run_ea(interval_minutes: int = 60):
    """
    Main entry point for running the EA.
    
    Args:
        interval_minutes: Time between ticks (default 60 min)
    """
    manager = BalanceScalperManager()
    
    logger.info("Macro Balance Scalper EA started")
    logger.info(f"Interval: {interval_minutes} minutes")
    
    while True:
        try:
            manager.run_tick()
        except Exception as e:
            logger.error(f"EA tick error: {e}")
        
        logger.info(f"Next tick in {interval_minutes} minutes...")
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    run_ea()
