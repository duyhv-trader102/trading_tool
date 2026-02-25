"""
Backtest Utilities
==================
Common helper functions for backtesting strategies.
"""

import statistics
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Trade:
    """Represents a single trade."""
    entry_time: datetime
    exit_time: datetime
    direction: str  # "bullish" or "bearish"
    entry_price: float
    exit_price: float
    entry_type: str = ""
    exit_reason: str = ""
    stop_loss: float = 0.0
    take_profit: float = 0.0
    max_drawdown: float = 0.0
    max_favorable: float = 0.0
    
    @property
    def return_pct(self) -> float:
        """Calculate return percentage."""
        if self.direction == "bullish":
            return (self.exit_price - self.entry_price) / self.entry_price * 100
        else:
            return (self.entry_price - self.exit_price) / self.entry_price * 100
    
    @property
    def profit_points(self) -> float:
        """Calculate profit in points."""
        if self.direction == "bullish":
            return self.exit_price - self.entry_price
        else:
            return self.entry_price - self.exit_price
    
    @property
    def duration_days(self) -> int:
        """Calculate trade duration in days."""
        return (self.exit_time - self.entry_time).days
    
    @property
    def is_win(self) -> bool:
        """Check if trade is profitable."""
        return self.return_pct > 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "entry_type": self.entry_type,
            "exit_reason": self.exit_reason,
            "return_pct": round(self.return_pct, 4),
            "profit_points": round(self.profit_points, 4),
            "duration_days": self.duration_days,
            "max_drawdown": round(self.max_drawdown, 4),
            "max_favorable": round(self.max_favorable, 4),
        }


@dataclass
class BacktestMetrics:
    """Performance metrics for a backtest."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    avg_duration_days: float = 0.0
    profit_factor: float = 0.0
    
    # Breakdown stats
    exit_breakdown: Dict[str, int] = field(default_factory=dict)
    entry_breakdown: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 4),
            "avg_return": round(self.avg_return, 4),
            "total_return": round(self.total_return, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "avg_duration_days": round(self.avg_duration_days, 2),
            "profit_factor": round(self.profit_factor, 4),
            "exit_breakdown": self.exit_breakdown,
            "entry_breakdown": self.entry_breakdown,
        }


def calculate_metrics(trades: List[Trade], annual_periods: int = 252) -> BacktestMetrics:
    """
    Calculate comprehensive backtest metrics from trade list.
    
    Args:
        trades: List of Trade objects
        annual_periods: Number of periods per year for Sharpe calculation
    
    Returns:
        BacktestMetrics with all performance stats
    """
    if not trades:
        return BacktestMetrics()
    
    returns = [t.return_pct for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    
    total_trades = len(trades)
    win_count = len(wins)
    loss_count = len(losses)
    
    metrics = BacktestMetrics(
        total_trades=total_trades,
        wins=win_count,
        losses=loss_count,
        win_rate=win_count / total_trades if total_trades > 0 else 0,
        avg_return=sum(returns) / total_trades if total_trades > 0 else 0,
        total_return=sum(returns),
        avg_duration_days=sum(t.duration_days for t in trades) / total_trades if total_trades > 0 else 0,
    )
    
    # Max drawdown (running max)
    equity = 100
    peak = equity
    max_dd = 0
    for r in returns:
        equity *= (1 + r / 100)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)
    metrics.max_drawdown = max_dd
    
    # Sharpe ratio
    if len(returns) > 1:
        std_return = statistics.stdev(returns)
        trades_per_year = min(total_trades / 2, annual_periods)  # Assume 2 years data
        if std_return > 0:
            metrics.sharpe_ratio = (metrics.avg_return / std_return) * (trades_per_year ** 0.5)
    
    # Profit factor
    total_wins = sum(wins) if wins else 0
    total_losses = abs(sum(losses)) if losses else 0.001
    metrics.profit_factor = total_wins / total_losses
    
    # Breakdowns
    for t in trades:
        # Exit breakdown
        reason = t.exit_reason or "unknown"
        metrics.exit_breakdown[reason] = metrics.exit_breakdown.get(reason, 0) + 1
        
        # Entry breakdown
        entry = t.entry_type or "unknown"
        metrics.entry_breakdown[entry] = metrics.entry_breakdown.get(entry, 0) + 1
    
    return metrics


def print_metrics(metrics: BacktestMetrics, symbol: str = "", version: str = "V1"):
    """Pretty print backtest metrics."""
    print(f"\n{'='*60}")
    print(f"BACKTEST RESULTS - {symbol} ({version})")
    print(f"{'='*60}")
    
    print(f"\n📊 PERFORMANCE METRICS:")
    print(f"  Total Trades:    {metrics.total_trades}")
    print(f"  Win Rate:        {metrics.win_rate*100:.1f}%")
    print(f"  Avg Return:      {metrics.avg_return:.2f}%")
    print(f"  Total Return:    {metrics.total_return:.2f}%")
    print(f"  Max Drawdown:    {metrics.max_drawdown:.2f}%")
    print(f"  Sharpe Ratio:    {metrics.sharpe_ratio:.2f}")
    print(f"  Profit Factor:   {metrics.profit_factor:.2f}")
    print(f"  Avg Duration:    {metrics.avg_duration_days:.1f} days")
    
    if metrics.exit_breakdown:
        print(f"\n📤 EXIT BREAKDOWN:")
        for reason, count in sorted(metrics.exit_breakdown.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")
    
    if metrics.entry_breakdown:
        print(f"\n📥 ENTRY BREAKDOWN:")
        for entry, count in sorted(metrics.entry_breakdown.items(), key=lambda x: -x[1]):
            print(f"  {entry}: {count}")


def calculate_equity_curve(trades: List[Trade], initial_equity: float = 100) -> List[Dict]:
    """
    Calculate equity curve from trades.
    
    Args:
        trades: List of Trade objects
        initial_equity: Starting equity (default 100)
    
    Returns:
        List of {date, equity} points
    """
    curve = [{"date": None, "equity": initial_equity}]
    equity = initial_equity
    
    for t in trades:
        equity *= (1 + t.return_pct / 100)
        curve.append({
            "date": t.exit_time.isoformat() if t.exit_time else None,
            "equity": round(equity, 2)
        })
    
    return curve


def calculate_monthly_returns(trades: List[Trade]) -> Dict[str, float]:
    """
    Calculate returns aggregated by month.
    
    Args:
        trades: List of Trade objects
    
    Returns:
        Dict of {YYYY-MM: return_pct}
    """
    monthly = {}
    
    for t in trades:
        if t.exit_time:
            key = t.exit_time.strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0) + t.return_pct
    
    return monthly
