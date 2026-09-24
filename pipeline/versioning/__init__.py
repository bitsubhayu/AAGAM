"""AAGAM — Automated Model-Version Switching and Lifecycle Management.

Package components:
- config: Configuration loader for model_switching.yaml
- floors: Minimum evidence and confidence floor evaluators (5 regions, min strata, sample size)
- scoring: Normalized, multi-metric composite scoring engine (MAE, RMSE, Bias, CSI)
- margin: Formulation B operational promotion-risk margin and regional non-regression guardrail
- state_machine: Multi-stage candidate lifecycle engine (draft -> candidate -> evaluating -> eligible -> shadow -> canary -> active)
- rollback: Automatic rollback triggers, cooldowns, and circuit breakers
- decisions: Durable append-only audit trail logger
"""

from pipeline.versioning.canary import (
    assign_canary_locations,
    get_active_canary_assignments,
    release_canary_assignments,
    select_canary_locations,
)
from pipeline.versioning.config import ModelSwitchingConfig, load_model_switching_config
from pipeline.versioning.decisions import VALID_DECISIONS, write_decision
from pipeline.versioning.floors import (
    WindowFloorsResult,
    evaluate_window_floors,
    validate_evaluation_window_temporal_safety,
)
from pipeline.versioning.lifecycle import (
    get_active_model_version,
    get_candidates_in_flight,
    load_automation_state,
    run_versioning_pipeline_step,
)
from pipeline.versioning.margin import MarginResult, calculate_required_margin, evaluate_promotion_margin
from pipeline.versioning.rollback import (
    RollbackResult,
    evaluate_active_rollback_triggers,
    evaluate_canary_rollback_triggers,
    evaluate_rollback_triggers,
    execute_rollback,
)
from pipeline.versioning.scoring import WindowEvaluation, compute_composite_score, compute_stratum_score
from pipeline.versioning.state_machine import (
    VALID_STATES,
    AutomationState,
    CandidateState,
    StateMachineResult,
    advance_candidate_state,
    validate_state_invariants,
)

__all__ = [
    "load_model_switching_config",
    "ModelSwitchingConfig",
    "evaluate_window_floors",
    "validate_evaluation_window_temporal_safety",
    "WindowFloorsResult",
    "compute_composite_score",
    "compute_stratum_score",
    "WindowEvaluation",
    "calculate_required_margin",
    "evaluate_promotion_margin",
    "MarginResult",
    "CandidateState",
    "AutomationState",
    "VALID_STATES",
    "VALID_DECISIONS",
    "advance_candidate_state",
    "validate_state_invariants",
    "StateMachineResult",
    "evaluate_rollback_triggers",
    "evaluate_active_rollback_triggers",
    "evaluate_canary_rollback_triggers",
    "execute_rollback",
    "RollbackResult",
    "write_decision",
    "select_canary_locations",
    "assign_canary_locations",
    "release_canary_assignments",
    "get_active_canary_assignments",
    "run_versioning_pipeline_step",
    "load_automation_state",
    "get_active_model_version",
    "get_candidates_in_flight",
]

