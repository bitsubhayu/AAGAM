"""Durable append-only audit trail writer for model switching decisions (Design Doc §R, §S)."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, Optional, Set

logger = logging.getLogger("aagam.pipeline.versioning.decisions")

VALID_DECISIONS: Set[str] = {
    "PROMOTED",
    "ROLLED_BACK",
    "REJECTED",
    "INSUFFICIENT_DATA",
    "NO_IMPROVEMENT",
    "OPERATIONAL_FAILURE",
    "COOLDOWN",
    "FROZEN",
    "UNFROZEN",
    "NOT_CONFIRMED",
    "ELIGIBLE",
}


def write_decision(
    decision: str,
    reason: str,
    algorithm_version: str = "staged_v2",
    previous_version_id: Optional[int] = None,
    candidate_version_id: Optional[int] = None,
    composite_recent_prev: Optional[float] = None,
    composite_recent_cand: Optional[float] = None,
    composite_seasonal_prev: Optional[float] = None,
    composite_seasonal_cand: Optional[float] = None,
    composite_longterm_prev: Optional[float] = None,
    composite_longterm_cand: Optional[float] = None,
    sample_counts: Optional[Dict[str, Any]] = None,
    evaluation_window_start: Optional[date] = None,
    evaluation_window_end: Optional[date] = None,
    triggered_by: Optional[str] = None,
    pipeline_run_id: Optional[int] = None,
    conn: Optional[Any] = None,
) -> Dict[str, Any]:
    """Writes an immutable record to model_version_decisions.

    If conn is provided, executes an INSERT against PostgreSQL.
    Returns the decision record dict (including database id if inserted).
    """
    if decision not in VALID_DECISIONS:
        raise ValueError(
            f"Invalid decision '{decision}'. Must be one of: {sorted(list(VALID_DECISIONS))}"
        )

    counts_json = json.dumps(sample_counts or {})

    record: Dict[str, Any] = {
        "decision": decision,
        "previous_version_id": previous_version_id,
        "candidate_version_id": candidate_version_id,
        "composite_recent_prev": composite_recent_prev,
        "composite_recent_cand": composite_recent_cand,
        "composite_seasonal_prev": composite_seasonal_prev,
        "composite_seasonal_cand": composite_seasonal_cand,
        "composite_longterm_prev": composite_longterm_prev,
        "composite_longterm_cand": composite_longterm_cand,
        "sample_counts": sample_counts or {},
        "evaluation_window_start": evaluation_window_start.isoformat() if evaluation_window_start else None,
        "evaluation_window_end": evaluation_window_end.isoformat() if evaluation_window_end else None,
        "reason": reason,
        "triggered_by": triggered_by,
        "pipeline_run_id": pipeline_run_id,
        "algorithm_version": algorithm_version,
    }

    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO model_version_decisions (
                        decision, previous_version_id, candidate_version_id,
                        composite_recent_prev, composite_recent_cand,
                        composite_seasonal_prev, composite_seasonal_cand,
                        composite_longterm_prev, composite_longterm_cand,
                        sample_counts, evaluation_window_start, evaluation_window_end,
                        reason, triggered_by, pipeline_run_id, algorithm_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s
                    ) RETURNING id, created_at;
                    """,
                    (
                        decision,
                        previous_version_id,
                        candidate_version_id,
                        composite_recent_prev,
                        composite_recent_cand,
                        composite_seasonal_prev,
                        composite_seasonal_cand,
                        composite_longterm_prev,
                        composite_longterm_cand,
                        counts_json,
                        evaluation_window_start,
                        evaluation_window_end,
                        reason,
                        triggered_by,
                        pipeline_run_id,
                        algorithm_version,
                    ),
                )
                row = cur.fetchone()
                if row:
                    record["id"] = row[0]
                    record["created_at"] = row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1])
        except Exception as e:
            logger.error(f"Failed to insert decision row into model_version_decisions: {e}")
            raise

    logger.info(
        f"ModelVersionDecision: decision={decision} candidate={candidate_version_id} "
        f"prev={previous_version_id} reason={reason}"
    )

    return record
