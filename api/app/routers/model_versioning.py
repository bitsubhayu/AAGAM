"""Model versioning, lifecycle, and automation management API endpoints.

Authoritative source:
- AAGAM_MODEL_VERSIONING_DESIGN.md §S, §T
- AAGAM_MODEL_VERSIONING_ANTIGRAVITY_SPEC.md Phase 4
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn, set_rls_claims
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
from pipeline.versioning.decisions import write_decision

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
# Coordinator Only Endpoints (require_role("coordinator"))
# ==============================================================================

@router.post("/models/automation/freeze", response_model=AutomationStateResponse)
async def freeze_automation(
    payload: FreezeRequest,
    current_user: CurrentUser = Depends(require_role("coordinator")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> AutomationStateResponse:
    """Freezes automatic model-version promotion.

    Requires coordinator role, reason with minimum 10 characters.
    Writes an immutable decision record with triggered_by=current_user.user_id.

    Authoritative source: Design Doc §T, §S
    """
    await set_rls_claims(conn, current_user.user_id, role="authenticated")

    user_uuid = None
    if current_user.user_id:
        try:
            user_uuid = uuid.UUID(str(current_user.user_id))
        except (ValueError, AttributeError):
            user_uuid = None

    valid_user_uuid = None
    if user_uuid:
        try:
            user_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM auth.users WHERE id = $1)",
                user_uuid,
            )
            if user_exists:
                valid_user_uuid = user_uuid
        except Exception:
            valid_user_uuid = None

    async with conn.transaction():
        # Update automation state
        await conn.execute(
            """
            UPDATE model_switching_automation_state
            SET frozen = true,
                frozen_reason = $1,
                frozen_by = $2,
                frozen_at = NOW(),
                updated_at = NOW()
            WHERE id = 1
            """,
            payload.reason,
            valid_user_uuid,
        )

        # Audit decision record (Design requirement)
        write_decision(
            decision="FROZEN",
            reason=payload.reason,
            triggered_by=str(current_user.user_id),
            algorithm_version="staged_v2",
        )

        await conn.execute(
            """
            INSERT INTO model_version_decisions (
                decision, reason, triggered_by, algorithm_version, sample_counts
            ) VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            "FROZEN",
            payload.reason,
            str(current_user.user_id),
            "staged_v2",
            json.dumps({}),
        )

    logger.info(f"Coordinator {current_user.user_id} froze model automation: {payload.reason}")
    return await get_automation_status(current_user=current_user, conn=conn)


@router.post("/models/automation/unfreeze", response_model=AutomationStateResponse)
async def unfreeze_automation(
    payload: UnfreezeRequest,
    current_user: CurrentUser = Depends(require_role("coordinator")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> AutomationStateResponse:
    """Unfreezes automatic model-version promotion.

    Requires coordinator role, reason with minimum 10 characters.
    Writes an immutable decision record with decision="UNFROZEN" and triggered_by=current_user.user_id.

    Authoritative source: Design Doc §T, §S
    """
    await set_rls_claims(conn, current_user.user_id, role="authenticated")

    async with conn.transaction():
        await conn.execute(
            """
            UPDATE model_switching_automation_state
            SET frozen = false,
                frozen_reason = NULL,
                frozen_by = NULL,
                frozen_at = NULL,
                updated_at = NOW()
            WHERE id = 1
            """
        )

        # Audit decision record (Design requirement: distinct UNFROZEN semantic)
        write_decision(
            decision="UNFROZEN",
            reason=payload.reason,
            triggered_by=str(current_user.user_id),
            algorithm_version="staged_v2",
        )

        await conn.execute(
            """
            INSERT INTO model_version_decisions (
                decision, reason, triggered_by, algorithm_version, sample_counts
            ) VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            "UNFROZEN",
            payload.reason,
            str(current_user.user_id),
            "staged_v2",
            json.dumps({}),
        )

    logger.info(f"Coordinator {current_user.user_id} unfroze model automation: {payload.reason}")
    return await get_automation_status(current_user=current_user, conn=conn)


@router.post("/models/automation/force-last-known-good", response_model=ModelVersionSummary)
async def force_last_known_good(
    payload: ForceLastKnownGoodRequest,
    current_user: CurrentUser = Depends(require_role("coordinator")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> ModelVersionSummary:
    """Forces immediate activation of the nearest surviving non-rolled-back ancestor version.

    Walks parent_version_id back from the active version, safely bypassing any versions
    marked 'rolled_back'. Sets the target version to active, the active version to rolled_back,
    and writes an audit decision row.

    Authoritative source: Design Doc §T, §S
    """
    await set_rls_claims(conn, current_user.user_id, role="authenticated")

    active_row = await conn.fetchrow(
        """
        SELECT id, status, parent_version_id, algorithm_type, evaluation_policy, is_active,
               created_at, activated_at, deactivated_at, created_by
        FROM model_versions
        WHERE is_active = true
        ORDER BY id DESC
        LIMIT 1
        """
    )
    if not active_row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "NO_ACTIVE_VERSION",
                "message": "No active model version currently found.",
                "retry_after": None,
            },
        )

    # Walk parent_version_id chain to find nearest ancestor NOT marked rolled_back
    curr_parent_id = active_row["parent_version_id"]
    target_row = None
    visited = set()

    while curr_parent_id is not None:
        if curr_parent_id in visited:
            logger.warning(f"Cycle detected in parent_version_id chain at version {curr_parent_id}")
            break
        visited.add(curr_parent_id)

        parent_row = await conn.fetchrow(
            """
            SELECT id, status, parent_version_id, algorithm_type, evaluation_policy, is_active,
                   created_at, activated_at, deactivated_at, created_by
            FROM model_versions
            WHERE id = $1
            """,
            curr_parent_id,
        )
        if not parent_row:
            logger.warning(f"Parent version {curr_parent_id} not found in database.")
            break

        if parent_row["status"] == "rolled_back":
            logger.info(
                f"Ancestor version {parent_row['id']} has status='rolled_back'; "
                f"skipping and walking to parent {parent_row['parent_version_id']}"
            )
            curr_parent_id = parent_row["parent_version_id"]
            continue

        # Found the clean ancestor!
        target_row = parent_row
        break

    if target_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "NO_CLEAN_ANCESTOR",
                "message": (
                    f"No clean last-known-good ancestor version found for active version {active_row['id']} "
                    "(ancestor versions either do not exist or are already marked rolled_back)."
                ),
                "retry_after": None,
            },
        )

    async with conn.transaction():
        # Deactivate currently active version
        await conn.execute(
            """
            UPDATE model_versions
            SET is_active = false,
                status = 'rolled_back',
                deactivated_at = NOW()
            WHERE id = $1
            """,
            active_row["id"],
        )

        # Activate target ancestor
        await conn.execute(
            """
            UPDATE model_versions
            SET is_active = true,
                status = 'active',
                activated_at = NOW()
            WHERE id = $1
            """,
            target_row["id"],
        )

        # Write audit decision record
        write_decision(
            decision="ROLLED_BACK",
            reason=payload.reason,
            previous_version_id=active_row["id"],
            candidate_version_id=target_row["id"],
            triggered_by=str(current_user.user_id),
            algorithm_version="staged_v2",
        )

        await conn.execute(
            """
            INSERT INTO model_version_decisions (
                decision, previous_version_id, candidate_version_id,
                reason, triggered_by, algorithm_version, sample_counts
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            """,
            "ROLLED_BACK",
            active_row["id"],
            target_row["id"],
            payload.reason,
            str(current_user.user_id),
            "staged_v2",
            json.dumps({}),
        )

    logger.info(
        f"Coordinator {current_user.user_id} forced last known good version {target_row['id']} "
        f"(rolled back {active_row['id']}): {payload.reason}"
    )

    reinstated = await conn.fetchrow(
        """
        SELECT id, status, algorithm_type, evaluation_policy, is_active, parent_version_id,
               created_at, activated_at, deactivated_at, created_by
        FROM model_versions
        WHERE id = $1
        """,
        target_row["id"],
    )

    return ModelVersionSummary(
        id=reinstated["id"],
        status=reinstated["status"],
        algorithm_type=reinstated["algorithm_type"],
        evaluation_policy=reinstated["evaluation_policy"],
        is_active=reinstated["is_active"],
        parent_version_id=reinstated["parent_version_id"],
        created_at=_format_iso(reinstated["created_at"]) or "",
        activated_at=_format_iso(reinstated["activated_at"]),
        deactivated_at=_format_iso(reinstated["deactivated_at"]),
        created_by=reinstated["created_by"],
        recent_evaluation=None,
    )


@router.post("/models/candidates/{id}/disable", response_model=ModelVersionSummary)
async def disable_candidate(
    payload: DisableCandidateRequest,
    id: int = Path(..., description="ID of the candidate model version to disable"),
    current_user: CurrentUser = Depends(require_role("coordinator")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> ModelVersionSummary:
    """Sets a candidate model version to 'rejected' regardless of evaluation state.

    Requires coordinator role, reason with minimum 10 characters.
    Cannot disable a currently active model version.
    Writes an immutable decision record with triggered_by=current_user.user_id.

    Authoritative source: Design Doc §T, §S
    """
    await set_rls_claims(conn, current_user.user_id, role="authenticated")

    cand_row = await conn.fetchrow(
        """
        SELECT id, status, is_active, algorithm_type, evaluation_policy, parent_version_id,
               created_at, activated_at, deactivated_at, created_by
        FROM model_versions
        WHERE id = $1
        """,
        id,
    )
    if not cand_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "MODEL_VERSION_NOT_FOUND",
                "message": f"Candidate model version {id} does not exist.",
                "retry_after": None,
            },
        )

    if cand_row["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "CANNOT_DISABLE_ACTIVE_MODEL",
                "message": f"Model version {id} is currently active and cannot be disabled. Use force-last-known-good instead.",
                "retry_after": None,
            },
        )

    async with conn.transaction():
        updated_row = await conn.fetchrow(
            """
            UPDATE model_versions
            SET status = 'rejected'
            WHERE id = $1
            RETURNING id, status, algorithm_type, evaluation_policy, is_active, parent_version_id,
                      created_at, activated_at, deactivated_at, created_by
            """,
            id,
        )

        # Audit decision record (Design requirement)
        write_decision(
            decision="REJECTED",
            reason=payload.reason,
            candidate_version_id=id,
            triggered_by=str(current_user.user_id),
            algorithm_version="staged_v2",
        )

        await conn.execute(
            """
            INSERT INTO model_version_decisions (
                decision, candidate_version_id,
                reason, triggered_by, algorithm_version, sample_counts
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            "REJECTED",
            id,
            payload.reason,
            str(current_user.user_id),
            "staged_v2",
            json.dumps({}),
        )

    logger.info(f"Coordinator {current_user.user_id} disabled candidate model version {id}: {payload.reason}")

    return ModelVersionSummary(
        id=updated_row["id"],
        status=updated_row["status"],
        algorithm_type=updated_row["algorithm_type"],
        evaluation_policy=updated_row["evaluation_policy"],
        is_active=updated_row["is_active"],
        parent_version_id=updated_row["parent_version_id"],
        created_at=_format_iso(updated_row["created_at"]) or "",
        activated_at=_format_iso(updated_row["activated_at"]),
        deactivated_at=_format_iso(updated_row["deactivated_at"]),
        created_by=updated_row["created_by"],
        recent_evaluation=None,
    )
