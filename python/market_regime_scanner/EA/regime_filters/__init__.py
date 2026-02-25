"""
EA.regime_filters — Market Regime Filters for EA Trading Decisions
===================================================================

A pluggable system of regime filters that gate trade entries.
Each filter answers one question: **should we trade right now?**

Architecture
------------
::

    BaseRegimeFilter (ABC)
      ├── BtcRegimeFilter        — BTC Monthly MBA direction
      ├── BroadMarketFilter      — % of coins bearish (aggregate)
      └── (future filters...)

    RegimeGate
      └── Chains multiple filters → single allow/block decision

Usage
-----
::

    from EA.regime_filters import RegimeGate, BtcRegimeFilter, BroadMarketFilter

    # Build gate with desired filters
    gate = RegimeGate([
        BtcRegimeFilter(),
        BroadMarketFilter(bear_threshold=0.70),
    ])

    # Pre-compute lookups (once, before backtest loop)
    gate.build()

    # Check on a given date
    verdict = gate.check("2025-06-15", direction="bullish", symbol="ETH/USDT")
    if verdict.blocked:
        print(f"Trade blocked: {verdict.reason}")

Adding a New Filter
-------------------
1. Create ``EA/regime_filters/my_filter.py``
2. Subclass ``BaseRegimeFilter``
3. Implement ``build()`` and ``check()``
4. Register in ``RegimeGate`` instantiation
"""

from EA.regime_filters.base import BaseRegimeFilter, RegimeVerdict, RegimeGate
from EA.regime_filters.btc_regime import BtcRegimeFilter
from EA.regime_filters.broad_market import BroadMarketFilter

__all__ = [
    "BaseRegimeFilter",
    "RegimeVerdict",
    "RegimeGate",
    "BtcRegimeFilter",
    "BroadMarketFilter",
]
