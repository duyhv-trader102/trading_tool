"""
Analytic Layer - Applies core primitives to identify market states and signals.
This layer is organized into domain-specific sub-packages:

- tpo_regime: Session-level schema (RegimeResult, RegimeFeatures)
- tpo_mba:    Multi-session Macro Balance Area detection & tracking
- ob_analysis: Order Block discovery and mitigation tracking
- tpo_momentum: Exhaustion and institutional flow analysis
- tpo_confluence: Multi-timeframe alignment and final decision logic
"""

# --- 1. Regime Schema (dataclasses only — classifier removed) ---
from .tpo_regime.schema import RegimeResult, RegimeFeatures

# --- 2. Macro Balance Area (Structural Context) ---
from .tpo_mba.detector import (
    find_last_directional_move,
    find_first_balance_move,
    is_session_closed,
)
from .tpo_mba.schema import (
    MacroBalanceArea, 
    MBAUnit,
    MBAMetadata,
    MBAReadiness,
)
from .tpo_mba.tracker import (
    track_mba_evolution,
    get_current_mba,
    detect_mba_break,
    evaluate_mba_readiness,
    mba_summary,
    build_mba_context,
)

# --- 3. Order Blocks & Execution context ---
from .ob_analysis.ob_mitigation import check_mitigation_type

# --- 4. Confluence & Direction (Alignment) ---
from .tpo_confluence.tpo_alignment import (
    detect_direction, DirectionSignal,
    build_topdown_conclusion, TopDownConclusion, TimeframeSummary,
)
