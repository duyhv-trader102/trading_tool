"""Tests for MarketRegistry — no I/O, no MT5 required."""
from __future__ import annotations

import pytest
from markets.registry import MarketRegistry


EXPECTED_MARKETS = {"FX", "COMM", "US_STOCK", "COIN", "BINANCE", "VNSTOCK"}


class TestMarketRegistryStructure:
    def test_list_markets_returns_expected_set(self):
        markets = set(MarketRegistry.list_markets())
        assert EXPECTED_MARKETS.issubset(markets), (
            f"Missing markets: {EXPECTED_MARKETS - markets}"
        )

    def test_get_provider_returns_instance(self):
        for market in ["FX", "COMM", "US_STOCK", "COIN"]:
            provider = MarketRegistry.get_provider(market)
            assert provider is not None, f"No provider for {market}"

    def test_get_provider_raises_on_unknown(self):
        with pytest.raises(ValueError, match="Unknown market"):
            MarketRegistry.get_provider("NOTAMARKET")


class TestMarketSymbolLists:
    def test_fx_symbols_non_empty(self):
        symbols = MarketRegistry.get_symbols("FX")
        assert len(symbols) >= 27, f"Expected ≥27 FX symbols, got {len(symbols)}"

    def test_fx_symbols_format(self):
        symbols = MarketRegistry.get_symbols("FX")
        for sym in symbols:
            assert sym.endswith("m"), f"FX symbol has wrong suffix: {sym}"

    def test_comm_symbols_non_empty(self):
        symbols = MarketRegistry.get_symbols("COMM")
        assert len(symbols) >= 6, f"Expected ≥6 COMM symbols, got {len(symbols)}"
        assert "XAUUSDm" in symbols, "XAUUSDm must be in COMM symbols"
        assert "USOILm" in symbols, "USOILm must be in COMM symbols"

    def test_us_stock_symbols_non_empty(self):
        symbols = MarketRegistry.get_symbols("US_STOCK")
        assert len(symbols) >= 10
        assert "NVDAm" in symbols
        assert "US500m" in symbols

    def test_coin_symbols_non_empty(self):
        symbols = MarketRegistry.get_symbols("COIN")
        assert len(symbols) >= 10
        assert "BTCUSDm" in symbols

    def test_no_duplicates_within_market(self):
        for market in ["FX", "COMM", "US_STOCK", "COIN"]:
            symbols = MarketRegistry.get_symbols(market)
            assert len(symbols) == len(set(symbols)), (
                f"{market} has duplicate symbols: "
                f"{[s for s in symbols if symbols.count(s) > 1]}"
            )

    def test_no_invalid_ma_symbol(self):
        """MAsm was a known invalid symbol — ensure it's removed."""
        symbols = MarketRegistry.get_symbols("US_STOCK")
        assert "MAsm" not in symbols, "Invalid symbol MAsm should have been removed"
