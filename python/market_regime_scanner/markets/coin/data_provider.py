from typing import List
from markets.base.data_provider import MT5DataProvider
from .config import COIN_SYMBOLS

class CoinDataProvider(MT5DataProvider):
    def get_all_symbols(self) -> List[str]:
        return COIN_SYMBOLS
