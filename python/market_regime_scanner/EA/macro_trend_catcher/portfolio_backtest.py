"""
Portfolio Backtest V2.1 — High-Fidelity Equity Simulation
==========================================================

Truth Level: 8/10

Takes the per-symbol trade log from backtest_v21_detailed.py and runs a
realistic portfolio simulation with:

1. Fixed fractional risk per trade (1% equity -> position_size = risk / SL_distance)
2. Cost model: commission + slippage (configurable)
3. Chronological portfolio merge: trades ordered by entry date across ALL symbols
4. Concurrent positions: real equity allocation, skip if insufficient capital
5. Correlation/sector cap: max N positions in same sector
6. Circuit breaker: daily/weekly loss limits, trailing drawdown halt
7. Monte Carlo: shuffle trade order (1000 runs) for statistical confidence
8. Prop firm metrics dashboard (FTMO/MFF standard)

Input:
    reports/v21_trade_log.csv  (from backtest_v21_detailed.py)

Output:
    reports/portfolio_v21_report.txt        — full report
    reports/portfolio_v21_equity.csv        — daily equity curve
    reports/portfolio_v21_monte_carlo.csv   — MC distribution
    reports/portfolio_v21_trades.csv        — enriched trade log with sizing

Usage::

    cd D:\\code\\trading_tool\\python\\market_regime_scanner
    python -m EA.macro_trend_catcher.portfolio_backtest
    python -m EA.macro_trend_catcher.portfolio_backtest --capital 100000 --risk-pct 1.0
    python -m EA.macro_trend_catcher.portfolio_backtest --prop-mode
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
import statistics
import sys
import time
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")


# =====================================================================
# Crypto Sector Classification
# =====================================================================

SECTOR_MAP: Dict[str, str] = {
    # Layer 1
    "BTC": "L1", "ETH": "L1", "SOL": "L1", "ADA": "L1", "AVAX": "L1",
    "DOT": "L1", "ATOM": "L1", "NEAR": "L1", "SUI": "L1", "APT": "L1",
    "FTM": "L1", "ALGO": "L1", "EGLD": "L1", "HBAR": "L1", "ICP": "L1",
    "TIA": "L1", "XTZ": "L1", "FIL": "L1", "EOS": "L1", "XLM": "L1",
    "XRP": "L1", "TRX": "L1", "TON": "L1", "SEI": "L1", "INJ": "L1",
    "KAS": "L1", "ROSE": "L1", "ONE": "L1", "ZIL": "L1", "KAVA": "L1",
    "CELO": "L1", "THETA": "L1", "VET": "L1", "IOTA": "L1", "NEO": "L1",
    "WAVES": "L1", "QTUM": "L1", "ICX": "L1", "ZEN": "L1", "STRAX": "L1",

    # Layer 2 / Scaling
    "MATIC": "L2", "ARB": "L2", "OP": "L2", "IMX": "L2", "METIS": "L2",
    "MANTA": "L2", "LRC": "L2", "CELR": "L2", "BOBA": "L2", "SKL": "L2",
    "STX": "L2", "STRK": "L2",

    # DeFi
    "UNI": "DEFI", "AAVE": "DEFI", "MKR": "DEFI", "SNX": "DEFI",
    "COMP": "DEFI", "CRV": "DEFI", "SUSHI": "DEFI", "YFI": "DEFI",
    "1INCH": "DEFI", "DYDX": "DEFI", "BAL": "DEFI", "CAKE": "DEFI",
    "JOE": "DEFI", "LQTY": "DEFI", "PENDLE": "DEFI", "RUNE": "DEFI",
    "PERP": "DEFI", "ALPHA": "DEFI", "ANKR": "DEFI", "BNT": "DEFI",
    "RSR": "DEFI", "KNC": "DEFI", "REN": "DEFI", "BAND": "DEFI",
    "GRT": "DEFI", "API3": "DEFI", "PYTH": "DEFI", "TLM": "DEFI",
    "POND": "DEFI",

    # AI / Data
    "FET": "AI", "AGIX": "AI", "OCEAN": "AI", "RNDR": "AI", "TAO": "AI",
    "WLD": "AI", "ARKM": "AI", "AI": "AI", "NMR": "AI", "CTXC": "AI",
    "PHB": "AI",

    # Gaming / Metaverse
    "AXS": "GAMING", "SAND": "GAMING", "MANA": "GAMING", "GALA": "GAMING",
    "ENJ": "GAMING", "ILV": "GAMING", "ALICE": "GAMING", "YGG": "GAMING",
    "PIXEL": "GAMING", "PORTAL": "GAMING", "MAGIC": "GAMING", "GMT": "GAMING",
    "LOKA": "GAMING", "PYR": "GAMING", "WAXP": "GAMING", "VOXEL": "GAMING",
    "GHST": "GAMING", "SUPER": "GAMING", "BICO": "GAMING",

    # Meme
    "DOGE": "MEME", "SHIB": "MEME", "PEPE": "MEME", "FLOKI": "MEME",
    "WIF": "MEME", "BONK": "MEME", "NEIRO": "MEME", "PEOPLE": "MEME",
    "LUNC": "MEME", "1000SATS": "MEME", "BOME": "MEME",

    # Infrastructure / Oracle
    "LINK": "INFRA", "QNT": "INFRA", "AR": "INFRA", "AKT": "INFRA",
    "STORJ": "INFRA", "SC": "INFRA", "GNO": "INFRA", "FLUX": "INFRA",
    "RLC": "INFRA",

    # Exchange / CeFi
    "BNB": "CEFI", "CRO": "CEFI", "OKB": "CEFI", "LEO": "CEFI",
    "FTT": "CEFI", "HT": "CEFI", "GT": "CEFI",

    # Privacy
    "XMR": "PRIVACY", "ZEC": "PRIVACY", "DASH": "PRIVACY", "SCRT": "PRIVACY",

    # Staking / Liquid Staking
    "LDO": "LST", "RPL": "LST", "FXS": "LST", "SSV": "LST",
    "ETHFI": "LST",

    # Social / Identity
    "ENS": "SOCIAL", "CYBER": "SOCIAL", "ID": "SOCIAL", "GAL": "SOCIAL",
    "HOOK": "SOCIAL",

    # NFT / Creator
    "BLUR": "NFT", "APE": "NFT", "RARE": "NFT", "LOOKS": "NFT",

    # IoT / DePIN
    "HNT": "DEPIN", "IOTX": "DEPIN", "MOBILE": "DEPIN",

    # Cross-chain / Bridge
    "WORM": "BRIDGE", "AXL": "BRIDGE", "STG": "BRIDGE",
    "ZRO": "BRIDGE",
}

DEFAULT_SECTOR = "OTHER"


def get_sector(symbol: str) -> str:
    """Map a symbol to its crypto sector."""
    sym = symbol.upper().replace("USDT", "").replace("/", "")
    return SECTOR_MAP.get(sym, DEFAULT_SECTOR)


# =====================================================================
# Configuration
# =====================================================================

@dataclass
class PortfolioConfig:
    """Portfolio backtest configuration."""
    # Capital
    initial_capital: float = 100_000.0

    # Position sizing
    risk_per_trade_pct: float = 1.0       # Risk 1% equity per trade
    max_position_pct: float = 20.0        # Max 20% equity in single position

    # Cost model
    commission_per_side: float = 0.001    # 0.1% per side (Binance standard)
    slippage_pct: float = 0.05            # 0.05% market impact per side

    # Portfolio constraints
    max_concurrent_positions: int = 10
    max_per_sector: int = 3               # Correlation cap
    max_total_exposure_pct: float = 100.0  # No leverage (spot)

    # Circuit breaker
    daily_loss_limit_pct: float = 3.0     # Halt if daily loss > 3%
    weekly_loss_limit_pct: float = 6.0    # Halt if weekly loss > 6%
    trailing_dd_halt_pct: float = 50.0    # Personal: very relaxed (effectively off)

    # Prop firm mode
    prop_mode: bool = False
    prop_max_dd_pct: float = 10.0         # FTMO max DD = 10%
    prop_daily_dd_pct: float = 5.0        # FTMO daily DD = 5%

    # Monte Carlo
    mc_runs: int = 1000
    mc_seed: int = 42

    @property
    def total_cost_per_side(self) -> float:
        return self.commission_per_side + self.slippage_pct / 100


# =====================================================================
# Data Structures
# =====================================================================

@dataclass
class PortfolioTrade:
    """A single trade with portfolio-level sizing context."""
    # From original trade log
    symbol: str
    entry_date: str       # YYYY-MM-DD
    exit_date: str        # YYYY-MM-DD
    entry_price: float
    exit_price: float
    stop_loss: float
    sl_distance_pct: float
    gross_return_pct: float
    exit_reason: str
    duration_days: int
    sector: str

    # Portfolio sizing
    equity_at_entry: float = 0.0
    position_size_usd: float = 0.0
    risk_amount_usd: float = 0.0
    shares: float = 0.0

    # PnL
    gross_pnl_usd: float = 0.0
    commission_usd: float = 0.0
    slippage_usd: float = 0.0
    net_pnl_usd: float = 0.0
    net_return_pct: float = 0.0

    # State
    equity_after: float = 0.0
    concurrent_positions: int = 0
    was_skipped: bool = False
    skip_reason: str = ""


@dataclass
class EquityPoint:
    """Daily equity tracking point."""
    date: str
    equity: float
    drawdown_pct: float
    open_positions: int
    daily_pnl_pct: float


@dataclass
class MCResult:
    """Monte Carlo single run result."""
    run_id: int
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    win_rate_pct: float
    total_trades: int
    calmar_ratio: float


# =====================================================================
# Trade Loader
# =====================================================================

def load_trade_log(csv_path: str) -> List[Dict[str, Any]]:
    """Load trades from V2.1 trade log CSV."""
    trades = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append({
                "symbol": row["symbol"],
                "entry_date": row["entry_time"],
                "exit_date": row["exit_time"],
                "entry_price": float(row["entry_price"]),
                "exit_price": float(row["exit_price"]),
                "stop_loss": float(row["stop_loss"]),
                "sl_distance_pct": float(row["sl_distance_pct"]),
                "gross_return_pct": float(row["gross_return_pct"]),
                "exit_reason": row["exit_reason"],
                "duration_days": int(row["duration_days"]),
            })

    # Sort chronologically by entry date
    trades.sort(key=lambda t: t["entry_date"])
    return trades


# =====================================================================
# Portfolio Simulation Engine
# =====================================================================

class PortfolioSimulator:
    """
    High-fidelity portfolio backtest engine.

    Processes trades in chronological order, managing:
    - Equity-based position sizing
    - Concurrent position tracking
    - Sector concentration limits
    - Circuit breaker halts
    - Realistic cost model
    """

    def __init__(self, config: PortfolioConfig):
        self.cfg = config

    def run(
        self,
        raw_trades: List[Dict[str, Any]],
        shuffle: bool = False,
    ) -> Tuple[List[PortfolioTrade], List[EquityPoint]]:
        """
        Run portfolio simulation on trade list.

        Parameters
        ----------
        raw_trades : list
            Raw trade dicts sorted by entry_date.
        shuffle : bool
            If True, shuffle trade order (for Monte Carlo).

        Returns
        -------
        (portfolio_trades, equity_curve)
        """
        trades = [dict(t) for t in raw_trades]
        if shuffle:
            random.shuffle(trades)

        equity = self.cfg.initial_capital
        peak_equity = equity
        portfolio_trades: List[PortfolioTrade] = []
        equity_curve: List[EquityPoint] = []

        # Track open positions (concurrent)
        open_positions: List[Dict] = []

        # Daily/weekly PnL tracking
        daily_pnl = 0.0
        weekly_pnl = 0.0
        current_day = ""
        current_week = ""
        halted = False
        halt_reason = ""

        # Sector tracking
        sector_count: Dict[str, int] = {}

        for trade_data in trades:
            entry_date = trade_data["entry_date"]
            exit_date = trade_data["exit_date"]
            symbol = trade_data["symbol"]
            sector = get_sector(symbol)

            # -- Close expired positions before new entry --
            still_open = []
            for pos in open_positions:
                if pos["exit_date"] <= entry_date:
                    # Position closed
                    pnl = pos["net_pnl_usd"]
                    equity += pnl
                    daily_pnl += pnl / max(equity, 1) * 100
                    weekly_pnl += pnl / max(equity, 1) * 100
                    peak_equity = max(peak_equity, equity)
                    # Release sector slot
                    sec = pos["sector"]
                    sector_count[sec] = max(0, sector_count.get(sec, 0) - 1)
                else:
                    still_open.append(pos)
            open_positions = still_open

            # -- Reset daily/weekly PnL on date change --
            if entry_date != current_day:
                daily_pnl = 0.0
                current_day = entry_date
                # Reset daily halt each new day
                if halted and halt_reason.startswith("daily_loss"):
                    halted = False
                    halt_reason = ""

            # Proper ISO week tracking for weekly reset
            try:
                entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
                week_str = f"{entry_dt.isocalendar()[0]}-W{entry_dt.isocalendar()[1]:02d}"
            except Exception:
                week_str = entry_date[:7]
            if week_str != current_week:
                weekly_pnl = 0.0
                current_week = week_str
                # Reset weekly halt each new week
                if halted and halt_reason.startswith("weekly_loss"):
                    halted = False
                    halt_reason = ""

            # -- Circuit breaker check --
            # Recalculate DD from peak each time (not sticky)
            dd_from_peak = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
            halt_dd = self.cfg.prop_max_dd_pct if self.cfg.prop_mode else self.cfg.trailing_dd_halt_pct
            halt_daily = self.cfg.prop_daily_dd_pct if self.cfg.prop_mode else self.cfg.daily_loss_limit_pct

            if self.cfg.prop_mode:
                # Prop firm: trailing DD halt is PERMANENT (account blown)
                if dd_from_peak >= halt_dd:
                    if not halted:
                        halted = True
                        halt_reason = f"trailing_dd_{dd_from_peak:.1f}%"
                elif daily_pnl <= -halt_daily and not halted:
                    halted = True
                    halt_reason = f"daily_loss_{daily_pnl:.1f}%"
                elif weekly_pnl <= -self.cfg.weekly_loss_limit_pct and not halted:
                    halted = True
                    halt_reason = f"weekly_loss_{weekly_pnl:.1f}%"
            else:
                # Standard mode: halts are transient, re-evaluate each trade
                halted = False
                halt_reason = ""
                if dd_from_peak >= halt_dd:
                    halted = True
                    halt_reason = f"trailing_dd_{dd_from_peak:.1f}%"
                elif daily_pnl <= -halt_daily:
                    halted = True
                    halt_reason = f"daily_loss_{daily_pnl:.1f}%"
                elif weekly_pnl <= -self.cfg.weekly_loss_limit_pct:
                    halted = True
                    halt_reason = f"weekly_loss_{weekly_pnl:.1f}%"

            # -- Portfolio constraints --
            pt = PortfolioTrade(
                symbol=symbol,
                entry_date=entry_date,
                exit_date=exit_date,
                entry_price=trade_data["entry_price"],
                exit_price=trade_data["exit_price"],
                stop_loss=trade_data["stop_loss"],
                sl_distance_pct=trade_data["sl_distance_pct"],
                gross_return_pct=trade_data["gross_return_pct"],
                exit_reason=trade_data["exit_reason"],
                duration_days=trade_data["duration_days"],
                sector=sector,
                equity_at_entry=equity,
                concurrent_positions=len(open_positions),
            )

            # Skip checks
            skip = False
            skip_reason = ""

            if halted:
                skip = True
                skip_reason = f"halted:{halt_reason}"
            elif len(open_positions) >= self.cfg.max_concurrent_positions:
                skip = True
                skip_reason = f"max_positions:{len(open_positions)}"
            elif sector_count.get(sector, 0) >= self.cfg.max_per_sector:
                skip = True
                skip_reason = f"sector_cap:{sector}={sector_count.get(sector, 0)}"
            elif equity <= 0:
                skip = True
                skip_reason = "bankrupt"

            if skip:
                pt.was_skipped = True
                pt.skip_reason = skip_reason
                portfolio_trades.append(pt)
                continue

            # -- Position sizing: Fixed fractional --
            sl_dist_pct = trade_data["sl_distance_pct"]
            if sl_dist_pct <= 0:
                sl_dist_pct = 5.0  # fallback 5% SL

            risk_amount = equity * (self.cfg.risk_per_trade_pct / 100.0)
            position_size = risk_amount / (sl_dist_pct / 100.0)

            # Cap at max position %
            max_pos = equity * (self.cfg.max_position_pct / 100.0)
            position_size = min(position_size, max_pos)

            # Check total exposure (all open + new)
            total_open_notional = sum(p["position_size"] for p in open_positions)
            max_total = equity * (self.cfg.max_total_exposure_pct / 100.0)
            if total_open_notional + position_size > max_total:
                remaining = max_total - total_open_notional
                if remaining < risk_amount:
                    pt.was_skipped = True
                    pt.skip_reason = "exposure_cap"
                    portfolio_trades.append(pt)
                    continue
                position_size = remaining

            if position_size <= 0:
                pt.was_skipped = True
                pt.skip_reason = "zero_size"
                portfolio_trades.append(pt)
                continue

            shares = position_size / trade_data["entry_price"]

            # -- Cost model --
            cost_per_side = self.cfg.total_cost_per_side
            entry_cost = position_size * cost_per_side
            exit_value = shares * trade_data["exit_price"]
            exit_cost = exit_value * cost_per_side
            total_cost = entry_cost + exit_cost

            gross_pnl = exit_value - position_size
            net_pnl = gross_pnl - total_cost
            net_return = net_pnl / position_size * 100 if position_size > 0 else 0

            # Fill trade record
            pt.position_size_usd = round(position_size, 2)
            pt.risk_amount_usd = round(risk_amount, 2)
            pt.shares = round(shares, 8)
            pt.gross_pnl_usd = round(gross_pnl, 2)
            pt.commission_usd = round(entry_cost + exit_cost - (position_size * self.cfg.slippage_pct / 100 * 2), 2)
            pt.slippage_usd = round(position_size * self.cfg.slippage_pct / 100 * 2, 2)
            pt.net_pnl_usd = round(net_pnl, 2)
            pt.net_return_pct = round(net_return, 4)

            # Add to open positions (will be closed when exit_date is reached)
            open_positions.append({
                "symbol": symbol,
                "sector": sector,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "position_size": position_size,
                "net_pnl_usd": net_pnl,
            })
            sector_count[sector] = sector_count.get(sector, 0) + 1

            # Note: equity is NOT deducted here (we track notional, not cash lock)
            # PnL is realized at exit (handled at top of loop)
            pt.equity_after = equity  # will be updated at exit
            portfolio_trades.append(pt)

            # Record equity point
            ep = EquityPoint(
                date=entry_date,
                equity=round(equity, 2),
                drawdown_pct=round(dd_from_peak, 2),
                open_positions=len(open_positions),
                daily_pnl_pct=round(daily_pnl, 2),
            )
            equity_curve.append(ep)

        # -- Close remaining open positions --
        for pos in open_positions:
            pnl = pos["net_pnl_usd"]
            equity += pnl
            peak_equity = max(peak_equity, equity)

        # Final equity point
        if portfolio_trades:
            last_date = max(t.exit_date for t in portfolio_trades if not t.was_skipped)
            dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
            equity_curve.append(EquityPoint(
                date=last_date,
                equity=round(equity, 2),
                drawdown_pct=round(dd, 2),
                open_positions=0,
                daily_pnl_pct=0.0,
            ))

        return portfolio_trades, equity_curve


# =====================================================================
# Metrics Calculator
# =====================================================================

def calculate_portfolio_metrics(
    trades: List[PortfolioTrade],
    equity_curve: List[EquityPoint],
    config: PortfolioConfig,
) -> Dict[str, Any]:
    """Calculate comprehensive portfolio metrics."""
    executed = [t for t in trades if not t.was_skipped]
    skipped = [t for t in trades if t.was_skipped]

    if not executed:
        return {"error": "no_executed_trades"}

    # Basic returns
    total_pnl = sum(t.net_pnl_usd for t in executed)
    total_gross = sum(t.gross_pnl_usd for t in executed)
    total_commission = sum(t.commission_usd for t in executed)
    total_slippage = sum(t.slippage_usd for t in executed)
    total_cost = total_commission + total_slippage

    final_equity = config.initial_capital + total_pnl
    total_return_pct = (final_equity / config.initial_capital - 1) * 100

    # Win/loss
    winners = [t for t in executed if t.net_pnl_usd > 0]
    losers = [t for t in executed if t.net_pnl_usd <= 0]
    win_rate = len(winners) / len(executed) * 100 if executed else 0

    avg_win = statistics.mean([t.net_pnl_usd for t in winners]) if winners else 0
    avg_loss = statistics.mean([t.net_pnl_usd for t in losers]) if losers else 0
    avg_win_pct = statistics.mean([t.net_return_pct for t in winners]) if winners else 0
    avg_loss_pct = statistics.mean([t.net_return_pct for t in losers]) if losers else 0

    # Profit factor
    gross_wins = sum(t.net_pnl_usd for t in winners) if winners else 0
    gross_losses = abs(sum(t.net_pnl_usd for t in losers)) if losers else 0.01
    profit_factor = gross_wins / gross_losses

    # Payoff ratio
    payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

    # Expectancy
    expectancy_usd = total_pnl / len(executed)
    expectancy_r = expectancy_usd / (config.initial_capital * config.risk_per_trade_pct / 100) if config.risk_per_trade_pct > 0 else 0

    # Max drawdown (from equity curve)
    peak = config.initial_capital
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    for ep in equity_curve:
        peak = max(peak, ep.equity)
        dd_usd = peak - ep.equity
        dd_pct = dd_usd / peak * 100 if peak > 0 else 0
        max_dd_usd = max(max_dd_usd, dd_usd)
        max_dd_pct = max(max_dd_pct, dd_pct)

    # Also calculate from trade sequence for accuracy
    eq = config.initial_capital
    peak2 = eq
    max_dd2 = 0.0
    for t in executed:
        eq += t.net_pnl_usd
        peak2 = max(peak2, eq)
        dd = (peak2 - eq) / peak2 * 100 if peak2 > 0 else 0
        max_dd2 = max(max_dd2, dd)
    max_dd_pct = max(max_dd_pct, max_dd2)

    # Sharpe ratio (annualized)
    returns_pct = [t.net_return_pct for t in executed]
    if len(returns_pct) > 1:
        avg_r = statistics.mean(returns_pct)
        std_r = statistics.stdev(returns_pct)

        # Estimate trades per year
        date_range_days = 1
        try:
            dates = sorted(set(t.entry_date for t in executed))
            if len(dates) > 1:
                d0 = datetime.strptime(dates[0], "%Y-%m-%d")
                d1 = datetime.strptime(dates[-1], "%Y-%m-%d")
                date_range_days = max((d1 - d0).days, 1)
        except Exception:
            pass
        trades_per_year = len(executed) / max(date_range_days / 365.25, 0.1)
        sharpe = (avg_r / std_r) * math.sqrt(trades_per_year) if std_r > 0 else 0
    else:
        sharpe = 0
        avg_r = returns_pct[0] if returns_pct else 0

    # Sortino ratio (downside deviation only)
    neg_returns = [r for r in returns_pct if r < 0]
    if neg_returns and len(neg_returns) > 1:
        downside_std = statistics.stdev(neg_returns)
        trades_per_year_est = len(executed) / max(date_range_days / 365.25, 0.1) if date_range_days > 0 else 12
        sortino = (avg_r / downside_std) * math.sqrt(trades_per_year_est) if downside_std > 0 else 0
    else:
        sortino = 0

    # Calmar ratio
    annual_return = total_return_pct / max(date_range_days / 365.25, 0.1) if date_range_days > 0 else total_return_pct
    calmar = annual_return / max_dd_pct if max_dd_pct > 0 else 0

    # Consecutive wins/losses
    max_consec_win = 0
    max_consec_loss = 0
    cur_win = 0
    cur_loss = 0
    for t in executed:
        if t.net_pnl_usd > 0:
            cur_win += 1
            cur_loss = 0
        else:
            cur_loss += 1
            cur_win = 0
        max_consec_win = max(max_consec_win, cur_win)
        max_consec_loss = max(max_consec_loss, cur_loss)

    # Max consecutive loss amount
    max_consec_loss_usd = 0.0
    cur_loss_usd = 0.0
    for t in executed:
        if t.net_pnl_usd <= 0:
            cur_loss_usd += t.net_pnl_usd
        else:
            max_consec_loss_usd = min(max_consec_loss_usd, cur_loss_usd)
            cur_loss_usd = 0.0
    max_consec_loss_usd = min(max_consec_loss_usd, cur_loss_usd)

    # Duration stats
    durations = [t.duration_days for t in executed]
    avg_duration = statistics.mean(durations) if durations else 0
    med_duration = statistics.median(durations) if durations else 0

    # Average position size
    avg_pos_size = statistics.mean([t.position_size_usd for t in executed]) if executed else 0

    # Avg holding period
    avg_hold = statistics.mean([t.duration_days for t in executed]) if executed else 0

    # Sector distribution
    sector_dist: Dict[str, int] = {}
    for t in executed:
        sector_dist[t.sector] = sector_dist.get(t.sector, 0) + 1

    # Skip reasons
    skip_reasons: Dict[str, int] = {}
    for t in skipped:
        skip_reasons[t.skip_reason] = skip_reasons.get(t.skip_reason, 0) + 1

    # Monthly returns (for prop firm evaluation)
    monthly_returns: Dict[str, float] = {}
    for t in executed:
        month = t.entry_date[:7]
        monthly_returns[month] = monthly_returns.get(month, 0) + t.net_pnl_usd

    # Recovery factor
    recovery_factor = total_pnl / max_dd_usd if max_dd_usd > 0 else 0

    return {
        # Capital
        "initial_capital": config.initial_capital,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return_pct, 2),
        "annual_return_pct": round(annual_return, 2),
        "total_pnl_usd": round(total_pnl, 2),

        # Costs
        "total_gross_pnl": round(total_gross, 2),
        "total_commission": round(total_commission, 2),
        "total_slippage": round(total_slippage, 2),
        "total_cost": round(total_cost, 2),
        "cost_pct_of_pnl": round(total_cost / abs(total_gross) * 100 if total_gross != 0 else 0, 1),

        # Trades
        "total_signals": len(trades),
        "executed_trades": len(executed),
        "skipped_trades": len(skipped),
        "skip_reasons": skip_reasons,
        "winners": len(winners),
        "losers": len(losers),
        "win_rate_pct": round(win_rate, 1),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "avg_win_pct": round(avg_win_pct, 2),
        "avg_loss_pct": round(avg_loss_pct, 2),
        "biggest_win_usd": round(max((t.net_pnl_usd for t in executed), default=0), 2),
        "biggest_loss_usd": round(min((t.net_pnl_usd for t in executed), default=0), 2),
        "biggest_win_pct": round(max((t.net_return_pct for t in executed), default=0), 2),
        "biggest_loss_pct": round(min((t.net_return_pct for t in executed), default=0), 2),

        # Risk metrics
        "profit_factor": round(profit_factor, 2),
        "payoff_ratio": round(payoff_ratio, 2),
        "expectancy_usd": round(expectancy_usd, 2),
        "expectancy_r": round(expectancy_r, 3),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
        "recovery_factor": round(recovery_factor, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_usd": round(max_dd_usd, 2),
        "max_consecutive_wins": max_consec_win,
        "max_consecutive_losses": max_consec_loss,
        "max_consecutive_loss_usd": round(abs(max_consec_loss_usd), 2),

        # Duration
        "avg_duration_days": round(avg_duration, 1),
        "median_duration_days": round(med_duration, 1),
        "avg_position_size_usd": round(avg_pos_size, 2),

        # Distribution
        "sector_distribution": sector_dist,
        "monthly_returns_usd": monthly_returns,
        "date_range_days": date_range_days,
    }


# =====================================================================
# Monte Carlo Engine
# =====================================================================

def run_monte_carlo(
    raw_trades: List[Dict[str, Any]],
    config: PortfolioConfig,
    executed_trades: Optional[List[PortfolioTrade]] = None,
) -> List[MCResult]:
    """
    Run Monte Carlo simulation by bootstrapping from executed trades.

    Method: Take the net_return_pct distribution from actually-executed
    trades, then resample with replacement to simulate alternative
    sequences. This properly accounts for portfolio constraints
    (the "executable" trade set) rather than naively using all signals.

    Tests path-dependency: "given these trade outcomes, how sensitive
    is final equity to the order they arrived?"
    """
    results: List[MCResult] = []
    random.seed(config.mc_seed)

    # Use executed trades' return profile (the realistic set)
    if executed_trades:
        trade_pool = [
            {
                "net_return_pct": t.net_return_pct,
                "sl_distance_pct": t.sl_distance_pct,
                "net_pnl_usd": t.net_pnl_usd,
                "position_size_usd": t.position_size_usd,
                "duration_days": t.duration_days,
            }
            for t in executed_trades if not t.was_skipped
        ]
    else:
        # Fallback: use raw trades with cost model applied
        trade_pool = []
        for t in raw_trades:
            cost_rt = (config.total_cost_per_side * 2) * 100  # round-trip cost %
            net_ret = t["gross_return_pct"] - cost_rt
            trade_pool.append({
                "net_return_pct": net_ret,
                "sl_distance_pct": t["sl_distance_pct"],
                "net_pnl_usd": 0,  # will be calculated
                "position_size_usd": 0,
                "duration_days": t["duration_days"],
            })

    if not trade_pool:
        return results

    n_trades = len(trade_pool)

    for run_id in range(config.mc_runs):
        # Bootstrap: resample n_trades with replacement, shuffled
        sampled = [random.choice(trade_pool) for _ in range(n_trades)]

        equity = config.initial_capital
        peak = equity
        max_dd = 0.0
        pnl_list: List[float] = []
        wins = 0
        total = 0

        for td in sampled:
            if equity <= 0:
                break

            # Size the position based on current equity
            sl_dist = td["sl_distance_pct"]
            if sl_dist <= 0:
                sl_dist = 5.0

            risk_amount = equity * (config.risk_per_trade_pct / 100.0)
            position_size = risk_amount / (sl_dist / 100.0)
            max_pos = equity * (config.max_position_pct / 100.0)
            position_size = min(position_size, max_pos)

            if position_size <= 0:
                continue

            # Apply the trade's return to the position
            net_pnl = position_size * (td["net_return_pct"] / 100.0)

            equity += net_pnl
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

            pnl_list.append(td["net_return_pct"])
            if net_pnl > 0:
                wins += 1
            total += 1

        # Calculate MC run metrics
        final_eq = max(equity, 0)
        total_ret = (final_eq / config.initial_capital - 1) * 100

        if len(pnl_list) > 1:
            avg_r = statistics.mean(pnl_list)
            std_r = statistics.stdev(pnl_list)
            sharpe_mc = (avg_r / std_r) * math.sqrt(min(total, 252)) if std_r > 0 else 0
        else:
            sharpe_mc = 0

        win_pnls = [p for p in pnl_list if p > 0]
        loss_pnls = [p for p in pnl_list if p <= 0]
        pf = sum(win_pnls) / abs(sum(loss_pnls)) if loss_pnls and sum(loss_pnls) != 0 else 99.0
        wr = wins / total * 100 if total > 0 else 0
        calmar_mc = total_ret / max_dd if max_dd > 0 else 0

        results.append(MCResult(
            run_id=run_id,
            final_equity=round(final_eq, 2),
            total_return_pct=round(total_ret, 2),
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=round(sharpe_mc, 2),
            profit_factor=round(pf, 2),
            win_rate_pct=round(wr, 1),
            total_trades=total,
            calmar_ratio=round(calmar_mc, 2),
        ))

    return results


# =====================================================================
# Report Generator
# =====================================================================

def generate_portfolio_report(
    metrics: Dict[str, Any],
    mc_results: List[MCResult],
    config: PortfolioConfig,
    report_path: str,
):
    """Generate comprehensive portfolio report with prop firm metrics."""
    lines = []
    w = lines.append

    w("=" * 110)
    w("PORTFOLIO BACKTEST V2.1 - HIGH FIDELITY EQUITY SIMULATION")
    w(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w(f"Truth Level: 8/10")
    w("=" * 110)
    w("")

    # ── Configuration ──
    w("CONFIGURATION")
    w("-" * 60)
    w(f"  Initial Capital:       ${config.initial_capital:,.0f}")
    w(f"  Risk Per Trade:        {config.risk_per_trade_pct}% of equity")
    w(f"  Max Position Size:     {config.max_position_pct}% of equity")
    w(f"  Commission/side:       {config.commission_per_side * 100:.2f}%")
    w(f"  Slippage/side:         {config.slippage_pct:.3f}%")
    w(f"  Total Cost/side:       {config.total_cost_per_side * 100:.3f}%")
    w(f"  Max Concurrent Pos:    {config.max_concurrent_positions}")
    w(f"  Max Per Sector:        {config.max_per_sector}")
    w(f"  Max Total Exposure:    {config.max_total_exposure_pct}%")
    mode_str = "PROP FIRM" if config.prop_mode else "STANDARD"
    w(f"  Mode:                  {mode_str}")
    if config.prop_mode:
        w(f"  Prop Max DD:           {config.prop_max_dd_pct}%")
        w(f"  Prop Daily DD:         {config.prop_daily_dd_pct}%")
    else:
        w(f"  Daily Loss Limit:      {config.daily_loss_limit_pct}%")
        w(f"  Weekly Loss Limit:     {config.weekly_loss_limit_pct}%")
        w(f"  Trailing DD Halt:      {config.trailing_dd_halt_pct}%")
    w(f"  Monte Carlo Runs:      {config.mc_runs}")
    w("")

    # ── Key Results ──
    w("=" * 110)
    w("KEY RESULTS")
    w("=" * 110)
    w("")
    w(f"  Final Equity:          ${metrics['final_equity']:>12,.2f}")
    w(f"  Total Return:          {metrics['total_return_pct']:>+10.2f}%")
    w(f"  Annualized Return:     {metrics['annual_return_pct']:>+10.2f}%")
    w(f"  Total PnL:             ${metrics['total_pnl_usd']:>12,.2f}")
    w("")

    # ── Cost Analysis ──
    w("COST ANALYSIS")
    w("-" * 60)
    w(f"  Gross PnL:             ${metrics['total_gross_pnl']:>12,.2f}")
    w(f"  Commission:            ${metrics['total_commission']:>12,.2f}")
    w(f"  Slippage:              ${metrics['total_slippage']:>12,.2f}")
    w(f"  Total Costs:           ${metrics['total_cost']:>12,.2f}")
    w(f"  Cost as % of Gross:    {metrics['cost_pct_of_pnl']:.1f}%")
    w(f"  Net PnL:               ${metrics['total_pnl_usd']:>12,.2f}")
    w("")

    # ── Trade Statistics ──
    w("TRADE STATISTICS")
    w("-" * 60)
    w(f"  Total Signals:         {metrics['total_signals']}")
    w(f"  Executed Trades:       {metrics['executed_trades']}")
    w(f"  Skipped Trades:        {metrics['skipped_trades']}")
    w(f"  Win Rate:              {metrics['win_rate_pct']:.1f}%")
    w(f"  Winners:               {metrics['winners']}")
    w(f"  Losers:                {metrics['losers']}")
    w(f"  Avg Win:               ${metrics['avg_win_usd']:>10,.2f}  ({metrics['avg_win_pct']:+.2f}%)")
    w(f"  Avg Loss:              ${metrics['avg_loss_usd']:>10,.2f}  ({metrics['avg_loss_pct']:+.2f}%)")
    w(f"  Biggest Win:           ${metrics['biggest_win_usd']:>10,.2f}  ({metrics['biggest_win_pct']:+.2f}%)")
    w(f"  Biggest Loss:          ${metrics['biggest_loss_usd']:>10,.2f}  ({metrics['biggest_loss_pct']:+.2f}%)")
    w(f"  Avg Position Size:     ${metrics['avg_position_size_usd']:>10,.2f}")
    w(f"  Avg Duration:          {metrics['avg_duration_days']:.1f} days")
    w(f"  Median Duration:       {metrics['median_duration_days']:.1f} days")
    w("")

    # ── Skip Reasons ──
    if metrics["skip_reasons"]:
        w("SKIP REASONS (why signals were not executed)")
        w("-" * 60)
        for reason, count in sorted(metrics["skip_reasons"].items(), key=lambda x: -x[1]):
            w(f"  {reason:<40s}  {count:>5d}")
        w("")

    # ── Prop Firm Standard Metrics ──
    w("=" * 110)
    w("PROP FIRM EVALUATION METRICS (FTMO / MFF / TFT Standard)")
    w("=" * 110)
    w("")

    w("  RISK-ADJUSTED RETURNS")
    w("  " + "-" * 55)
    w(f"  Profit Factor:         {metrics['profit_factor']:.2f}          (Target: > 1.5)")
    w(f"  Payoff Ratio:          {metrics['payoff_ratio']:.2f}          (Avg Win / Avg Loss)")
    w(f"  Expectancy/trade:      ${metrics['expectancy_usd']:>8,.2f}    (Target: > $0)")
    w(f"  Expectancy (R):        {metrics['expectancy_r']:.3f}R         (Target: > 0.3R)")
    w(f"  Sharpe Ratio:          {metrics['sharpe_ratio']:.2f}          (Target: > 1.0)")
    w(f"  Sortino Ratio:         {metrics['sortino_ratio']:.2f}          (Target: > 1.5)")
    w(f"  Calmar Ratio:          {metrics['calmar_ratio']:.2f}          (Target: > 2.0)")
    w(f"  Recovery Factor:       {metrics['recovery_factor']:.2f}          (Target: > 3.0)")
    w("")

    w("  DRAWDOWN ANALYSIS")
    w("  " + "-" * 55)
    w(f"  Max Drawdown:          {metrics['max_drawdown_pct']:.2f}%       (FTMO limit: 10%)")
    w(f"  Max DD (USD):          ${metrics['max_drawdown_usd']:>10,.2f}")
    ftmo_pass = "PASS" if metrics["max_drawdown_pct"] < 10 else "FAIL"
    mff_pass = "PASS" if metrics["max_drawdown_pct"] < 12 else "FAIL"
    w(f"  FTMO DD Check:         {ftmo_pass}")
    w(f"  MFF DD Check:          {mff_pass}")
    w("")

    w("  CONSISTENCY")
    w("  " + "-" * 55)
    w(f"  Max Consecutive Wins:  {metrics['max_consecutive_wins']}")
    w(f"  Max Consecutive Losses:{metrics['max_consecutive_losses']}")
    w(f"  Max Consec Loss (USD): ${metrics['max_consecutive_loss_usd']:>10,.2f}")
    w("")

    # Monthly returns table
    monthly = metrics.get("monthly_returns_usd", {})
    if monthly:
        w("  MONTHLY RETURNS")
        w("  " + "-" * 55)
        w(f"  {'Month':<10s}  {'PnL (USD)':>12s}  {'PnL (%)':>10s}  {'Status':>8s}")
        positive_months = 0
        total_months = 0
        for month in sorted(monthly.keys()):
            pnl = monthly[month]
            pnl_pct = pnl / config.initial_capital * 100
            status = "+" if pnl > 0 else "-"
            if pnl > 0:
                positive_months += 1
            total_months += 1
            w(f"  {month:<10s}  ${pnl:>11,.2f}  {pnl_pct:>+9.2f}%  {status:>8s}")

        w(f"\n  Profitable Months: {positive_months}/{total_months} ({positive_months/total_months*100:.0f}%)" if total_months > 0 else "")
        w("")

    # Sector distribution
    sectors = metrics.get("sector_distribution", {})
    if sectors:
        w("  SECTOR DISTRIBUTION")
        w("  " + "-" * 55)
        total_trades = sum(sectors.values())
        for sec, count in sorted(sectors.items(), key=lambda x: -x[1]):
            pct = count / total_trades * 100
            bar = "#" * int(pct / 2)
            w(f"  {sec:<12s}  {count:>4d}  ({pct:>5.1f}%)  {bar}")
        w("")

    # ── Monte Carlo Results ──
    if mc_results:
        w("=" * 110)
        w(f"MONTE CARLO SIMULATION ({len(mc_results)} runs)")
        w("=" * 110)
        w("")

        returns = sorted([r.total_return_pct for r in mc_results])
        dds = sorted([r.max_drawdown_pct for r in mc_results])
        sharpes = sorted([r.sharpe_ratio for r in mc_results])
        pfs = sorted([r.profit_factor for r in mc_results])

        def percentile(arr, p):
            idx = int(len(arr) * p / 100)
            idx = max(0, min(idx, len(arr) - 1))
            return arr[idx]

        w("  RETURN DISTRIBUTION")
        w("  " + "-" * 55)
        w(f"  {'Percentile':<15s}  {'Return%':>10s}  {'MaxDD%':>10s}  {'Sharpe':>8s}  {'PF':>8s}")
        for p in [5, 10, 25, 50, 75, 90, 95]:
            w(f"  P{p:<14d}  {percentile(returns, p):>+9.2f}%  {percentile(dds, p):>9.2f}%  "
              f"{percentile(sharpes, p):>8.2f}  {percentile(pfs, p):>8.2f}")
        w("")

        w("  SUMMARY STATISTICS")
        w("  " + "-" * 55)
        w(f"  Mean Return:           {statistics.mean(returns):+.2f}%")
        w(f"  Std Dev Return:        {statistics.stdev(returns):.2f}%")
        w(f"  Mean Max DD:           {statistics.mean(dds):.2f}%")
        w(f"  Mean Sharpe:           {statistics.mean(sharpes):.2f}")
        w(f"  Mean PF:               {statistics.mean(pfs):.2f}")
        w("")

        # Probability of specific outcomes
        prob_positive = sum(1 for r in returns if r > 0) / len(returns) * 100
        prob_10pct = sum(1 for r in returns if r > 10) / len(returns) * 100
        prob_dd_under_10 = sum(1 for d in dds if d < 10) / len(dds) * 100
        prob_dd_under_5 = sum(1 for d in dds if d < 5) / len(dds) * 100
        prob_ruin = sum(1 for r in mc_results if r.final_equity <= 0) / len(mc_results) * 100

        w("  PROBABILITY TABLE")
        w("  " + "-" * 55)
        w(f"  P(Return > 0%):        {prob_positive:.1f}%")
        w(f"  P(Return > 10%):       {prob_10pct:.1f}%")
        w(f"  P(MaxDD < 10%):        {prob_dd_under_10:.1f}%    (FTMO safe)")
        w(f"  P(MaxDD < 5%):         {prob_dd_under_5:.1f}%     (Ultra safe)")
        w(f"  P(Ruin):               {prob_ruin:.2f}%")
        w("")

        # Worst case scenario
        worst = min(mc_results, key=lambda r: r.total_return_pct)
        best = max(mc_results, key=lambda r: r.total_return_pct)
        w("  WORST CASE (P5)")
        w("  " + "-" * 55)
        w(f"  Worst Return:          {worst.total_return_pct:+.2f}%")
        w(f"  Worst Max DD:          {worst.max_drawdown_pct:.2f}%")
        w(f"  Best Return:           {best.total_return_pct:+.2f}%")
        w(f"  Best Max DD:           {best.max_drawdown_pct:.2f}%")
        w("")

    # ── Overall Assessment ──
    w("=" * 110)
    w("OVERALL ASSESSMENT")
    w("=" * 110)
    w("")

    score = 0
    checks = []

    # 1. Profitability
    if metrics["total_return_pct"] > 0:
        score += 1
        checks.append("[PASS] Positive return")
    else:
        checks.append("[FAIL] Negative return")

    # 2. Profit factor
    if metrics["profit_factor"] >= 1.5:
        score += 1
        checks.append(f"[PASS] PF {metrics['profit_factor']:.2f} >= 1.5")
    else:
        checks.append(f"[WARN] PF {metrics['profit_factor']:.2f} < 1.5")

    # 3. Max DD
    if metrics["max_drawdown_pct"] < 10:
        score += 1
        checks.append(f"[PASS] MaxDD {metrics['max_drawdown_pct']:.1f}% < 10% (FTMO safe)")
    elif metrics["max_drawdown_pct"] < 15:
        checks.append(f"[WARN] MaxDD {metrics['max_drawdown_pct']:.1f}% - borderline")
    else:
        checks.append(f"[FAIL] MaxDD {metrics['max_drawdown_pct']:.1f}% > 15%")

    # 4. Sharpe
    if metrics["sharpe_ratio"] >= 1.0:
        score += 1
        checks.append(f"[PASS] Sharpe {metrics['sharpe_ratio']:.2f} >= 1.0")
    else:
        checks.append(f"[WARN] Sharpe {metrics['sharpe_ratio']:.2f} < 1.0")

    # 5. Win rate
    if metrics["win_rate_pct"] >= 40:
        score += 1
        checks.append(f"[PASS] WinRate {metrics['win_rate_pct']:.1f}% >= 40%")
    else:
        checks.append(f"[WARN] WinRate {metrics['win_rate_pct']:.1f}% < 40%")

    # 6. Expectancy
    if metrics["expectancy_r"] > 0.2:
        score += 1
        checks.append(f"[PASS] Expectancy {metrics['expectancy_r']:.3f}R > 0.2R")
    else:
        checks.append(f"[WARN] Expectancy {metrics['expectancy_r']:.3f}R < 0.2R")

    # 7. Recovery factor
    if metrics["recovery_factor"] >= 2.0:
        score += 1
        checks.append(f"[PASS] Recovery Factor {metrics['recovery_factor']:.2f} >= 2.0")
    else:
        checks.append(f"[WARN] Recovery Factor {metrics['recovery_factor']:.2f} < 2.0")

    # 8. Calmar
    if metrics["calmar_ratio"] >= 1.0:
        score += 1
        checks.append(f"[PASS] Calmar {metrics['calmar_ratio']:.2f} >= 1.0")
    else:
        checks.append(f"[WARN] Calmar {metrics['calmar_ratio']:.2f} < 1.0")

    # MC checks
    if mc_results:
        prob_pos = sum(1 for r in mc_results if r.total_return_pct > 0) / len(mc_results) * 100
        if prob_pos >= 90:
            score += 1
            checks.append(f"[PASS] MC P(profit) = {prob_pos:.0f}% >= 90%")
        else:
            checks.append(f"[WARN] MC P(profit) = {prob_pos:.0f}% < 90%")

        prob_ftmo = sum(1 for r in mc_results if r.max_drawdown_pct < 10) / len(mc_results) * 100
        if prob_ftmo >= 80:
            score += 1
            checks.append(f"[PASS] MC P(DD<10%) = {prob_ftmo:.0f}% >= 80% (FTMO safe)")
        else:
            checks.append(f"[WARN] MC P(DD<10%) = {prob_ftmo:.0f}% < 80%")

    for c in checks:
        w(f"  {c}")
    w("")
    w(f"  SCORE: {score}/{len(checks)}")
    w("")

    # Prop firm verdict
    if config.prop_mode:
        w("  PROP FIRM VERDICT")
        w("  " + "-" * 55)
        if metrics["max_drawdown_pct"] < config.prop_max_dd_pct:
            w(f"  Max DD {metrics['max_drawdown_pct']:.1f}% < {config.prop_max_dd_pct}% -> PASS")
        else:
            w(f"  Max DD {metrics['max_drawdown_pct']:.1f}% >= {config.prop_max_dd_pct}% -> FAIL (account blown)")
        w("")

    w("=" * 110)

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  Report -> {report_path}")


def export_portfolio_trades(
    trades: List[PortfolioTrade],
    csv_path: str,
):
    """Export enriched trade log to CSV."""
    cols = [
        "symbol", "sector", "entry_date", "exit_date", "duration_days",
        "entry_price", "exit_price", "stop_loss", "sl_distance_pct",
        "gross_return_pct", "exit_reason",
        "equity_at_entry", "position_size_usd", "risk_amount_usd", "shares",
        "gross_pnl_usd", "commission_usd", "slippage_usd", "net_pnl_usd",
        "net_return_pct", "concurrent_positions",
        "was_skipped", "skip_reason",
    ]
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for t in trades:
            row = {c: getattr(t, c, "") for c in cols}
            writer.writerow(row)
    print(f"  Trades CSV -> {csv_path}  ({len(trades)} rows)")


def export_equity_curve(equity_curve: List[EquityPoint], csv_path: str):
    """Export equity curve to CSV."""
    cols = ["date", "equity", "drawdown_pct", "open_positions", "daily_pnl_pct"]
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for ep in equity_curve:
            writer.writerow(asdict(ep))
    print(f"  Equity CSV -> {csv_path}  ({len(equity_curve)} points)")


def export_mc_results(mc_results: List[MCResult], csv_path: str):
    """Export Monte Carlo results to CSV."""
    cols = [
        "run_id", "final_equity", "total_return_pct", "max_drawdown_pct",
        "sharpe_ratio", "profit_factor", "win_rate_pct", "total_trades",
        "calmar_ratio",
    ]
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for r in mc_results:
            writer.writerow(asdict(r))
    print(f"  MC CSV -> {csv_path}  ({len(mc_results)} runs)")


# =====================================================================
# Main
# =====================================================================

def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Portfolio Backtest V2.1 - High Fidelity Simulation"
    )
    ap.add_argument("--capital", type=float, default=100_000,
                    help="Initial capital in USD (default: 100000)")
    ap.add_argument("--risk-pct", type=float, default=1.0,
                    help="Risk per trade as %% of equity (default: 1.0)")
    ap.add_argument("--max-pos-pct", type=float, default=20.0,
                    help="Max single position as %% of equity (default: 20)")
    ap.add_argument("--commission", type=float, default=0.001,
                    help="Commission per side (default: 0.001 = 0.1%%)")
    ap.add_argument("--slippage", type=float, default=0.05,
                    help="Slippage per side in %% (default: 0.05)")
    ap.add_argument("--max-positions", type=int, default=10,
                    help="Max concurrent positions (default: 10)")
    ap.add_argument("--max-sector", type=int, default=3,
                    help="Max positions per sector (default: 3)")
    ap.add_argument("--daily-limit", type=float, default=3.0,
                    help="Daily loss limit %% (default: 3.0)")
    ap.add_argument("--weekly-limit", type=float, default=6.0,
                    help="Weekly loss limit %% (default: 6.0)")
    ap.add_argument("--trailing-dd", type=float, default=50.0,
                    help="Trailing DD halt %% (default: 50.0 standard, 10 prop)")
    ap.add_argument("--prop-mode", action="store_true",
                    help="Enable prop firm mode (FTMO limits)")
    ap.add_argument("--mc-runs", type=int, default=1000,
                    help="Monte Carlo simulation count (default: 1000)")
    ap.add_argument("--mc-seed", type=int, default=42,
                    help="Random seed for MC (default: 42)")
    ap.add_argument("--trade-log", type=str, default=None,
                    help="Path to V2.1 trade log CSV")
    args = ap.parse_args()

    # Build config
    config = PortfolioConfig(
        initial_capital=args.capital,
        risk_per_trade_pct=args.risk_pct,
        max_position_pct=args.max_pos_pct,
        commission_per_side=args.commission,
        slippage_pct=args.slippage,
        max_concurrent_positions=args.max_positions,
        max_per_sector=args.max_sector,
        daily_loss_limit_pct=args.daily_limit,
        weekly_loss_limit_pct=args.weekly_limit,
        trailing_dd_halt_pct=args.trailing_dd,
        prop_mode=args.prop_mode,
        mc_runs=args.mc_runs,
        mc_seed=args.mc_seed,
    )

    if config.prop_mode:
        config.prop_max_dd_pct = 10.0
        config.prop_daily_dd_pct = 5.0
        config.daily_loss_limit_pct = 5.0
        config.weekly_loss_limit_pct = 8.0
        config.trailing_dd_halt_pct = 10.0

    # Load trade log
    trade_log_path = args.trade_log or os.path.join(REPORT_DIR, "v21_trade_log.csv")
    if not os.path.exists(trade_log_path):
        print(f"ERROR: Trade log not found: {trade_log_path}")
        print("Run backtest_v21_detailed first to generate the trade log.")
        sys.exit(1)

    print(f"\n{'=' * 90}")
    print(f"  PORTFOLIO BACKTEST V2.1 - HIGH FIDELITY SIMULATION")
    print(f"{'=' * 90}")
    print(f"  Capital:  ${config.initial_capital:,.0f}    Risk/trade: {config.risk_per_trade_pct}%")
    print(f"  Cost:     {config.commission_per_side*100:.2f}% comm + {config.slippage_pct:.3f}% slip per side")
    print(f"  Limits:   {config.max_concurrent_positions} pos max, {config.max_per_sector}/sector")
    print(f"  Mode:     {'PROP FIRM (FTMO)' if config.prop_mode else 'STANDARD'}")
    print(f"  MC Runs:  {config.mc_runs}")
    print(f"  Source:   {trade_log_path}")
    print(f"{'=' * 90}\n")

    t0 = time.time()

    # Load trades
    print("Loading trade log...")
    raw_trades = load_trade_log(trade_log_path)
    print(f"  Loaded {len(raw_trades)} trades from {len(set(t['symbol'] for t in raw_trades))} symbols")
    if raw_trades:
        print(f"  Date range: {raw_trades[0]['entry_date']} -> {raw_trades[-1]['entry_date']}")
    print()

    # ── Phase 1: Primary simulation ──
    print("Phase 1: Portfolio simulation...")
    sim = PortfolioSimulator(config)
    portfolio_trades, equity_curve = sim.run(raw_trades, shuffle=False)

    executed = [t for t in portfolio_trades if not t.was_skipped]
    skipped = [t for t in portfolio_trades if t.was_skipped]
    print(f"  Executed: {len(executed)} trades")
    print(f"  Skipped:  {len(skipped)} trades")
    if executed:
        final_eq = config.initial_capital + sum(t.net_pnl_usd for t in executed)
        ret = (final_eq / config.initial_capital - 1) * 100
        print(f"  Final equity: ${final_eq:,.2f} ({ret:+.2f}%)")
    print()

    # ── Phase 2: Calculate metrics ──
    print("Phase 2: Calculating metrics...")
    metrics = calculate_portfolio_metrics(portfolio_trades, equity_curve, config)
    print(f"  PF={metrics.get('profit_factor', 0):.2f}  "
          f"Sharpe={metrics.get('sharpe_ratio', 0):.2f}  "
          f"MaxDD={metrics.get('max_drawdown_pct', 0):.2f}%  "
          f"WR={metrics.get('win_rate_pct', 0):.1f}%")
    print()

    # ── Phase 3: Monte Carlo ──
    print(f"Phase 3: Monte Carlo ({config.mc_runs} runs)...")
    mc_t0 = time.time()
    mc_results = run_monte_carlo(raw_trades, config, executed_trades=executed)
    mc_time = time.time() - mc_t0
    mc_returns = [r.total_return_pct for r in mc_results]
    mc_dds = [r.max_drawdown_pct for r in mc_results]
    print(f"  Completed in {mc_time:.1f}s")
    print(f"  Median return: {sorted(mc_returns)[len(mc_returns)//2]:+.2f}%")
    print(f"  Median MaxDD:  {sorted(mc_dds)[len(mc_dds)//2]:.2f}%")
    print(f"  P(profit):     {sum(1 for r in mc_returns if r > 0)/len(mc_returns)*100:.1f}%")
    print()

    # ── Phase 4: Export ──
    print("Phase 4: Exporting results...")
    report_path = os.path.join(REPORT_DIR, "portfolio_v21_report.txt")
    trades_csv = os.path.join(REPORT_DIR, "portfolio_v21_trades.csv")
    equity_csv = os.path.join(REPORT_DIR, "portfolio_v21_equity.csv")
    mc_csv = os.path.join(REPORT_DIR, "portfolio_v21_monte_carlo.csv")

    generate_portfolio_report(metrics, mc_results, config, report_path)
    export_portfolio_trades(portfolio_trades, trades_csv)
    export_equity_curve(equity_curve, equity_csv)
    export_mc_results(mc_results, mc_csv)

    # Also save metrics as JSON
    metrics_json = os.path.join(REPORT_DIR, "portfolio_v21_metrics.json")
    serializable_metrics = {k: v for k, v in metrics.items()
                           if not isinstance(v, (set, type))}
    with open(metrics_json, "w", encoding="utf-8") as f:
        json.dump(serializable_metrics, f, indent=2, default=str)
    print(f"  Metrics JSON -> {metrics_json}")

    total_time = time.time() - t0
    print(f"\n{'=' * 90}")
    print(f"  DONE in {total_time:.1f}s")
    print(f"  Open portfolio_v21_report.txt for full analysis")
    print(f"{'=' * 90}")


if __name__ == "__main__":
    main()
