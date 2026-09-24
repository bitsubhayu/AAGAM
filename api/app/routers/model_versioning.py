"""Model versioning, lifecycle, and automation management API endpoints.

Authoritative source:
- AAGAM_MODEL_VERSIONING_DESIGN.md §S, §T
- AAGAM_MODEL_VERSIONING_ANTIGRAVITY_SPEC.md Phase 4
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn
from core.config import settings
from core.schemas import (
    AutomationStateResponse,
    DisableCandidateRequest,
    ForceLastKnownGoodRequest,
    FreezeRequest,
    ModelVersionDecisionItem,
    ModelVersionEvaluationItem,
    ModelVersionSummary,
    UnfreezeRequest,
)

logger = logging.getLogger("aagam.api.model_versioning")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Model Versioning"])


def _format_iso(dt: Any) -> Optional[str]:
    """Formats datetime or date object to ISO-8601 string safely."""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _parse_json(val: Any) -> Dict[str, Any]:
    """Parses JSONB values that may be returned as strings or dicts by asyncpg."""
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return {}


# ==============================================================================
# Public Endpoints (require_role("public"))
# ==============================================================================

@router.get("/models/active", response_model=ModelVersionSummary)
async def get_active_model(
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> ModelVersionSummary:
    """Returns the currently active model version and its most recent evaluation summary.

    Authoritative source: Design Doc §T
    """
    row = await conn.fetchrow(
        """
        SELECT id, status, algorithm_type, evaluation_policy, is_active, parent_version_id,
               created_at, activated_at, deactivated_at, created_by
        FROM model_versions
        WHERE is_active = true
        ORDER BY id DESC
        LIMIT 1
        """
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NO_ACTIVE_MODEL",
                "message": "No active model version currently configured.",
                "retry_after": None,
            },
        )

    # Fetch most recent evaluation if available
    eval_row = await conn.fetchrow(
        """
        SELECT id, version_id, pipeline_run_id, window_type, window_start, window_end,
               composite_score, strata_included, strata_excluded, regions_covered,
               lead_days_covered, sample_counts, metrics_detail, computed_at
        FROM model_version_evaluations
        WHERE version_id = $1
        ORDER BY computed_at DESC
        LIMIT 1
        """,
        row["id"],
    )

    recent_eval = None
    if eval_row:
        recent_eval = {
            "id": eval_row["id"],
            "version_id": eval_row["version_id"],
            "pipeline_run_id": eval_row["pipeline_run_id"],
            "window_type": eval_row["window_type"],
            "window_start": _format_iso(eval_row["window_start"]),
            "window_end": _format_iso(eval_row["window_end"]),
            "composite_score": eval_row["composite_score"],
            "strata_included": eval_row["strata_included"],
            "strata_excluded": eval_row["strata_excluded"],
            "regions_covered": eval_row.get("regions_covered", 0),
            "locations_covered": eval_row.get("locations_covered"),
            "lead_days_covered": eval_row["lead_days_covered"],
            "sample_counts": _parse_json(eval_row["sample_counts"]),
            "metrics_detail": _parse_json(eval_row["metrics_detail"]),
            "computed_at": _format_iso(eval_row["computed_at"]),
        }

    return ModelVersionSummary(
        id=row["id"],
        status=row["status"],
        algorithm_type=row["algorithm_type"],
        evaluation_policy=row["evaluation_policy"],
        is_active=row["is_active"],
        parent_version_id=row["parent_version_id"],
        created_at=_format_iso(row["created_at"]) or "",
        activated_at=_format_iso(row["activated_at"]),
        deactivated_at=_format_iso(row["deactivated_at"]),
        created_by=row["created_by"],
        recent_evaluation=recent_eval,
    )


@router.get("/models/versions", response_model=List[ModelVersionSummary])
async def list_model_versions(
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> List[ModelVersionSummary]:
    """Returns list of all model versions with lifecycle metadata.

    Authoritative source: Design Doc §T
    """
    rows = await conn.fetch(
        """
        SELECT id, status, algorithm_type, evaluation_policy, is_active, parent_version_id,
               created_at, activated_at, deactivated_at, created_by
        FROM model_versions
        ORDER BY id DESC
        """
    )
    return [
        ModelVersionSummary(
            id=r["id"],
            status=r["status"],
            algorithm_type=r["algorithm_type"],
            evaluation_policy=r["evaluation_policy"],
            is_active=r["is_active"],
            parent_version_id=r["parent_version_id"],
            created_at=_format_iso(r["created_at"]) or "",
            activated_at=_format_iso(r["activated_at"]),
            deactivated_at=_format_iso(r["deactivated_at"]),
            created_by=r["created_by"],
            recent_evaluation=None,
        )
        for r in rows
    ]


@router.get("/models/versions/{id}/evaluations", response_model=List[ModelVersionEvaluationItem])
async def get_model_evaluations(
    id: int = Path(..., description="ID of the model version"),
    window_type: Optional[str] = Query(None, description="Optional window type filter (recent, seasonal, longterm)"),
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> List[ModelVersionEvaluationItem]:
    """Returns stratified evaluation records for a specific model version.

    Authoritative source: Design Doc §S, §T
    """
    version_row = await conn.fetchrow("SELECT id FROM model_versions WHERE id = $1", id)
    if not version_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "MODEL_VERSION_NOT_FOUND",
                "message": f"Model version {id} does not exist.",
                "retry_after": None,
            },
        )

    if window_type:
        rows = await conn.fetch(
            """
            SELECT id, version_id, pipeline_run_id, window_type, window_start, window_end,
                   composite_score, strata_included, strata_excluded, regions_covered,
                   lead_days_covered, sample_counts, metrics_detail, computed_at
            FROM model_version_evaluations
            WHERE version_id = $1 AND window_type = $2
            ORDER BY computed_at DESC, id DESC
            """,
            id,
            window_type,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, version_id, pipeline_run_id, window_type, window_start, window_end,
                   composite_score, strata_included, strata_excluded, regions_covered,
                   lead_days_covered, sample_counts, metrics_detail, computed_at
            FROM model_version_evaluations
            WHERE version_id = $1
            ORDER BY computed_at DESC, id DESC
            """,
            id,
        )

    return [
        ModelVersionEvaluationItem(
            id=r["id"],
            version_id=r["version_id"],
            pipeline_run_id=r["pipeline_run_id"],
            window_type=r["window_type"],
            window_start=_format_iso(r["window_start"]) or "",
            window_end=_format_iso(r["window_end"]) or "",
            composite_score=r["composite_score"],
            strata_included=r["strata_included"],
            strata_excluded=r["strata_excluded"],
            regions_covered=r.get("regions_covered", 0),
            locations_covered=r.get("locations_covered"),
            lead_days_covered=r["lead_days_covered"],
            sample_counts=_parse_json(r["sample_counts"]),
            metrics_detail=_parse_json(r["metrics_detail"]),
            computed_at=_format_iso(r["computed_at"]) or "",
        )
        for r in rows
    ]


@router.get("/models/decisions", response_model=List[ModelVersionDecisionItem])
async def list_model_decisions(
    limit: int = Query(50, ge=1, le=200, description="Number of decision items to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    candidate_version_id: Optional[int] = Query(None, description="Optional candidate version filter"),
    decision: Optional[str] = Query(None, description="Optional decision type filter"),
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> List[ModelVersionDecisionItem]:
    """Returns paginated model version decision audit trail.

    Authoritative source: Design Doc §R, §S, §T
    """
    conditions = []
    params: List[Any] = []

    if candidate_version_id is not None:
        params.append(candidate_version_id)
        conditions.append(f"candidate_version_id = ${len(params)}")

    if decision is not None:
        params.append(decision)
        conditions.append(f"decision = ${len(params)}")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    params.append(limit)
    limit_clause = f"LIMIT ${len(params)}"
    params.append(offset)
    offset_clause = f"OFFSET ${len(params)}"

    sql = f"""
        SELECT id, decision, previous_version_id, candidate_version_id,
               composite_recent_prev, composite_recent_cand,
               composite_seasonal_prev, composite_seasonal_cand,
               composite_longterm_prev, composite_longterm_cand,
               sample_counts, evaluation_window_start, evaluation_window_end,
               reason, triggered_by, pipeline_run_id, algorithm_version, created_at
        FROM model_version_decisions
        {where_clause}
        ORDER BY created_at DESC, id DESC
        {limit_clause} {offset_clause}
    """
    rows = await conn.fetch(sql, *params)

    return [
        ModelVersionDecisionItem(
            id=r["id"],
            decision=r["decision"],
            previous_version_id=r["previous_version_id"],
            candidate_version_id=r["candidate_version_id"],
            composite_recent_prev=r["composite_recent_prev"],
            composite_recent_cand=r["composite_recent_cand"],
            composite_seasonal_prev=r["composite_seasonal_prev"],
            composite_seasonal_cand=r["composite_seasonal_cand"],
            composite_longterm_prev=r["composite_longterm_prev"],
            composite_longterm_cand=r["composite_longterm_cand"],
            sample_counts=_parse_json(r["sample_counts"]),
            evaluation_window_start=_format_iso(r["evaluation_window_start"]),
            evaluation_window_end=_format_iso(r["evaluation_window_end"]),
            reason=r["reason"],
            triggered_by=r["triggered_by"],
            pipeline_run_id=r["pipeline_run_id"],
            algorithm_version=r["algorithm_version"],
            created_at=_format_iso(r["created_at"]) or "",
        )
        for r in rows
    ]


# ==============================================================================
# Forecaster+ Endpoints (require_role("forecaster+"))
# ==============================================================================

@router.get("/models/automation/status", response_model=AutomationStateResponse)
async def get_automation_status(
    current_user: CurrentUser = Depends(require_role("forecaster+")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> AutomationStateResponse:
    """Returns the current model switching automation state and active candidate status.

    Authoritative source: Design Doc §S, §T
    """
    state_row = await conn.fetchrow(
        """
        SELECT id, frozen, frozen_reason, frozen_by, frozen_at, cooldown_until,
               rollback_count_14d, updated_at
        FROM model_switching_automation_state
        WHERE id = 1
        """
    )
    if not state_row:
        # Default fallback if table was empty
        return AutomationStateResponse(
            id=1,
            frozen=False,
            frozen_reason=None,
            frozen_by=None,
            frozen_at=None,
            cooldown_until=None,
            rollback_count_14d=0,
            updated_at=_format_iso(None) or "",
            current_candidate=None,
        )

    cand_row = await conn.fetchrow(
        """
        SELECT id, status, algorithm_type, evaluation_policy, created_at,
               shadow_started_at, canary_started_at
        FROM model_versions
        WHERE status IN ('candidate', 'evaluating', 'eligible', 'shadow', 'canary')
        ORDER BY id DESC
        LIMIT 1
        """
    )

    current_cand = None
    if cand_row:
        current_cand = {
            "id": cand_row["id"],
            "status": cand_row["status"],
            "algorithm_type": cand_row["algorithm_type"],
            "evaluation_policy": cand_row["evaluation_policy"],
            "created_at": _format_iso(cand_row["created_at"]),
            "shadow_started_at": _format_iso(cand_row["shadow_started_at"]),
            "canary_started_at": _format_iso(cand_row["canary_started_at"]),
        }

    return AutomationStateResponse(
        id=state_row["id"],
        frozen=state_row["frozen"],
        frozen_reason=state_row["frozen_reason"],
        frozen_by=str(state_row["frozen_by"]) if state_row["frozen_by"] else None,
        frozen_at=_format_iso(state_row["frozen_at"]),
        cooldown_until=_format_iso(state_row["cooldown_until"]),
        rollback_count_14d=state_row["rollback_count_14d"],
        updated_at=_format_iso(state_row["updated_at"]) or "",
        current_candidate=current_cand,
    )


# ==============================================================================
# Model Automation Mutation Controls (Permanently Removed & Disallowed)
# ==============================================================================

@router.post("/models/automation/freeze")
async def freeze_automation(
    payload: Optional[FreezeRequest] = None,
    current_user: CurrentUser = Depends(require_role("public")),
) -> Dict[str, Any]:
    """Model switching automation is permanently enabled. Human mutation controls are removed and permanently disabled."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "OPERATION_DISALLOWED",
            "message": "Model switching automation is permanently enabled. Manual freeze mutation controls have been removed and are permanently disabled.",
            "retry_after": None,
        },
    )


@router.post("/models/automation/unfreeze")
async def unfreeze_automation(
    payload: Optional[UnfreezeRequest] = None,
    current_user: CurrentUser = Depends(require_role("public")),
) -> Dict[str, Any]:
    """Model switching automation is permanently enabled. Human mutation controls are removed and permanently disabled."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "OPERATION_DISALLOWED",
            "message": "Model switching automation is permanently enabled. Manual unfreeze mutation controls have been removed and are permanently disabled.",
            "retry_after": None,
        },
    )


@router.post("/models/automation/force-last-known-good")
async def force_last_known_good(
    payload: Optional[ForceLastKnownGoodRequest] = None,
    current_user: CurrentUser = Depends(require_role("public")),
) -> Dict[str, Any]:
    """Model switching automation is permanently enabled. Human mutation controls are removed and permanently disabled."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "OPERATION_DISALLOWED",
            "message": "Model switching automation is permanently enabled. Manual force-last-known-good controls have been removed and are permanently disabled.",
            "retry_after": None,
        },
    )


@router.post("/models/candidates/{id}/disable")
async def disable_candidate(
    id: int = Path(..., description="ID of the candidate model version"),
    payload: Optional[DisableCandidateRequest] = None,
    current_user: CurrentUser = Depends(require_role("public")),
) -> Dict[str, Any]:
    """Model switching automation is permanently enabled. Human mutation controls are removed and permanently disabled."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "OPERATION_DISALLOWED",
            "message": "Model switching automation is permanently enabled. Candidate disable mutation controls have been removed and are permanently disabled.",
            "retry_after": None,
        },
    )

