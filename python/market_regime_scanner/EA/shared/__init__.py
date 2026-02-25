"""
EA Shared Utilities
==================
Common modules used across different EA strategies.

Modules:
- indicators: ATR, ADX, RSI, EMA, Bollinger Bands
- backtest_utils: Trade, BacktestMetrics, calculate_metrics
- market_filter: Tiered symbol scoring (FilterConfig, score_symbols)
"""

from EA.shared.indicators import (
    calculate_atr,
    calculate_adx,
    calculate_rsi,
    calculate_ema,
    calculate_sma,
    calculate_bollinger_bands,
)

from EA.shared.backtest_utils import (
    Trade,
    BacktestMetrics,
    calculate_metrics,
    print_metrics,
    calculate_equity_curve,
    calculate_monthly_returns,
)

from EA.shared.market_filter import (
    FilterConfig,
    ScoredSymbol,
    score_symbols,
    print_report,
    export_watchlist,
)

__all__ = [
    # Indicators
    "calculate_atr",
    "calculate_adx",
    "calculate_rsi",
    "calculate_ema",
    "calculate_sma",
    "calculate_bollinger_bands",
    # Backtest utils
    "Trade",
    "BacktestMetrics",
    "calculate_metrics",
    "print_metrics",
    "calculate_equity_curve",
    "calculate_monthly_returns",
    # Market filter
    "FilterConfig",
    "ScoredSymbol",
    "score_symbols",
    "print_report",
    "export_watchlist",
]
