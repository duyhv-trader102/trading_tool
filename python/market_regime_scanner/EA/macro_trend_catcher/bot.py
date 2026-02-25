"""
Trend Catcher V3 -- Top-Down Alignment Bot
==========================================

Live MT5 trading bot for the Macro Trend Catcher V3 strategy.

Strategy
--------
V3 signal pipeline using ``build_tf_regime()`` + ``evaluate_overall_signal()``
with two signal paths:

**Path 1 — balance_aligned** (classic):
    All 3 TFs ``IN BALANCE`` + ready + directions match  ⇒  ENTER

**Path 2 — breakout_ready**:
    Monthly ``BREAKOUT``  +  W/D ``IN BALANCE`` + ready + aligned  ⇒  ENTER

Timeframe Mapping (fewer bars → less noise)::

    Monthly sessions : W1 bars  (≈4-5 bars/session)
    Weekly  sessions : D1 bars  (≈5  bars/session)
    Daily   sessions : H4 bars  (≈6  bars/session)

Entry Filters:
    * V3 signal: balance_aligned or breakout_ready
    * Compression gate (V2.1): all TFs must be Normal/Neutral/3-1-3
    * MBA continuity check
    * Cooldown after stop-loss hit (same direction blocked)

Exit:
    * Monthly direction flips  →  close position
    * Stop-loss hit (server-side on MT5)

Dependencies:
    * ``analytic.tpo_mba.tracker.build_mba_context()`` → MBAMetadata
    * ``workflow.pipeline.analyze_timeframe()`` → TPO sessions
    * ``infra.mt5`` → order execution

Usage::

    # Dry run (no real trades)
    python -m EA.macro_trend_catcher.bot --dry-run

    # Live trading
    python -m EA.macro_trend_catcher.bot

    # Specific asset classes
    python -m EA.macro_trend_catcher.bot --assets FOREX_MAJORS US_INDICES

    # Run once (no loop)
    python -m EA.macro_trend_catcher.bot --once
"""

import json
import logging
import time
import argparse
import schedule
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

# Path setup
from core.path_manager import setup_path
setup_path()

from infra.data.mt5_provider import MT5Provider
from infra import mt5 as mt5_infra
from workflow.pipeline import analyze_timeframe
from analytic.tpo_mba.tracker import build_mba_context
from analytic.tpo_mba.schema import MBAMetadata
from EA.shared.indicators import calculate_atr
from EA.macro_trend_catcher.config import (
    TrendCatcherV2Config,
    ASSET_CONFIG,
    STATE_FILE,
    LOG_DIR,
    REPORT_DIR,
    MAGIC_NUMBER,
)
from analytic.tpo_mba.alignment import (
    build_tf_regime, evaluate_overall_signal,
)
from EA.macro_trend_catcher.signals import (
    SignalGeneratorV2,
    TrendSignalV2,
)

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

try:
    _fh = logging.FileHandler(
        LOG_DIR / f"bot_{datetime.now():%Y%m%d}.log", mode="a"
    )
    _fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(_fh)
except Exception:
    pass


# ── Position dataclass ───────────────────────────────────────

@dataclass
class V2Position:
    """Tracked position (flat JSON-serialisable)."""
    symbol: str
    direction: str         # "bullish" | "bearish"
    entry_price: float
    stop_loss: float       # fixed, never trails
    entry_time: datetime
    lot_size: float
    ticket: int = 0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "entry_time": self.entry_time.isoformat(),
            "lot_size": self.lot_size,
            "ticket": self.ticket,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "V2Position":
        return cls(
            symbol=d["symbol"],
            direction=d["direction"],
            entry_price=d["entry_price"],
            stop_loss=d["stop_loss"],
            entry_time=datetime.fromisoformat(d["entry_time"]),
            lot_size=d["lot_size"],
            ticket=d.get("ticket", 0),
        )


# ═════════════════════════════════════════════════════════════
# Bot
# ═════════════════════════════════════════════════════════════

class TrendCatcherV2Bot:
    """
    Live trading bot — Trend Catcher V2 (top-down alignment).

    Key differences from V1:
    - Uses ``build_mba_context()`` (not deprecated ``classify_regime()``).
    - Supports ``min_mba_continuity`` filter (MBA must have ≥ N units).
    - Supports cooldown after stop-loss hit.
    - Uses ``infra.mt5`` for order execution (no V3 executor dependency).
    """

    def __init__(
        self,
        asset_classes: Optional[List[str]] = None,
        dry_run: bool = True,
    ):
        self.asset_classes = asset_classes or list(ASSET_CONFIG.keys())
        self.dry_run = dry_run

        # Components
        self.provider = MT5Provider()
        self.signal_gen = SignalGeneratorV2()

        # State
        self.active_positions: Dict[str, V2Position] = {}
        self.cooldowns: Dict[str, datetime] = {}  # symbol → cooldown_expiry
        self.last_scan_time: Optional[datetime] = None

        # Stats
        self.stats = {
            "scanned": 0,
            "signals": 0,
            "executed": 0,
            "errors": 0,
        }

    # ── MT5 connection ────────────────────────────────────────

    def connect(self) -> bool:
        """Connect to MT5 terminal using infra settings."""
        try:
            from infra.settings_loader import get_mt5_config
            cfg = get_mt5_config()
            mt5_infra.start_mt5(
                username=int(cfg["username"]),
                password=cfg["password"],
                server=cfg["server"],
                mt5Pathway=cfg["mt5Pathway"],
            )
            acct = mt5_infra.get_account_info()
            if acct is None:
                logger.error("MT5: account_info returned None")
                return False
            logger.info(
                "[OK] V2 Bot connected — Account %s  Balance $%.2f",
                acct.login, acct.balance,
            )
            return True
        except Exception as exc:
            logger.error("MT5 connection failed: %s", exc)
            return False

    # ── State persistence ─────────────────────────────────────

    def load_state(self):
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                for sym, pd in data.get("positions", {}).items():
                    self.active_positions[sym] = V2Position.from_dict(pd)
                for sym, ts in data.get("cooldowns", {}).items():
                    self.cooldowns[sym] = datetime.fromisoformat(ts)
                if self.active_positions:
                    logger.info("Loaded %d V2 positions", len(self.active_positions))
            except Exception as exc:
                logger.warning("Failed to load V2 state: %s", exc)

    def save_state(self):
        try:
            payload = {
                "timestamp": datetime.now().isoformat(),
                "version": "V2",
                "positions": {
                    s: p.to_dict() for s, p in self.active_positions.items()
                },
                "cooldowns": {
                    s: t.isoformat() for s, t in self.cooldowns.items()
                },
            }
            STATE_FILE.write_text(json.dumps(payload, indent=2))
        except Exception as exc:
            logger.error("Failed to save V2 state: %s", exc)

    # ── Config lookup ─────────────────────────────────────────

    def _config_for(self, symbol: str) -> Optional[TrendCatcherV2Config]:
        for ac in self.asset_classes:
            entry = ASSET_CONFIG.get(ac)
            if entry and symbol in entry["symbols"]:
                return entry["config"]
        return None

    # ── MBA analysis ──────────────────────────────────────────

    @staticmethod
    def _build_meta(
        symbol: str,
        data_tf: str,
        session_type: str,
        provider,
        bars: int,
        tf_label: str,
    ) -> Tuple[Optional[MBAMetadata], list]:
        """
        Fetch bars → build TPO sessions → build_mba_context.

        Returns (MBAMetadata | None, raw_sessions_list).

        data_tf / session_type / bars:
            Monthly  → ("W1", "M",  600)  ≈4-5 W1 bars per month
            Weekly   → ("D1", "W", 3000)  ≈5 D1 bars per week
            Daily    → ("H4", "D", 5000)  ≈6 H4 bars per day
        """
        sessions, _ = analyze_timeframe(
            symbol, data_tf, session_type,
            provider=provider, bars=bars,
        )
        if not sessions or len(sessions) < 3:
            return None, []

        # build_mba_context strips unclosed tails internally
        meta = build_mba_context(
            sessions, timeframe=tf_label, symbol=symbol,
        )
        return meta, sessions

    def analyze_symbol(
        self, symbol: str, config: TrendCatcherV2Config
    ) -> Optional[dict]:
        """
        Run top-down MBA analysis:  Monthly → Weekly → Daily.

        Uses V3 pipeline: ``build_tf_regime()`` → ``evaluate_overall_signal()``
        with Path 1 (balance aligned) + Path 2 (breakout ready).

        TF Mapping (fewer bars per session → less noise):
            Monthly : W1 bars → M sessions  (≈4-5 bars/session)
            Weekly  : D1 bars → W sessions  (≈5 bars/session)
            Daily   : H4 bars → D sessions  (≈6 bars/session)

        Returns dict with signal_result + price data, or None.
        """
        try:
            meta_m, sessions_m = self._build_meta(
                symbol, "W1", "M", self.provider, 600, "Monthly"
            )
            meta_w, sessions_w = self._build_meta(
                symbol, "D1", "W", self.provider, 3000, "Weekly"
            )
            meta_d, sessions_d = self._build_meta(
                symbol, "H4", "D", self.provider, 5000, "Daily"
            )

            # Build per-TF regimes (V3 pipeline)
            regime_m = build_tf_regime(meta_m, sessions_m or None)
            regime_w = build_tf_regime(meta_w, sessions_w or None)
            regime_d = build_tf_regime(meta_d, sessions_d or None)

            # min_mba_continuity guard — override regime readiness
            for meta, regime in [(meta_m, regime_m), (meta_w, regime_w), (meta_d, regime_d)]:
                if meta and meta.is_ready:
                    if meta.mba_continuity_count < config.min_mba_continuity:
                        regime.is_ready = False
                        regime.ready_direction = None

            # Evaluate V3 signal (balance_aligned + breakout_ready)
            signal_result = evaluate_overall_signal(
                regime_m, regime_w, regime_d,
                require_compression=True,
            )

            # Price data for ATR (reuse daily sessions)
            highs = [s.session_high for s in sessions_d if s.session_high]
            lows = [s.session_low for s in sessions_d if s.session_low]
            closes = [s.close_price for s in sessions_d if s.close_price]
            current_price = closes[-1] if closes else None

            if current_price is None:
                return None

            return {
                "symbol": symbol,
                "signal_result": signal_result,
                "meta_m": meta_m,
                "meta_w": meta_w,
                "meta_d": meta_d,
                "current_price": current_price,
                "highs": highs,
                "lows": lows,
                "closes": closes,
            }
        except Exception as exc:
            logger.error("Error analysing %s: %s", symbol, exc)
            return None

    # ── Entry logic ───────────────────────────────────────────

    def check_entry(
        self, symbol: str, analysis: dict, config: TrendCatcherV2Config,
    ) -> Optional[TrendSignalV2]:
        """Generate entry signal when V3 signal fires."""
        return self.signal_gen.generate_entry_signal(
            symbol=symbol,
            signal_result=analysis["signal_result"],
            current_price=analysis["current_price"],
            highs=analysis["highs"],
            lows=analysis["lows"],
            closes=analysis["closes"],
            atr_period=config.atr_period,
            sl_atr_mult=config.initial_stop_atr_mult,
        )

    # ── Exit logic ────────────────────────────────────────────

    def check_exit(
        self, position: V2Position, config: TrendCatcherV2Config,
    ) -> Optional[str]:
        """Check monthly direction flip (stop-loss is handled by MT5 server-side)."""
        try:
            meta_m, _ = self._build_meta(
                position.symbol, "D1", "M", self.provider, 3000, "Monthly",
            )

            return self.signal_gen.check_exit(
                position_direction=position.direction,
                meta_m=meta_m,
            )
        except Exception as exc:
            logger.error("Error checking exit for %s: %s", position.symbol, exc)
            return None

    # ── Position sizing (same formula as balance scalper) ─────

    @staticmethod
    def _calculate_lot_size(
        symbol: str,
        entry_price: float,
        stop_loss: float,
        risk_usd: float,
    ) -> float:
        """Position size so that SL hit = ``risk_usd`` loss."""
        import MetaTrader5 as mt5

        mt5.initialize()
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.error("No symbol info for %s", symbol)
            return 0.0

        sl_distance = abs(entry_price - stop_loss)
        if sl_distance == 0:
            return 0.0

        tick_size = info.trade_tick_size
        tick_value = info.trade_tick_value
        lot_min = info.volume_min
        lot_max = info.volume_max
        lot_step = info.volume_step

        pip_value_per_lot = (
            tick_value / tick_size if tick_size > 0 else info.trade_contract_size
        )

        lot = risk_usd / (sl_distance * pip_value_per_lot)
        lot = max(lot_min, min(lot_max, lot))
        lot = round(lot / lot_step) * lot_step
        lot = round(lot, 2)
        return lot

    # ── Order execution (uses infra.mt5 directly) ────────────

    def _execute_entry(self, signal: TrendSignalV2, config: TrendCatcherV2Config) -> bool:
        symbol = signal.symbol
        direction = signal.direction

        # Account equity for risk
        acct = mt5_infra.get_account_info()
        equity = acct.equity if acct else 10_000
        risk_usd = equity * config.risk_per_trade_pct / 100.0

        lot = self._calculate_lot_size(
            symbol, signal.entry_price, signal.stop_loss, risk_usd,
        )
        if lot <= 0:
            logger.warning("[%s] lot_size=0, skipping", symbol)
            return False

        side = "buy" if direction == "bullish" else "sell"

        if self.dry_run:
            ticket = int(datetime.now().timestamp())
            logger.info(
                "[DRY] %s %s %.2f lots @ %.5f  SL=%.5f",
                side.upper(), symbol, lot, signal.entry_price, signal.stop_loss,
            )
        else:
            result = mt5_infra.place_order(
                symbol=symbol,
                side=side,
                volume=lot,
                sl=signal.stop_loss,
                comment=f"TCV2-{direction[:1].upper()}",
            )
            if result is None:
                return False
            ticket = result.order
            logger.info("[LIVE] Ticket %d  %s %s %.2f lots", ticket, side.upper(), symbol, lot)

        pos = V2Position(
            symbol=symbol,
            direction=direction,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            entry_time=datetime.now(),
            lot_size=lot,
            ticket=ticket,
        )
        self.active_positions[symbol] = pos
        self.save_state()
        return True

    def _execute_exit(self, symbol: str, reason: str):
        pos = self.active_positions.get(symbol)
        if pos is None:
            return

        if self.dry_run:
            logger.info("[DRY EXIT] %s — %s", symbol, reason)
        else:
            mt5_infra.close_position(pos.ticket, comment=f"TCV2-{reason}")

        del self.active_positions[symbol]

        if reason == "stop_loss":
            config = self._config_for(symbol)
            cd = config.cooldown_days if config else 3
            self.cooldowns[symbol] = datetime.now() + timedelta(days=cd)

        self.save_state()
        logger.info("[CLOSED] %s — %s", symbol, reason)

    # ── Cooldown ──────────────────────────────────────────────

    def _in_cooldown(self, symbol: str) -> bool:
        if symbol in self.cooldowns:
            if datetime.now() < self.cooldowns[symbol]:
                return True
            del self.cooldowns[symbol]
        return False

    # ── Scan / Check loops ────────────────────────────────────

    def scan_for_entries(self):
        logger.info("\n" + "=" * 60)
        logger.info(">> V2 SCANNING FOR ENTRIES …")
        logger.info("=" * 60)

        self.stats = {"scanned": 0, "signals": 0, "executed": 0, "errors": 0}

        for ac in self.asset_classes:
            entry = ASSET_CONFIG.get(ac)
            if not entry:
                continue
            config: TrendCatcherV2Config = entry["config"]
            symbols: List[str] = entry["symbols"]

            for symbol in symbols:
                self.stats["scanned"] += 1

                if len(self.active_positions) >= config.max_positions:
                    logger.info("Max positions (%d) reached", config.max_positions)
                    break

                if symbol in self.active_positions:
                    continue
                if self._in_cooldown(symbol):
                    continue

                try:
                    analysis = self.analyze_symbol(symbol, config)
                    if not analysis:
                        continue

                    signal = self.check_entry(symbol, analysis, config)
                    if signal:
                        self.stats["signals"] += 1
                        logger.info(
                            "[SIGNAL] %s %s @ %.5f  %s [%s]",
                            symbol,
                            signal.direction.upper(),
                            signal.entry_price,
                            signal.signal_result.signal,
                            signal.signal_result.path,
                        )
                        if self._execute_entry(signal, config):
                            self.stats["executed"] += 1
                except Exception as exc:
                    self.stats["errors"] += 1
                    logger.error("Error scanning %s: %s", symbol, exc)

        logger.info(
            "V2 Scan complete: %d scanned, %d signals, %d executed",
            self.stats["scanned"],
            self.stats["signals"],
            self.stats["executed"],
        )
        self.last_scan_time = datetime.now()

    def check_positions(self):
        logger.info("\n" + "-" * 60)
        logger.info(">> V2 CHECKING POSITIONS …")
        logger.info("-" * 60)

        if not self.active_positions:
            logger.info("No active V2 positions")
            return

        to_close: List[tuple] = []
        for symbol, pos in self.active_positions.items():
            config = self._config_for(symbol)
            if not config:
                continue
            reason = self.check_exit(pos, config)
            if reason:
                to_close.append((symbol, reason))
            else:
                logger.info("  %s: %s holding", symbol, pos.direction.upper())

        for symbol, reason in to_close:
            self._execute_exit(symbol, reason)

    # ── Status / reports ──────────────────────────────────────

    def print_status(self):
        acct = mt5_infra.get_account_info()
        print("\n" + "=" * 60)
        print("TREND CATCHER V2 BOT STATUS")
        print("=" * 60)
        if acct:
            print(f"  Balance: ${acct.balance:,.2f}   Equity: ${acct.equity:,.2f}")
        print(f"\n  Positions ({len(self.active_positions)}):")
        for sym, pos in self.active_positions.items():
            days = (datetime.now() - pos.entry_time).days
            print(f"    {sym}: {pos.direction.upper()} @ {pos.entry_price:.5f}  ({days}d)")
        if not self.active_positions:
            print("    (none)")
        total_syms = sum(
            len(ASSET_CONFIG[ac]["symbols"])
            for ac in self.asset_classes if ac in ASSET_CONFIG
        )
        print(f"\n  Watching: {total_syms} symbols across {len(self.asset_classes)} classes")
        if self.last_scan_time:
            print(f"  Last scan: {self.last_scan_time:%Y-%m-%d %H:%M:%S}")
        print("=" * 60 + "\n")

    def save_report(self):
        try:
            report = {
                "version": "V2",
                "date": f"{datetime.now():%Y-%m-%d}",
                "positions": {
                    s: p.to_dict() for s, p in self.active_positions.items()
                },
                "stats": self.stats,
            }
            path = REPORT_DIR / f"v2_daily_{datetime.now():%Y-%m-%d}.json"
            path.write_text(json.dumps(report, indent=2))
            logger.info("Report → %s", path)
        except Exception as exc:
            logger.error("Report save failed: %s", exc)

    # ── Run modes ─────────────────────────────────────────────

    def run_once(self):
        if not self.connect():
            return
        self.load_state()
        self.print_status()
        self.check_positions()
        self.scan_for_entries()
        self.save_report()
        self.print_status()

    def run_loop(self, interval_hours: float = 4):
        logger.info("Starting Trend Catcher V2 Bot …")
        logger.info("  Mode: %s", "DRY RUN" if self.dry_run else "LIVE")
        logger.info("  Interval: %.1fh", interval_hours)

        if not self.connect():
            return
        self.load_state()

        def _job():
            try:
                logger.info("\n[%s] V2 scheduled check …", f"{datetime.now():%H:%M:%S}")
                self.print_status()
                self.check_positions()
                self.scan_for_entries()
                self.save_report()
                self.print_status()
            except Exception as exc:
                logger.error("V2 scheduled job error: %s", exc)

        _job()
        schedule.every(interval_hours).hours.do(_job)

        logger.info("V2 Bot running.  Ctrl+C to stop.")
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("\n[STOPPED] V2 Bot stopped")
            self.save_state()


# ── CLI ──────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Trend Catcher V2 Bot")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--assets", nargs="+")
    ap.add_argument("--interval", type=float, default=4)

    args = ap.parse_args()

    bot = TrendCatcherV2Bot(
        asset_classes=args.assets,
        dry_run=args.dry_run,
    )

    if args.once:
        bot.run_once()
    else:
        bot.run_loop(interval_hours=args.interval)


if __name__ == "__main__":
    main()
