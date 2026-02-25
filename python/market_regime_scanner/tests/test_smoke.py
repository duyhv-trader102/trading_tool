"""
Smoke tests — verify all key modules import cleanly
and main entry points are callable without errors.
No I/O, no MT5, no network required.
"""
from __future__ import annotations


class TestCoreImports:
    def test_import_data_providers(self):
        from data_providers import get_data, get_provider, UnifiedDataProvider  # noqa: F401

    def test_import_registry(self):
        from markets.registry import MarketRegistry  # noqa: F401

    def test_import_manager(self):
        from markets.manager import MarketManager  # noqa: F401

    def test_import_base_scanner(self):
        from markets.base.scanner import BaseScanner  # noqa: F401

    def test_import_signal_logger(self):
        from infra.signal_logger import SignalLogger  # noqa: F401

    def test_import_daily_scan(self):
        import markets.daily_scan  # noqa: F401

    def test_import_reporting(self):
        from markets.reporting import HTMLReporter  # noqa: F401


class TestMarketProviderImports:
    def test_import_fx_provider(self):
        from markets.fx.data_provider import FXDataProvider  # noqa: F401

    def test_import_comm_provider(self):
        from markets.comm.data_provider import CommodityDataProvider  # noqa: F401

    def test_import_us_stock_provider(self):
        from markets.us_stock.data_provider import USStockDataProvider  # noqa: F401

    def test_import_coin_provider(self):
        from markets.coin.data_provider import CoinDataProvider  # noqa: F401


class TestMarketConfigs:
    def test_fx_config(self):
        from markets.fx.config import FX_SYMBOLS, FX_MAJORS, FX_CROSSES
        assert len(FX_MAJORS) == 7
        assert len(FX_CROSSES) == 20
        assert len(FX_SYMBOLS) == 27

    def test_comm_config(self):
        from markets.comm.config import COMMODITY_SYMBOLS, METALS, ENERGY
        assert len(METALS) >= 4
        assert len(ENERGY) >= 2

    def test_us_stock_config(self):
        from markets.us_stock.config import US_STOCK_SYMBOLS, INDICES, TECH_STOCKS
        assert "US500m" in INDICES
        assert "NVDAm" in TECH_STOCKS
        assert all(sym.endswith("m") for sym in US_STOCK_SYMBOLS)

    def test_coin_config(self):
        from markets.coin.config import COIN_SYMBOLS
        assert "BTCUSDm" in COIN_SYMBOLS
        assert "ETHUSDm" in COIN_SYMBOLS


class TestDailyScanStructure:
    def test_default_markets_list(self):
        from markets.utils.constants import DEFAULT_MARKETS
        assert "FX" in DEFAULT_MARKETS
        assert "COMM" in DEFAULT_MARKETS
        assert "US_STOCK" in DEFAULT_MARKETS

    def test_market_meta_complete(self):
        from markets.utils.constants import DEFAULT_MARKETS, MARKET_META
        for mkt in DEFAULT_MARKETS:
            assert mkt in MARKET_META, f"No MARKET_META entry for {mkt}"
            assert "label" in MARKET_META[mkt]
            assert "color" in MARKET_META[mkt]
