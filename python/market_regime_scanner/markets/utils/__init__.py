"""
markets.utils — Shared constants, formatters and HTML helpers.

Centralises definitions that were previously duplicated across
``daily_scan.py``, ``pnl_tracker.py``, ``sync.py`` and ``reporting.py``.
"""

from markets.utils.constants import (        # noqa: F401
    MT5_MARKETS,
    WEEKEND_MARKETS,
    MARKET_ORDER,
    DEFAULT_MARKETS,
    MARKET_META,
)
from markets.utils.formatters import (       # noqa: F401
    fmt_price,
    fmt_pct,
    fmt_range,
    compact_regime,
    sorted_markets,
)
from markets.utils.html_helpers import (     # noqa: F401
    sig_cls,
    sig_key,
    SIGNAL_PRIORITY,
    change_cell,
    range_bar_html,
    trend_badge_cls,
    build_trade_history_html,
    dashboard_css,
    dashboard_js,
)
