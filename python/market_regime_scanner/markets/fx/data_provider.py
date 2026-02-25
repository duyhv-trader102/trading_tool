from typing import List
from markets.base.data_provider import MT5DataProvider
from .config import FX_SYMBOLS

class FXDataProvider(MT5DataProvider):
    def get_all_symbols(self) -> List[str]:
        return FX_SYMBOLS
