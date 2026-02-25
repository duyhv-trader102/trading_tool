from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from core.tpo import TPOResult

@dataclass
class MBAUnit:
    """A single MBA unit - a balanced box within a sequence.
    
    Only closed sessions can form an MBA unit.
    An unclosed session's VA/POC is not finalised yet.
    """
    area_high: float
    area_low: float
    mother_index: int
    mother_start: datetime
    source: str
    is_closed: bool = True          # must always be True; kept for validation
    end_index: Optional[int] = None
    end_start: Optional[datetime] = None

@dataclass
class MacroBalanceArea:
    """Result of macro balance area detection (with history)."""
    area_high: float
    area_low: float
    source: str
    mother_session: TPOResult
    mother_index: int
    imbalance_session: Optional[TPOResult] = None
    imbalance_index: Optional[int] = None
    imbalance_direction: Optional[str] = None
    is_structural: bool = False
    outer_high: Optional[float] = None
    outer_low: Optional[float] = None
    all_units: List[MBAUnit] = field(default_factory=list)

    @property
    def area_range(self) -> float:
        return self.area_high - self.area_low
    
    @property
    def area_mid(self) -> float:
        return (self.area_high + self.area_low) / 2

@dataclass
class MBAReadiness:
    """Result of MBA readiness evaluation for new beginning."""
    is_ready: bool = False
    ready_direction: Optional[str] = None          # bullish / bearish
    signals: List[str] = field(default_factory=list)  # e.g. ["normal_session", "3-1-3_ready"]
    trigger_session_index: Optional[int] = None    # index of last readiness session
    compression_ratio: Optional[float] = None      # VA_trigger / MBA_range (<0.5 = compressed)
    conflict_sessions: int = 0                     # how many sessions had conflict

    def summary(self) -> str:
        if not self.is_ready:
            return "NOT READY"
        sig = ", ".join(self.signals)
        cr = f" compression={self.compression_ratio:.0%}" if self.compression_ratio is not None else ""
        return f"READY {self.ready_direction} [{sig}]{cr} @#{self.trigger_session_index}"


@dataclass
class MBAMetadata:
    """
    Aggregated metadata for market scanning.
    Combines balance area detection with compression/sweep analysis.
    """
    symbol: str
    timeframe: str
    last_session_time: datetime
    
    # MBA status
    current_mba: Optional[MacroBalanceArea] = None
    last_closed_session: Optional[TPOResult] = None # Legacy
    
    # Reversal signals for scanner
    is_compression: bool = False
    is_sweep: bool = False
    
    # Readiness for move
    is_ready: bool = False
    ready_direction: Optional[str] = None
    ready_for_new_beginning: bool = False # Legacy
    ready_reason: str = "" # Legacy
    trigger_session_index: Optional[int] = None
    
    # Continuity
    mba_continuity_count: int = 0
    compression_count: int = 0
    
    # Analysis results
    direction_signal: Optional[object] = None # Will be DirectionSignal
    
    @property
    def last_closed_is_compression(self) -> bool:
        return self.is_compression

    @property
    def last_closed_is_sweep(self) -> bool:
        return self.is_sweep
    
    @property
    def mba(self) -> Optional[MacroBalanceArea]:
        """Legacy access to current_mba."""
        return self.current_mba

    @property
    def has_mba(self) -> bool:
        return self.current_mba is not None
    
    @property
    def reversal_alert(self) -> bool:
        """True when MBA exists AND last closed session is compression/sweep."""
        return self.has_mba and (self.is_compression or self.is_sweep)

    def summary_line(self, price_fmt: str = ".2f", tf_regime=None) -> str:
        """One-line summary for console / scanner output.

        Parameters
        ----------
        tf_regime : TFRegime, optional
            When supplied, status/readiness is derived from the regime
            (BREAKOUT / IN BALANCE / READY) instead of raw metadata flags.
            This ensures consistency with the scanner.
        """
        mba_str = "No MBA"
        if self.current_mba:
            mba_str = f"MBA({self.current_mba.area_low:{price_fmt}}-{self.current_mba.area_high:{price_fmt}})"

        if tf_regime is not None:
            # Derive status from TFRegime (same source of truth as scanner)
            if tf_regime.is_ready:
                status = f"READY({tf_regime.ready_direction})"
            elif tf_regime.status == "BREAKOUT":
                status = f"BREAKOUT({tf_regime.trend})"
            elif self.reversal_alert:
                sig = "COMPRESSION" if self.is_compression else "SWEEP"
                status = f"ALERT({sig})"
            else:
                status = f"IN BALANCE({tf_regime.trend})"
        else:
            # Fallback: derive from raw metadata (legacy callers)
            status = "RESERVED"
            if self.is_ready:
                status = f"READY({self.ready_direction})"
            elif self.reversal_alert:
                sig = "COMPRESSION" if self.is_compression else "SWEEP"
                status = f"ALERT({sig})"
            
        return f"{self.symbol:<10} {self.timeframe:<8} {mba_str:<25} {status:<15} Units:{len(self.current_mba.all_units) if self.current_mba else 0}"
