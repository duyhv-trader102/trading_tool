"""Trend Catcher V2 -- Signal Generation
=======================================

Core signal logic for the top-down alignment strategy.

Entry Condition
---------------
Wait for MBA readiness confluence across 3 timeframes::

    1M session ready  ⇒  direction (anchor)
    1W session ready  +  same direction as 1M
    1D session ready  +  same direction as 1W  ⇒  ENTER

Each timeframe's readiness comes from ``build_mba_context()``
(``analytic.tpo_mba.tracker``) which returns ``MBAMetadata``
with ``.is_ready`` and ``.ready_direction``.

The 3-1-3 readiness direction uses VA dominance (buying vs selling
TPO counts) confirmed by close price relative to h_limit/l_limit.

Exit Condition
--------------
- Monthly direction flips (ready in opposite direction)  →  close
- Stop-loss hit (checked externally with intraday H/L)   →  close

Classes
-------
- ``AlignmentState``    : (from ``analytic.tpo_mba.alignment``)
- ``TrendSignalV2``     : Entry signal dataclass
- ``SignalGeneratorV2`` : Builds alignment, generates signals, checks exits
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List
from datetime import datetime

from analytic.tpo_mba.schema import MBAMetadata
from analytic.tpo_mba.alignment import (
    AlignmentState, build_alignment,
    TFRegime, SignalResult, build_tf_regime, evaluate_overall_signal,
)
from EA.shared.indicators import calculate_atr


@dataclass
class TrendSignalV2:
    """A trading signal from the Trend Catcher V2/V3 strategy."""
    symbol: str
    direction: str               # "bullish" or "bearish"
    entry_price: float
    stop_loss: float
    atr: float
    timestamp: datetime
    signal_result: SignalResult
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "atr": self.atr,
            "timestamp": self.timestamp.isoformat(),
            "signal": self.signal_result.signal,
            "signal_path": self.signal_result.path,
            "reason": self.reason,
        }


# ──────────────────────────────────────────────────────────────
# Signal generator
# ──────────────────────────────────────────────────────────────

class SignalGeneratorV2:
    """
    V2 signal generator — top-down alignment using MBA readiness.

    Entry:
        All 3 TFs ready in same direction  →  BUY / SELL
    Exit:
        Monthly direction flips  or  fixed stop-loss hit.
    """

    # ── Alignment ─────────────────────────────────────────────

    @staticmethod
    def build_alignment(
        meta_m: Optional[MBAMetadata],
        meta_w: Optional[MBAMetadata],
        meta_d: Optional[MBAMetadata] = None,
        *,
        require_compression: bool = False,
    ) -> AlignmentState:
        """Delegate to shared ``analytic.tpo_mba.alignment.build_alignment``.

        Kept as a static method for backward compatibility so callers
        can still do ``signal_gen.build_alignment(m, w, d)``.

        .. deprecated::
            Prefer ``evaluate_signal()`` which uses the centralised
            ``TFRegime`` + ``evaluate_overall_signal()`` pipeline.
        """
        return build_alignment(
            meta_m, meta_w, meta_d,
            require_compression=require_compression,
        )

    # ── Centralised signal evaluation (V3) ────────────────────

    @staticmethod
    def evaluate_signal(
        meta_m: Optional[MBAMetadata],
        meta_w: Optional[MBAMetadata],
        meta_d: Optional[MBAMetadata] = None,
        *,
        sessions_m: Optional[list] = None,
        sessions_w: Optional[list] = None,
        sessions_d: Optional[list] = None,
        allow_breakout_ready: bool = True,
        require_compression: bool = False,
    ) -> SignalResult:
        """Evaluate multi-TF signal using the centralised pipeline.

        Builds ``TFRegime`` for each timeframe, then delegates to
        ``evaluate_overall_signal()`` — the single source of truth for
        signal logic (Path 1: balance aligned, Path 2: breakout ready).

        When ``sessions_*`` are provided, BREAKOUT detection is enabled.
        Otherwise falls back to pure readiness alignment (equivalent to
        the old ``AlignmentState.is_aligned`` for Path 1).

        Args:
            meta_m / meta_w / meta_d: ``MBAMetadata`` per timeframe.
            sessions_m / sessions_w / sessions_d: TPO session lists
                (including open sessions) for breakout detection.
            allow_breakout_ready: Enable Path 2 (default ``True``).
            require_compression: V2.1 compression gate.

        Returns:
            ``SignalResult`` with signal text, direction, and path.
        """
        regime_m = build_tf_regime(meta_m, sessions_m)
        regime_w = build_tf_regime(meta_w, sessions_w)
        regime_d = build_tf_regime(meta_d, sessions_d) if meta_d is not None else None

        return evaluate_overall_signal(
            regime_m, regime_w, regime_d,
            allow_breakout_ready=allow_breakout_ready,
            require_compression=require_compression,
        )

    # ── Entry signal ──────────────────────────────────────────

    def generate_entry_signal(
        self,
        symbol: str,
        signal_result: SignalResult,
        current_price: float,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        atr_period: int = 14,
        sl_atr_mult: float = 3.0,
    ) -> Optional[TrendSignalV2]:
        """
        Produce an entry signal when V3 signal is confirmed.

        Returns TrendSignalV2 if signal has a direction, else None.
        """
        if not signal_result.direction:
            return None

        direction = signal_result.direction
        atr = calculate_atr(highs, lows, closes, atr_period)
        if atr <= 0:
            return None

        if direction == "bullish":
            stop_loss = current_price - sl_atr_mult * atr
        else:
            stop_loss = current_price + sl_atr_mult * atr

        return TrendSignalV2(
            symbol=symbol,
            direction=direction,
            entry_price=current_price,
            stop_loss=stop_loss,
            atr=atr,
            timestamp=datetime.now(),
            signal_result=signal_result,
            reason=signal_result.signal,
        )

    # ── Exit check ────────────────────────────────────────────

    @staticmethod
    def check_exit(
        position_direction: str,
        meta_m: Optional[MBAMetadata],
    ) -> Optional[str]:
        """
        V2 exit condition:
            Monthly direction flips (ready in opposite direction).

        Note: Stop-loss is checked separately with intraday high/low
        in the backtest/bot loop (before this method is called).

        Returns exit reason string, or None.
        """
        if meta_m and meta_m.is_ready and meta_m.ready_direction:
            opposing = "bearish" if position_direction == "bullish" else "bullish"
            if meta_m.ready_direction == opposing:
                return "direction_flip"

        return None
