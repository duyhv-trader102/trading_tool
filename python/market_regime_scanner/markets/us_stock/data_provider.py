from typing import List
from markets.base.data_provider import MT5DataProvider
from .config import US_STOCK_SYMBOLS

class USStockDataProvider(MT5DataProvider):
    def get_all_symbols(self) -> List[str]:
        return US_STOCK_SYMBOLS
