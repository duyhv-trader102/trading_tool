"""Shared test fixtures for EA tests."""

import pytest
import sys
from pathlib import Path

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


@pytest.fixture
def sample_equity():
    """Sample starting equity for risk tests."""
    return 10_000.0


@pytest.fixture
def sample_positions():
    """Sample portfolio positions for guard tests."""
    from EA.risk.portfolio_guard import Position

    return [
        Position(symbol="BTCUSDT", sector="crypto", notional=2000, direction="LONG"),
        Position(symbol="ETHUSDT", sector="crypto", notional=1500, direction="LONG"),
    ]
