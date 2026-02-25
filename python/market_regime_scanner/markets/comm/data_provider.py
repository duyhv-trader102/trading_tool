from typing import List
from markets.base.data_provider import MT5DataProvider
from .config import COMMODITY_SYMBOLS

class CommodityDataProvider(MT5DataProvider):
    def get_all_symbols(self) -> List[str]:
        return COMMODITY_SYMBOLS
