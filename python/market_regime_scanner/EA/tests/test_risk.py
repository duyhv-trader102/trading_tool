"""Tests for EA.risk package."""

from EA.risk.circuit_breaker import CircuitBreaker
from EA.risk.position_sizer import PositionSizer
from EA.risk.portfolio_guard import PortfolioGuard, Position
from EA.risk.reconciler import Reconciler, PositionRecord, DiffType


class TestCircuitBreaker:
    """Test CircuitBreaker thresholds."""

    def test_normal_trading_allowed(self):
        cb = CircuitBreaker(daily_limit_pct=4.0)
        assert cb.can_trade(10_000, daily_pnl_pct=-1.0, weekly_pnl_pct=-2.0)
        assert cb.halt_reason is None

    def test_daily_limit_halt(self):
        cb = CircuitBreaker(daily_limit_pct=4.0)
        assert not cb.can_trade(10_000, daily_pnl_pct=-4.5, weekly_pnl_pct=-4.5)
        assert "Daily" in cb.halt_reason

    def test_weekly_limit_halt(self):
        cb = CircuitBreaker(weekly_limit_pct=8.0)
        assert not cb.can_trade(10_000, daily_pnl_pct=-1.0, weekly_pnl_pct=-9.0)
        assert "Weekly" in cb.halt_reason

    def test_trailing_drawdown_halt(self):
        cb = CircuitBreaker(trailing_dd_pct=10.0)
        cb.update_equity_peak(10_000)
        assert not cb.can_trade(8_900, daily_pnl_pct=0, weekly_pnl_pct=0)
        assert "Trailing DD" in cb.halt_reason

    def test_reset(self):
        cb = CircuitBreaker()
        cb.can_trade(10_000, daily_pnl_pct=-5.0, weekly_pnl_pct=0)
        cb.reset()
        assert cb.halt_reason is None
        assert not cb.is_halted


class TestPositionSizer:
    """Test position sizing calculations."""

    def test_basic_sizing(self):
        sizer = PositionSizer(risk_pct=1.0)
        lots = sizer.calculate(equity=10_000, stop_distance=50, pip_value=10)
        # risk = 100, lots = 100 / (50 * 10) = 0.2
        assert abs(lots - 0.2) < 0.01

    def test_zero_stop(self):
        sizer = PositionSizer()
        assert sizer.calculate(equity=10_000, stop_distance=0) == 0.0

    def test_prop_mode_caps_risk(self):
        sizer = PositionSizer(risk_pct=2.0, prop_mode=True, max_risk_pct_prop=0.5)
        lots_normal = PositionSizer(risk_pct=2.0).calculate(10_000, 50, 10)
        lots_prop = sizer.calculate(10_000, 50, 10)
        assert lots_prop < lots_normal

    def test_max_lot_cap(self):
        sizer = PositionSizer(risk_pct=50.0, max_lot=1.0)
        lots = sizer.calculate(equity=100_000, stop_distance=1, pip_value=1)
        assert lots <= 1.0


class TestPortfolioGuard:
    """Test portfolio-level constraints."""

    def test_max_positions(self):
        guard = PortfolioGuard(max_positions=2)
        positions = [
            Position("BTC", "crypto", 1000, "LONG"),
            Position("ETH", "crypto", 1000, "LONG"),
        ]
        assert not guard.can_add_position("SOL", "crypto", 500, 10_000, positions)
        assert "Max positions" in guard.rejection_reason

    def test_duplicate_symbol(self):
        guard = PortfolioGuard(max_positions=5)
        positions = [Position("BTC", "crypto", 1000, "LONG")]
        assert not guard.can_add_position("BTC", "crypto", 500, 10_000, positions)

    def test_allows_valid_position(self):
        guard = PortfolioGuard(max_positions=5, max_correlated=3)
        positions = [Position("BTC", "crypto", 1000, "LONG")]
        assert guard.can_add_position("ETH", "crypto", 500, 10_000, positions)


class TestReconciler:
    """Test position reconciliation."""

    def test_no_diffs(self):
        recon = Reconciler()
        ea = [PositionRecord("BTC", "LONG", 1.0, 50000)]
        broker = [PositionRecord("BTC", "LONG", 1.0, 50000)]
        assert len(recon.compare(ea, broker)) == 0

    def test_phantom_detected(self):
        recon = Reconciler()
        ea = [PositionRecord("BTC", "LONG", 1.0, 50000)]
        broker = []
        diffs = recon.compare(ea, broker)
        assert len(diffs) == 1
        assert diffs[0].diff_type == DiffType.PHANTOM

    def test_orphan_detected(self):
        recon = Reconciler()
        ea = []
        broker = [PositionRecord("BTC", "LONG", 1.0, 50000)]
        diffs = recon.compare(ea, broker)
        assert len(diffs) == 1
        assert diffs[0].diff_type == DiffType.ORPHAN

    def test_size_mismatch(self):
        recon = Reconciler(size_tolerance=0.01)
        ea = [PositionRecord("BTC", "LONG", 1.0, 50000)]
        broker = [PositionRecord("BTC", "LONG", 0.5, 50000)]
        diffs = recon.compare(ea, broker)
        assert any(d.diff_type == DiffType.SIZE_MISMATCH for d in diffs)
