from typing import Dict, Type, List
from markets.base.data_provider import BaseDataProvider, MT5DataProvider
from markets.vnstock.data_provider import VNStockDataProvider
from markets.binance.data_provider import BinanceDataProvider
from markets.coin.data_provider import CoinDataProvider
from markets.fx.data_provider import FXDataProvider
from markets.comm.data_provider import CommodityDataProvider
from markets.us_stock.data_provider import USStockDataProvider

# Import configs or symbols if needed for default symbols
from markets.coin.config import COIN_SYMBOLS
from markets.fx.config import FX_SYMBOLS
from markets.comm.config import COMMODITY_SYMBOLS
from markets.us_stock.config import US_STOCK_SYMBOLS
from markets.binance.config import DEFAULT_SYMBOLS

from markets.vnstock.config import VN30_SYMBOLS, VN100_SYMBOLS

class MarketRegistry:
    _providers: Dict[str, Type[BaseDataProvider]] = {
        "COIN": CoinDataProvider,
        "FX": FXDataProvider,
        "COMM": CommodityDataProvider,
        "US_STOCK": USStockDataProvider,
        "VNSTOCK": VNStockDataProvider,
        "VN30": VNStockDataProvider,   # VN30 sub-market (subset of VNSTOCK)
        "BINANCE": BinanceDataProvider
    }
    
    _symbols: Dict[str, List[str]] = {
        "COIN": COIN_SYMBOLS,
        "FX": FX_SYMBOLS,
        "COMM": COMMODITY_SYMBOLS,
        "US_STOCK": US_STOCK_SYMBOLS,
        "VNSTOCK": [], # Default is All if empty
        "VN30": VN30_SYMBOLS,
        "BINANCE": DEFAULT_SYMBOLS
    }

    _groups: Dict[str, Dict[str, List[str]]] = {
        "VNSTOCK": {
            "VN30": VN30_SYMBOLS,
            "VN100": VN100_SYMBOLS
        }
    }

    @classmethod
    def get_provider(cls, market: str) -> BaseDataProvider:
        market = market.upper()
        if market not in cls._providers:
            raise ValueError(f"Unknown market: {market}")
        return cls._providers[market]()

    @classmethod
    def get_symbols(cls, market: str, group: str = None) -> List[str]:
        """Get symbols for market, optionally filtered by group."""
        market = market.upper()
        
        # Check group first
        if group:
            group = group.upper()
            
            # 1. Try dynamic fetching from provider
            try:
                provider = cls.get_provider(market)
                if hasattr(provider, 'get_group_symbols'):
                    symbols = provider.get_group_symbols(group)
                    if symbols: 
                        print(f"Fetched {len(symbols)} symbols for {group} from provider.")
                        return symbols
            except Exception as e:
                print(f"Provider dynamic fetch failed: {e}")

            # 2. Fallback to hardcoded groups
            if market in cls._groups and group in cls._groups[market]:
                return cls._groups[market][group]
            else:
                print(f"Warning: Group {group} not found for {market}. Using defaults.")

        if market not in cls._symbols:
            return []

        symbols = cls._symbols[market]

        # For VNSTOCK default, resolve live symbol list:
        # 1. Try API (VN100 dynamic list)
        # 2. Fallback to hardcoded VN100_SYMBOLS from config
        # 3. Last resort: read from disk (files already downloaded)
        if not symbols and market == "VNSTOCK":
            try:
                provider = cls.get_provider(market)
                api_syms = provider.get_group_symbols("VN100")
                if api_syms:
                    return api_syms
            except Exception:
                pass
            if VN100_SYMBOLS:
                return VN100_SYMBOLS
            return cls.get_provider(market).get_all_symbols()

        return symbols

    @classmethod
    def get_default_symbols(cls, market: str) -> List[str]:
        return cls.get_symbols(market)

    @classmethod
    def list_markets(cls) -> List[str]:
        return list(cls._providers.keys())
