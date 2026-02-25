"""Tests for SignalLogger — uses a temp directory, no MT5 required."""
from __future__ import annotations

import csv as csv_mod
from datetime import date
from pathlib import Path

import pytest

from infra.signal_logger import SignalLogger


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_result(symbol: str, signal: str, m_ready=True, w_ready=True) -> dict:
    """Build a minimal scanner result dict."""
    return {
        "symbol": symbol,
        "signal": signal,
        "monthly": {
            "status": "BALANCE",
            "trend": "bullish",
            "range_low": 1.08,
            "range_high": 1.12,
            "mother_date": "2026-01-01",
            "continuity": 2,
            "is_ready": m_ready,
            "ready_direction": "bullish",
            "ready_reason": "[MBA_BREAK] test",
        },
        "weekly": {
            "status": "IMBALANCE",
            "trend": "bullish",
            "range_low": 1.09,
            "range_high": 1.11,
            "mother_date": "2026-01-10",
            "continuity": 1,
            "is_ready": w_ready,
            "ready_direction": "bullish",
            "ready_reason": "[PULLBACK] test",
        },
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def log_dir(tmp_path) -> Path:
    return tmp_path / "signal_logs"


@pytest.fixture
def logger(log_dir) -> SignalLogger:
    return SignalLogger(log_dir=str(log_dir))


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSignalLoggerBasic:
    def test_dir_created_on_init(self, log_dir):
        # Dir is created lazily on first write, NOT at init time.
        sl = SignalLogger(log_dir=str(log_dir))
        assert not log_dir.exists(), "dir should not exist before any write"
        sl.log_scan_results("FX", [_make_result("EURUSDm", "READY_LONG_BULLISH")])
        assert log_dir.exists(), "dir should exist after first write"

    def test_log_ready_signal(self, logger):
        results = [_make_result("EURUSDm", "READY_LONG_BULLISH")]
        count = logger.log_scan_results("FX", results)
        assert count == 1

    def test_non_ready_signal_not_logged(self, logger):
        results = [_make_result("EURUSDm", "WAIT_LONG")]
        count = logger.log_scan_results("FX", results)
        assert count == 0

    def test_empty_results_returns_zero(self, logger):
        assert logger.log_scan_results("FX", []) == 0

    def test_none_signal_not_logged(self, logger):
        r = _make_result("EURUSDm", "READY_LONG")
        r["signal"] = None
        assert logger.log_scan_results("FX", [r]) == 0


class TestSignalLoggerDedup:
    def test_same_signal_same_day_is_dedup(self, logger):
        results = [_make_result("EURUSDm", "READY_LONG_BULLISH")]
        first  = logger.log_scan_results("FX", results)
        second = logger.log_scan_results("FX", results)
        assert first == 1
        assert second == 0  # same signal → dedup

    def test_changed_signal_overwrites(self, logger):
        logger.log_scan_results("FX", [_make_result("EURUSDm", "READY_LONG_BULLISH")])
        count = logger.log_scan_results("FX", [_make_result("EURUSDm", "READY_SHORT_BEARISH")])
        assert count == 1  # updated

    def test_different_symbols_independent(self, logger):
        results = [
            _make_result("EURUSDm", "READY_LONG_BULLISH"),
            _make_result("GBPUSDm", "READY_LONG_BULLISH"),
        ]
        assert logger.log_scan_results("FX", results) == 2


class TestSignalLoggerQuery:
    def test_get_date_returns_entries(self, logger):
        today = date.today().isoformat()
        logger.log_scan_results("FX", [_make_result("EURUSDm", "READY_LONG_BULLISH")])
        data = logger.get_date(today)
        assert len(data) == 1
        entry = next(iter(data.values()))
        assert entry["symbol"] == "EURUSDm"
        assert entry["market"] == "FX"

    def test_get_ready_signals(self, logger):
        today = date.today().isoformat()
        logger.log_scan_results("FX", [_make_result("EURUSDm", "READY_LONG_BULLISH")])
        ready = logger.get_ready_signals(today)
        assert len(ready) == 1

    def test_list_dates(self, logger):
        logger.log_scan_results("FX", [_make_result("EURUSDm", "READY_LONG_BULLISH")])
        dates = logger.list_dates()
        assert len(dates) >= 1
        assert date.today().isoformat() in dates

    def test_get_symbol_history(self, logger):
        logger.log_scan_results("FX", [_make_result("EURUSDm", "READY_LONG_BULLISH")])
        history = logger.get_symbol_history("EURUSDm")
        assert len(history) >= 1
        assert history[0]["symbol"] == "EURUSDm"

    def test_csv_file_is_valid_csv(self, logger, log_dir):
        logger.log_scan_results("FX", [_make_result("EURUSDm", "READY_LONG_BULLISH")])
        csv_files = list(log_dir.glob("*.csv"))
        assert len(csv_files) == 1
        with open(csv_files[0], encoding="utf-8", newline="") as f:
            rows = list(csv_mod.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["symbol"] == "EURUSDm"
        assert rows[0]["market"] == "FX"
