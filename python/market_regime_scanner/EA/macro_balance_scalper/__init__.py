"""
Macro Balance Scalper EA

Strategy for trading bounces within Monthly MBA range,
targeting Daily MBA units (I→B→I fractal).
"""
from EA.macro_balance_scalper.strategy import MacroBalanceScalperStrategy, BalanceTradeSignal
from EA.macro_balance_scalper.manager import BalanceScalperManager, run_ea
from EA.macro_balance_scalper.config import TRADING_CONFIG, ACCOUNT_BALANCE, RISK_PERCENT

__all__ = [
    "MacroBalanceScalperStrategy",
    "BalanceTradeSignal",
    "BalanceScalperManager", 
    "run_ea",
    "TRADING_CONFIG",
    "ACCOUNT_BALANCE",
    "RISK_PERCENT",
]
