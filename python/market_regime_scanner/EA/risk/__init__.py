"""
risk — Capital Preservation
=============================

Risk management components for protecting trading capital.

Modules
-------
circuit_breaker :   Daily/weekly loss limits — auto-halt trading
position_sizer :    Position size calculation based on risk budget
portfolio_guard :   Portfolio-level exposure limits & correlation guard
reconciler :        Position reconciliation between EA state and broker
"""

from EA.risk.circuit_breaker import CircuitBreaker
from EA.risk.position_sizer import PositionSizer
from EA.risk.portfolio_guard import PortfolioGuard
from EA.risk.reconciler import Reconciler

__all__ = [
    "CircuitBreaker",
    "PositionSizer",
    "PortfolioGuard",
    "Reconciler",
]
