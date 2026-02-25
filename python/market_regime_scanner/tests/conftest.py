"""Shared fixtures for the test suite."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path regardless of how pytest is invoked
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "mt5"

# ── Symbols that have full H4+D1+W1 parquet data ──────────────────────────
# Used for scanner integration tests (no MT5 connection required)
WELL_COVERED_SYMBOL = "EURUSDm"


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA_DIR


@pytest.fixture(scope="session")
def parquet_symbol() -> str:
    """A symbol that has H4, D1, and W1 parquet files."""
    return WELL_COVERED_SYMBOL


@pytest.fixture(scope="session")
def sample_h4_df(parquet_symbol):
    """Load the H4 parquet for the test symbol (parquet-only, no MT5)."""
    import polars as pl
    path = DATA_DIR / f"{parquet_symbol}_H4.parquet"
    from infra.s3_storage import smart_read_parquet
    df = smart_read_parquet(path)
    if df is None:
        pytest.skip(f"Missing parquet: {path}")
    return df
