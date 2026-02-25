from dataclasses import dataclass, field
from typing import List, Optional, Union
from core.tpo import TPOResult, SessionType, DistributionInfo
from analytic.tpo_context.schema import MarketContext

@dataclass
class RegimeFeatures:
    """Extracted features for regime classification."""
    
    # POC analysis
    poc: float
    poc_prev: Optional[float]
    poc_shift: float  # Absolute change
    poc_shift_pct: float  # Percentage of range
    
    # Value Area analysis
    va_high: float
    va_low: float
    va_range: float
    va_overlap_pct: float  # Overlap with previous session (0-1)
    va_expanding: bool  # VA wider than previous
    
    # Single prints / Imbalance indicators
    single_print_count: int
    single_print_pct: float  # % of total range that is single prints
    minus_dev_count: int
    
    # Unfair extremes
    has_unfair_high: bool
    has_unfair_low: bool
    
    # Initial Balance
    ib_range: float
    ib_extension_up: float  # How far above IB high
    ib_extension_down: float  # How far below IB low
    day_type: Union[SessionType, str]  # SessionType enum (or str for backwards compat)
    
    # Responsive participation
    responsive_high: bool  # Unfair high exists but close < VAH (rejection)
    responsive_low: bool   # Unfair low exists but close > VAL (rejection)
    has_range_extension: bool  # Extended beyond IB (responsive activity)
    responsive_buying_in_VA: bool 
    responsive_selling_in_VA: bool 
    
    # Session metrics
    session_range: float
    close_in_va: bool  # Close within Value Area
    total_tpo: int

    tpo_above_poc: int  # TPO rows (2+) above POC
    tpo_below_poc: int  # TPO rows (2+) below POC
    
    # Conflict/Signal tracking
    conflict: bool = False
    initiating_signals: List[str] = field(default_factory=list)
    responsive_signals: List[str] = field(default_factory=list)
    close_price: float = 0.0  # Session close price
    
    # Market Context (Replaces old ResponsiveParticipation)
    context: Optional[MarketContext] = None
    
    # Distribution shape
    distribution: Optional[DistributionInfo] = None
    
    # Context from prior sessions
    prior_direction: Optional[str] = None  # "bullish", "bearish", None (from last 2 sessions)


@dataclass  
class RegimeResult:
    """Output of regime classification."""
    
    regime: str  # "BALANCE" or "IMBALANCE"
    confidence: float  # 0-1
    direction: Optional[str]  # "bullish", "bearish", None (for balance)
    
    # Key levels
    control_price: float  # POC
    range_high: float  # VAH or session high
    range_low: float  # VAL or session low
    
    # Features used
    features: RegimeFeatures
    rules_triggered: List[str] = field(default_factory=list)
    
    # Distribution
    ready_to_move: bool = False  # 3-1-3 without minus dev
    
    # For learning
    uncertain_because: Optional[str] = None
