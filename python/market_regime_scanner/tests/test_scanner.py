"""
Integration tests for BaseScanner — uses real parquet data, no MT5 required.
These tests call analyze_symbol() end-to-end to catch regressions.
"""
from __future__ import annotations

import pytest
from markets.base.scanner import BaseScanner


VALID_SIGNALS = {
    None,
    "READY_LONG_BULLISH", "READY_SHORT_BEARISH",
    "WAIT_LONG", "WAIT_SHORT",
}


@pytest.fixture(scope="module")
def scanner():
    """Create an FX scanner — no provider needed (uses UnifiedDataProvider internally)."""
    return BaseScanner(provider=None, market_name="FX")


class TestBaseScannerAnalysis:
    def test_analyze_returns_dict(self, scanner, parquet_symbol):
        result = scanner.analyze_symbol(parquet_symbol, print_report=False)
        assert result is not None
        assert isinstance(result, dict)

    def test_result_has_required_keys(self, scanner, parquet_symbol):
        result = scanner.analyze_symbol(parquet_symbol, print_report=False)
        assert "symbol" in result
        assert "monthly" in result
        assert "weekly" in result
        assert "signal" in result

    def test_symbol_matches(self, scanner, parquet_symbol):
        result = scanner.analyze_symbol(parquet_symbol, print_report=False)
        assert result["symbol"] == parquet_symbol

    def test_monthly_has_required_fields(self, scanner, parquet_symbol):
        result = scanner.analyze_symbol(parquet_symbol, print_report=False)
        m = result["monthly"]
        for field in ["status", "trend", "is_ready", "ready_direction"]:
            assert field in m, f"Missing field '{field}' in monthly"

    def test_weekly_has_required_fields(self, scanner, parquet_symbol):
        result = scanner.analyze_symbol(parquet_symbol, print_report=False)
        w = result["weekly"]
        for field in ["status", "trend", "is_ready", "ready_direction"]:
            assert field in w, f"Missing field '{field}' in weekly"

    def test_signal_is_valid_type(self, scanner, parquet_symbol):
        result = scanner.analyze_symbol(parquet_symbol, print_report=False)
        sig = result["signal"]
        assert sig is None or isinstance(sig, str), f"signal must be str or None, got {type(sig)}"

    def test_status_is_non_empty_string(self, scanner, parquet_symbol):
        result = scanner.analyze_symbol(parquet_symbol, print_report=False)
        assert isinstance(result["monthly"]["status"], str)
        assert len(result["monthly"]["status"]) > 0

    def test_is_ready_is_bool(self, scanner, parquet_symbol):
        result = scanner.analyze_symbol(parquet_symbol, print_report=False)
        assert isinstance(result["monthly"]["is_ready"], bool)
        assert isinstance(result["weekly"]["is_ready"], bool)

    def test_range_values_when_present(self, scanner, parquet_symbol):
        result = scanner.analyze_symbol(parquet_symbol, print_report=False)
        for tf_key in ("monthly", "weekly"):
            lo = result[tf_key]["range_low"]
            hi = result[tf_key]["range_high"]
            if lo is not None and hi is not None:
                assert lo <= hi, f"{tf_key}: range_low > range_high"
                assert lo > 0, f"{tf_key}: range_low must be positive"

    def test_deterministic_on_same_data(self, scanner, parquet_symbol):
        """Two consecutive calls with the same parquet data must return identical results."""
        r1 = scanner.analyze_symbol(parquet_symbol, print_report=False)
        r2 = scanner.analyze_symbol(parquet_symbol, print_report=False)
        assert r1["signal"] == r2["signal"]
        assert r1["monthly"]["status"] == r2["monthly"]["status"]
        assert r1["weekly"]["status"] == r2["weekly"]["status"]


class TestBaseScannerUnknownSymbol:
    def test_missing_symbol_has_no_ready_signal(self, scanner):
        """Unknown symbol should not produce a READY signal."""
        result = scanner.analyze_symbol("XXXXXm", print_report=False)
        # Scanner may return None OR a "WAITING FOR DATA" dict — either is valid
        if result is None:
            return
        assert isinstance(result, dict)
        sig = result.get("signal") or ""
        assert "READY" not in sig.upper(), (
            f"Unknown symbol produced READY signal: {sig}"
        )

    def test_missing_symbol_not_ready(self, scanner):
        """Monthly and weekly is_ready must both be False for unknown symbol."""
        result = scanner.analyze_symbol("XXXXXm", print_report=False)
        if result is None:
            return  # None is acceptable
        assert not result["monthly"]["is_ready"]
        assert not result["weekly"]["is_ready"]
