"""AAGAM Alert Events & Lifecycle Management Package (PRD §6.10, §11.1, Tech Stack §12)."""

from pipeline.events.group import AlertEventRecord, group_alerts_into_events
from pipeline.events.lifecycle_state import (
    SEVERITY_RANKS,
    compute_lifecycle_states,
    update_event_cancellations_and_expiries,
)
from pipeline.events.verify import (
    batch_verify_events,
    evaluate_event_outcome,
    get_hazard_threshold,
)

__all__ = [
    "AlertEventRecord",
    "group_alerts_into_events",
    "compute_lifecycle_states",
    "update_event_cancellations_and_expiries",
    "SEVERITY_RANKS",
    "evaluate_event_outcome",
    "batch_verify_events",
    "get_hazard_threshold",
]

