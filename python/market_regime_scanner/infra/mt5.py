import logging

import MetaTrader5 as mt5

from infra.data.utils.tf_mapping import mt5_timeframe

logger = logging.getLogger(__name__)


def start_mt5(username, password, server, mt5Pathway):
    """
    Initialize MT5 connection to a specific terminal.
    Always uses the provided path to ensure connecting to the correct terminal.
    
    Raises:
        ConnectionError: If MT5 fails to initialize.
        RuntimeError: If account info cannot be retrieved after login.
    """
    # Always shutdown first to ensure clean state
    mt5.shutdown()
    
    # Initialize with specific path - always use provided pathway
    if not mt5.initialize(path=mt5Pathway):
        logger.error("Failed to initialize MT5 at: %s — %s", mt5Pathway, mt5.last_error())
        # Try without path as fallback
        if not mt5.initialize():
            raise ConnectionError(
                f"Failed to initialize MT5 (fallback also failed): {mt5.last_error()}"
            )
        else:
            logger.warning("Connected to default terminal, not specified path!")
    
    # Verify terminal path
    terminal_info = mt5.terminal_info()
    if terminal_info:
        logger.info("Connected to: %s", terminal_info.path)
    
    # Check if we are already logged into the right account
    acc_info = mt5.account_info()
    if acc_info is None or acc_info.login != username:
        logger.info("Logging in as %s...", username)
        if not mt5.login(login=username, password=password, server=server):
            logger.error("Login failed: %s", mt5.last_error())
            # We don't raise here as sometimes data can still be fetched if terminal is already manually logged in

    # Get account info
    account_info = mt5.account_info()
    if account_info is None:
        mt5.shutdown()
        raise RuntimeError("Failed to get account info after MT5 login")


def set_query_timeframe(timeframe):
    """Convert timeframe string to MT5 constant.

    Delegates to ``infra.data.utils.tf_mapping.mt5_timeframe``.
    """
    return mt5_timeframe(timeframe)


def get_tick_size(symbol: str) -> float:
    """
    Get the minimum tick size for a symbol from MT5.
    This is equivalent to MQL5's _Point or SymbolInfoDouble(SYMBOL_TRADE_TICK_SIZE).
    
    Args:
        symbol: Trading symbol (e.g., 'XAUUSDm', 'EURUSD')
    
    Returns:
        Tick size (e.g., 0.01 for XAUUSD, 0.00001 for EURUSD)
    """
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        logger.error("Failed to get symbol info for %s", symbol)
        return 0.01  # Default fallback
    
    return symbol_info.trade_tick_size


def get_historical_data(symbol, timeframe, number_of_bars):
    # Ensure MT5 is initialized AND logged into the CORRECT account from settings
    from infra.settings_loader import get_mt5_config
    config = get_mt5_config()
    expected_login = int(config['username'])
    
    mt5.initialize()  # Try to init first
    account_info = mt5.account_info()
    
    # Check if logged into correct account, not just any account
    if account_info is None or account_info.login != expected_login:
        logger.info("Connecting to correct MT5 terminal (account %s)...", expected_login)
        try:
            start_mt5(
                username=expected_login,
                password=config['password'],
                server=config['server'],
                mt5Pathway=config['mt5Pathway']
            )
        except Exception as e:
            logger.error("Could not auto-connect MT5: %s", e)
            return None
    mt5_timeframe = set_query_timeframe(timeframe)
    if mt5_timeframe is None:
        logger.error("Invalid timeframe: %s", timeframe)
        return None
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        logger.error("Symbol not found or not in Market Watch: %s", symbol)
        return None
    if not symbol_info.visible:
        logger.warning("Symbol %s not visible in Market Watch. Attempting to add...", symbol)
        if not mt5.symbol_select(symbol, True):
            logger.error("Failed to add symbol %s to Market Watch", symbol)
            return None
    rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, number_of_bars)
    if rates is None or len(rates) == 0:
        logger.error("Failed to get historical data for %s (tf=%s, bars=%d)", symbol, timeframe, number_of_bars)
        logger.debug("mt5.last_error: %s", mt5.last_error())
        return None
    return rates


# =============================================================================
# Execution & Trading Functions
# =============================================================================

def get_account_info():
    """Returns MT5 account information."""
    mt5.initialize()
    return mt5.account_info()


def get_open_positions(symbol: str = None):
    """Returns a list of open positions, optionally filtered by symbol."""
    mt5.initialize()
    if symbol:
        return mt5.positions_get(symbol=symbol)
    return mt5.positions_get()


def place_order(symbol: str, side: str, volume: float, sl: float = None, tp: float = None, comment: str = ""):
    """
    Places a market order.
    side: 'buy' or 'sell'
    """
    mt5.initialize()
    
    # 1. Prepare Request
    order_type = mt5.ORDER_TYPE_BUY if side.lower() == 'buy' else mt5.ORDER_TYPE_SELL
    price = mt5.symbol_info_tick(symbol).ask if side.lower() == 'buy' else mt5.symbol_info_tick(symbol).bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "magic": 123456, # Default EA Magic Number
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    if sl: request["sl"] = sl
    if tp: request["tp"] = tp

    # 2. Send Order
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Order failed: {result.retcode} - {result.comment}")
        return None
        
    logger.info(f"Order placed successfully: Ticket {result.order}")
    return result


def close_position(ticket: int, comment: str = ""):
    """Closes an open position by ticket."""
    mt5.initialize()
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        logger.error(f"Position {ticket} not found.")
        return False
        
    pos = positions[0]
    symbol = pos.symbol
    volume = pos.volume
    order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = mt5.symbol_info_tick(symbol).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).ask
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "position": ticket,
        "price": price,
        "magic": 123456,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Close failed: {result.retcode} - {result.comment}")
        return False
        
    logger.info(f"Position {ticket} closed.")
    return True
