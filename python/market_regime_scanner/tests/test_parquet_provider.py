"""Tests for ParquetDataProvider — reads real parquet files, no MT5 required."""
from __future__ import annotations

import polars as pl
import pytest

from data_providers.parquet_data_provider import ParquetDataProvider, get_path


EXPECTED_COLUMNS = {"time", "open", "high", "low", "close"}


class TestParquetDataProvider:
    def test_get_data_returns_dataframe(self, parquet_symbol, data_dir):
        provider = ParquetDataProvider()
        df = provider.get_data(parquet_symbol, "H4")
        assert df is not None
        assert isinstance(df, pl.DataFrame)
        assert not df.is_empty()

    def test_get_data_has_required_columns(self, parquet_symbol):
        provider = ParquetDataProvider()
        df = provider.get_data(parquet_symbol, "H4")
        missing = EXPECTED_COLUMNS - set(df.columns)
        assert not missing, f"Missing columns: {missing}"

    def test_get_data_d1_available(self, parquet_symbol):
        provider = ParquetDataProvider()
        df = provider.get_data(parquet_symbol, "D1")
        assert df is not None and not df.is_empty()

    def test_get_data_w1_available(self, parquet_symbol):
        provider = ParquetDataProvider()
        df = provider.get_data(parquet_symbol, "W1")
        assert df is not None and not df.is_empty()

    def test_bars_limit_respected(self, parquet_symbol):
        provider = ParquetDataProvider()
        df = provider.get_data(parquet_symbol, "H4", bars=100)
        assert len(df) <= 100

    def test_unknown_symbol_returns_none(self):
        provider = ParquetDataProvider()
        df = provider.get_data("XXXXXm", "H4")
        assert df is None

    def test_get_path_returns_path(self, parquet_symbol):
        path = get_path(parquet_symbol, "H4")
        assert path is not None
        assert path.suffix == ".parquet"

    def test_time_column_is_sorted_ascending(self, parquet_symbol):
        provider = ParquetDataProvider()
        df = provider.get_data(parquet_symbol, "H4")
        times = df["time"].to_list()
        assert times == sorted(times), "Time column should be sorted ascending"

    def test_no_null_ohlc(self, parquet_symbol):
        provider = ParquetDataProvider()
        df = provider.get_data(parquet_symbol, "H4")
        for col in ["open", "high", "low", "close"]:
            nulls = df[col].null_count()
            assert nulls == 0, f"Column '{col}' has {nulls} nulls"

    def test_ohlc_valid_ranges(self, parquet_symbol):
        provider = ParquetDataProvider()
        df = provider.get_data(parquet_symbol, "H4")
        # High >= Low always
        violations = df.filter(pl.col("high") < pl.col("low"))
        assert len(violations) == 0, f"{len(violations)} bars where high < low"
        # Positive prices
        assert df["close"].min() > 0
