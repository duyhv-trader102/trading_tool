"""
Signal Diff — Compare today's READY signals with the previous scan day.

Highlights:
  NEW     — symbol just became READY (was not READY yesterday)
  FLIPPED — symbol was READY in opposite direction (e.g. BULL -> BEAR)
  GONE    — symbol was READY yesterday but is NOT READY today
  HELD    — same READY signal as yesterday (no change)

Usage:
    from infra.signal_diff import SignalDiff

    diff = SignalDiff()
    report = diff.compare()          # today vs previous day
    diff.print_diff(report)          # pretty-print to console

CLI:
    python -m infra.signal_diff                # show today's signals + diff
    python -m infra.signal_diff --watch 60     # refresh every 60s, alert on new
    python -m infra.signal_diff --market BINANCE
    python -m infra.signal_diff --bullish
    python -m infra.signal_diff --new-only     # only show NEW / FLIPPED
    python -m infra.signal_diff --history      # show last 7 days summary
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Any

from infra.signal_logger import SignalLogger


@dataclass
class DiffEntry:
    """One row in the diff report."""
    market: str
    symbol: str
    status: str                # NEW, GONE, FLIPPED, HELD
    today_signal: Optional[str] = None
    prev_signal: Optional[str] = None
    entry_price: Optional[float] = None
    detail: str = ""           # extra context (e.g. ready reason)


@dataclass
class DiffReport:
    """Full diff between two scan days."""
    today_date: str
    prev_date: str
    new: List[DiffEntry] = field(default_factory=list)
    gone: List[DiffEntry] = field(default_factory=list)
    flipped: List[DiffEntry] = field(default_factory=list)
    held: List[DiffEntry] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.new or self.gone or self.flipped)


class SignalDiff:
    """Compare READY signals across two scan dates."""

    def __init__(self, logger: SignalLogger | None = None):
        self.logger = logger or SignalLogger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare(
        self,
        today_str: str | None = None,
        prev_str: str | None = None,
    ) -> DiffReport:
        """Compare signals for *today_str* vs *prev_str*.

        If *prev_str* is None, automatically picks the most recent date
        before *today_str* that has a log file.
        """
        today_str = today_str or date.today().isoformat()
        if prev_str is None:
            prev_str = self._find_previous_date(today_str)

        today_data = self._ready_map(today_str)
        prev_data = self._ready_map(prev_str) if prev_str else {}

        report = DiffReport(today_date=today_str, prev_date=prev_str or "(none)")

        all_keys = set(today_data.keys()) | set(prev_data.keys())

        for key in sorted(all_keys):
            in_today = key in today_data
            in_prev = key in prev_data

            if in_today and not in_prev:
                # NEW signal
                e = today_data[key]
                report.new.append(DiffEntry(
                    market=e["market"], symbol=e["symbol"],
                    status="NEW", today_signal=e["signal"],
                    entry_price=e.get("entry_price"),
                    detail=self._ready_detail(e),
                ))

            elif not in_today and in_prev:
                # GONE — was READY yesterday, not today
                e = prev_data[key]
                report.gone.append(DiffEntry(
                    market=e["market"], symbol=e["symbol"],
                    status="GONE", prev_signal=e["signal"],
                ))

            else:
                # Both days — check for direction flip
                t = today_data[key]
                p = prev_data[key]
                t_dir = self._direction(t["signal"])
                p_dir = self._direction(p["signal"])

                if t_dir != p_dir:
                    report.flipped.append(DiffEntry(
                        market=t["market"], symbol=t["symbol"],
                        status="FLIPPED",
                        today_signal=t["signal"], prev_signal=p["signal"],
                        entry_price=t.get("entry_price"),
                        detail=f"{p_dir} → {t_dir}",
                    ))
                else:
                    report.held.append(DiffEntry(
                        market=t["market"], symbol=t["symbol"],
                        status="HELD", today_signal=t["signal"],
                    ))

        return report

    # ------------------------------------------------------------------
    # Console display
    # ------------------------------------------------------------------

    def print_diff(self, report: DiffReport) -> None:
        """Pretty-print the diff report to stdout."""
        w = 70
        print(f"\n{'='*w}")
        print(f"  SIGNAL DIFF — {report.today_date} vs {report.prev_date}")
        print(f"{'='*w}")

        if not report.has_changes:
            print(f"  No changes — {len(report.held)} signal(s) unchanged.")
            print(f"{'='*w}\n")
            return

        # ── NEW ──
        if report.new:
            print(f"\n  NEW SIGNALS ({len(report.new)})")
            print(f"  {'-'*60}")
            for e in sorted(report.new, key=lambda x: (x.market, x.symbol)):
                price = f"  @ {e.entry_price:.4f}" if e.entry_price else ""
                print(f"    ++ {e.symbol:<14} [{e.market}]  {e.today_signal}{price}")
                if e.detail:
                    print(f"       {e.detail}")

        # ── FLIPPED ──
        if report.flipped:
            print(f"\n  FLIPPED SIGNALS ({len(report.flipped)})")
            print(f"  {'-'*60}")
            for e in sorted(report.flipped, key=lambda x: (x.market, x.symbol)):
                print(f"    ~~ {e.symbol:<14} [{e.market}]  {e.prev_signal} --> {e.today_signal}")
                if e.detail:
                    print(f"       ({e.detail})")

        # ── GONE ──
        if report.gone:
            print(f"\n  GONE SIGNALS ({len(report.gone)})")
            print(f"  {'-'*60}")
            for e in sorted(report.gone, key=lambda x: (x.market, x.symbol)):
                print(f"    -- {e.symbol:<14} [{e.market}]  was {e.prev_signal}")

        # ── Summary line ──
        held_count = len(report.held)
        print(f"\n  Summary: +{len(report.new)} new, ~{len(report.flipped)} flipped, "
              f"-{len(report.gone)} gone, {held_count} held")
        print(f"{'='*w}\n")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ready_map(self, date_str: str) -> Dict[str, Dict[str, Any]]:
        """Return {MARKET:SYMBOL → entry} for READY signals on *date_str*."""
        signals = self.logger.get_ready_signals(date_str)
        return {f"{s['market']}:{s['symbol']}": s for s in signals}

    def _find_previous_date(self, ref_date: str) -> str | None:
        """Find the most recent log date strictly before *ref_date*."""
        dates = self.logger.list_dates()
        earlier = [d for d in dates if d < ref_date]
        return earlier[-1] if earlier else None

    @staticmethod
    def _direction(signal: str | None) -> str:
        if not signal:
            return "none"
        sig = signal.upper()
        if "BULLISH" in sig:
            return "BULLISH"
        if "BEARISH" in sig:
            return "BEARISH"
        return "unknown"

    @staticmethod
    def _ready_detail(entry: Dict[str, Any]) -> str:
        """Build a concise detail string from monthly/weekly ready reasons."""
        parts: list[str] = []
        for pfx, label in [("m", "M"), ("w", "W")]:
            if entry.get(f"{pfx}_is_ready"):
                d = entry.get(f"{pfx}_ready_direction") or "?"
                reason = entry.get(f"{pfx}_ready_reason") or ""
                short = ""
                if "[" in reason and "]" in reason:
                    short = reason[reason.index("[") + 1: reason.index("]")]
                tag = f"{label}:READY({'Bull' if d == 'bullish' else 'Bear'})"
                if short:
                    tag += f" [{short}]"
                parts.append(tag)
        return " | ".join(parts)
