"""
EA — Expert Advisor Framework
==============================

Top-level package for all trading system components.

Structure::

    EA/
    ├── macro_trend_catcher/   Main strategy (config, signals, bot, backtest)
    ├── risk/                  Capital preservation (circuit breaker, sizing)
    ├── shared/                Cross-cutting utilities (indicators, backtest_utils)
    ├── tests/                 Test suite
    ├── data/                  CSV data cache
    └── macro_balance_scalper/ Balance scalper (experimental)
"""
