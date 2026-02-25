from dataclasses import dataclass, field
from enum import Enum
from typing import List

class VAContext(Enum):
    """Relationship of Current Value Area relative to Previous."""
    HIGHER = "HIGHER"                # Higher Value (no overlap)
    LOWER = "LOWER"                  # Lower Value (no overlap)
    OVERLAP_HIGHER = "OVERLAP_HIGHER"# Overlap but higher center
    OVERLAP_LOWER = "OVERLAP_LOWER"  # Overlap but lower center
    INSIDE = "INSIDE"                # Completely inside previous VA
    OUTSIDE = "OUTSIDE"              # Engulfing previous VA
    UNCHANGED = "UNCHANGED"          # Nearly identical

class ActivityType(Enum):
    """Type of market activity based on Context."""
    INITIATING_BUYING = "INITIATING_BUYING"    # Trend continuation UP
    INITIATING_SELLING = "INITIATING_SELLING"  # Trend continuation DOWN
    RESPONSIVE_BUYING = "RESPONSIVE_BUYING"    # Counter-trend buying (returning to value)
    RESPONSIVE_SELLING = "RESPONSIVE_SELLING"  # Counter-trend selling (returning to value)
    ROTATIONAL = "ROTATIONAL"                  # Two-way auction with no clear control
    UNCLEAR = "UNCLEAR"

class Control(Enum):
    """Who is in control?"""
    BUYERS = "BUYERS"
    SELLERS = "SELLERS"
    NEUTRAL = "NEUTRAL"
    CONFLICT = "CONFLICT"  # Both strong buyers and sellers present

@dataclass
class MarketContext:
    """Captured context of the current session relative to history."""
    
    # Value Area analysis
    va_relationship: VAContext
    overlap_pct: float          # 0.0 to 1.0
    va_expanding: bool          # Current VA range > Previous VA range
    
    # Detailed Context
    trend_context: str          # "up", "down", "neutral" (simplified from VAContext)
    
    # Activity & Control
    activity: ActivityType
    control: Control
    
    # Specific signals detected
    signals: List[str] = field(default_factory=list)
    
    # Confidence in analysis (0.0 - 1.0)
    confidence: float = 1.0
    
    def summary(self) -> str:
        """Human readable summary."""
        return f"[{self.va_relationship.value}] {self.activity.value} ({self.control.value})"
