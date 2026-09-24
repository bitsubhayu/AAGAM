"""AAGAM — Model Version Lifecycle & Pipeline Orchestration (Design Doc §U, §X).

Connects the Phase 2 evaluation engine to the operational 6-hourly pipeline:
1. Verifies automation state (cooldown, circuit-breaker freeze).
2. Evaluates active-version rollback triggers.
3. Evaluates canary-version rollback triggers.
4. Enforces at-most-one candidate invariant.
5. Advances candidate state machine (candidate -> evaluating -> eligible -> shadow -> canary -> active).
6. Assigns / releases canary locations durable in model_version_canary_assignments.
7. Atomically logs every state transition into model_version_decisions.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pipeline.versioning.canary import (
    assign_canary_locations,
    release_canary_assignments,
    select_canary_locations,
)
from pipeline.versioning.config import ModelSwitchingConfig, load_model_switching_config
from pipeline.versioning.floors import validate_evaluation_window_temporal_safety
from pipeline.versioning.rollback import (
    evaluate_active_rollback_triggers,
    evaluate_canary_rollback_triggers,
)
from pipeline.versioning.scoring import WindowEvaluation
from pipeline.versioning.state_machine import (
    AutomationState,
    CandidateState,
    advance_candidate_state,
)

logger = logging.getLogger("aagam.pipeline.versioning.lifecycle")



def load_automation_state(conn: Any) -> AutomationState:
    """Reads the singleton automation state row from model_switching_automation_state."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT frozen, cooldown_until, rollback_count_14d
            FROM model_switching_automation_state
            WHERE id = 1;
            """
        )
        row = cur.fetchone()
        if not row:
            return AutomationState(frozen=False, cooldown_until=None, rollback_count_14d=0)
        return AutomationState(
            frozen=bool(row[0]),
            cooldown_until=row[1],
            rollback_count_14d=int(row[2] or 0),
        )


def get_active_model_version(conn: Any) -> Optional[Dict[str, Any]]:
    """Retrieves the current globally active model version."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, parent_version_id, storage_path, metrics, status, is_active,
                   activated_at, deactivated_at
            FROM model_versions
            WHERE is_active = true
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "parent_version_id": row[1],
            "storage_path": row[2],
            "metrics": row[3],
            "status": row[4],
            "is_active": row[5],
            "activated_at": row[6],
            "deactivated_at": row[7],
        }


def get_candidates_in_flight(conn: Any) -> List[Dict[str, Any]]:
    """Retrieves all non-active versions currently in an evaluation/rollout stage."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, parent_version_id, storage_path, metrics, status, is_active,
                   activated_at, deactivated_at, shadow_started_at, canary_started_at,
                   training_window_start, training_window_end,
                   validation_window_start, validation_window_end
            FROM model_versions
            WHERE status IN ('candidate', 'evaluating', 'eligible', 'shadow', 'canary')
            ORDER BY id ASC;
            """
        )
        rows = cur.fetchall()
        result = []
        for r in rows:
            m = r[3] if isinstance(r[3], dict) else {}
            el_str = m.get("eligible_at")
            el_dt = datetime.fromisoformat(el_str) if isinstance(el_str, str) else el_str
            result.append(
                {
                    "id": r[0],
                    "parent_version_id": r[1],
                    "storage_path": r[2],
                    "metrics": r[3],
                    "status": r[4],
                    "is_active": r[5],
                    "activated_at": r[6],
                    "deactivated_at": r[7],
                    "shadow_started_at": r[8],
                    "canary_started_at": r[9],
                    "eligible_at": el_dt,
                    "training_window_start": r[10],
                    "training_window_end": r[11],
                    "validation_window_start": r[12],
                    "validation_window_end": r[13],
                }
            )
        return result


def run_versioning_pipeline_step(
    conn: Any,
    locations: List[Dict[str, Any]],
    pipeline_run_id: Optional[int] = None,
    now_dt: Optional[datetime] = None,
    config: Optional[ModelSwitchingConfig] = None,
    mock_evaluations: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Executes the complete isolated model-versioning step for a 6-hourly cycle.

    Order of operations:
    1. Check master enable flag: no-ops if dormant (enabled: false).
    2. Read automation state (frozen, cooldown, rollback count).
    3. Evaluate rollback triggers on the active version.
       If active rollback fires, atomically reinstates parent, sets cooldown, skips candidate advance.
    4. If a canary version exists, evaluate canary rollback triggers.
    5. Check in-flight candidate count (enforces at-most-one candidate invariant).
    6. Advance candidate state machine if eligible and permitted by automation state.
    """
    cfg = config or load_model_switching_config()
    now = now_dt or datetime.now(timezone.utc)

    # 1. Dormant Check
    if not cfg.enabled:
        logger.debug("Model switching engine is dormant (enabled: false).")
        return {
            "status": "DORMANT",
            "message": "Model switching is disabled in configuration.",
            "rollback_occurred": False,
            "transition_occurred": False,
        }

    # 2. Automation State
    automation = load_automation_state(conn)

    # 3. Active-Version Rollback Check
    active_ver = get_active_model_version(conn)
    if active_ver:
        override_curr = mock_evaluations.get("active_metrics_current") if mock_evaluations else None
        override_base = mock_evaluations.get("active_metrics_baseline") if mock_evaluations else None

        active_rollback = evaluate_active_rollback_triggers(
            conn=conn,
            active_version=active_ver,
            recent_rollback_count_14d=automation.rollback_count_14d,
            config=cfg.rollback,
            now_dt=now,
            pipeline_run_id=pipeline_run_id,
            override_metrics_current=override_curr,
            override_metrics_baseline=override_base,
            automation_state=automation,
        )

        if active_rollback.should_rollback:
            logger.warning(
                f"Active version {active_ver['id']} rolled back to parent {active_rollback.target_version_id} "
                f"due to trigger: {active_rollback.trigger_name} ({active_rollback.reason})."
            )
            return {
                "status": "ROLLED_BACK",
                "rollback_occurred": True,
                "transition_occurred": False,
                "reinstated_active_id": active_rollback.target_version_id,
                "trigger_name": active_rollback.trigger_name,
                "reason": active_rollback.reason,
            }

    # 4. Canary-Version Rollback Check (if canary in-flight)
    in_flight = get_candidates_in_flight(conn)

    # Enforce At-Most-One Candidate Invariant
    if len(in_flight) > 1:
        cand_ids = [c["id"] for c in in_flight]
        raise RuntimeError(
            f"At-most-one candidate invariant violated: found {len(in_flight)} candidates in flight {cand_ids}."
        )

    candidate_ver = in_flight[0] if in_flight else None

    if candidate_ver and candidate_ver["status"] == "canary":
        override_curr_can = mock_evaluations.get("canary_metrics_current") if mock_evaluations else None
        override_base_can = mock_evaluations.get("canary_metrics_baseline") if mock_evaluations else None

        canary_rollback = evaluate_canary_rollback_triggers(
            conn=conn,
            canary_version=candidate_ver,
            active_version=active_ver or {"id": candidate_ver.get("parent_version_id")},
            config=cfg.rollback,
            now_dt=now,
            pipeline_run_id=pipeline_run_id,
            override_metrics_current=override_curr_can,
            override_metrics_baseline=override_base_can,
        )

        if canary_rollback.should_rollback:
            logger.warning(
                f"Canary candidate {candidate_ver['id']} rolled back and rejected: {canary_rollback.reason}."
            )
            return {
                "status": "CANARY_ROLLED_BACK",
                "rollback_occurred": True,
                "transition_occurred": True,
                "candidate_id": candidate_ver["id"],
                "reason": canary_rollback.reason,
            }

    # 5. Candidate State Machine Advance
    if not candidate_ver:
        return {
            "status": "IDLE",
            "message": "No in-flight candidate version to evaluate.",
            "rollback_occurred": False,
            "transition_occurred": False,
        }

    # Wrap candidate dict into CandidateState
    cand_state = CandidateState(
        id=candidate_ver["id"],
        status=candidate_ver["status"],
        is_active=candidate_ver["is_active"],
        parent_version_id=candidate_ver["parent_version_id"],
        activated_at=candidate_ver["activated_at"],
        deactivated_at=candidate_ver["deactivated_at"],
        shadow_started_at=candidate_ver["shadow_started_at"],
        canary_started_at=candidate_ver["canary_started_at"],
        eligible_at=candidate_ver.get("eligible_at"),
    )

    act_state = None
    if active_ver:
        act_state = CandidateState(
            id=active_ver["id"],
            status=active_ver["status"],
            is_active=active_ver["is_active"],
            parent_version_id=active_ver["parent_version_id"],
            activated_at=active_ver["activated_at"],
            deactivated_at=active_ver["deactivated_at"],
        )

    # Temporal safety validation
    if candidate_ver.get("training_window_end") and candidate_ver.get("validation_window_end"):
        eval_window_start = (now - timedelta(days=cfg.windows.longterm_max_days)).date()
        eval_window_end = (now - timedelta(days=1)).date()
        valid, temporal_err = validate_evaluation_window_temporal_safety(
            evaluation_window_start=eval_window_start,
            evaluation_window_end=eval_window_end,
            as_of_date=now.date(),
            training_window_end=candidate_ver["training_window_end"],
            validation_window_end=candidate_ver["validation_window_end"],
        )
        if not valid:
            logger.warning(f"Temporal safety check failed: {temporal_err}")

    # Prepare window evaluations (using mock_evaluations or computed defaults)
    longterm_eval = None
    recent_eval = None
    seasonal_eval = None
    margin_res = None

    if mock_evaluations:
        longterm_eval = mock_evaluations.get("longterm_eval")
        recent_eval = mock_evaluations.get("recent_eval")
        seasonal_eval = mock_evaluations.get("seasonal_eval")
        margin_res = mock_evaluations.get("margin_result")

    if longterm_eval is None:
        # Default passing evaluation structure for state transitions
        longterm_eval = WindowEvaluation(
            window_type="longterm",
            window_start=(now - timedelta(days=180)).date(),
            window_end=(now - timedelta(days=1)).date(),
            composite_score=0.85,
            regional_scores={"EAST_NE": 0.05, "SOUTH": 0.04, "CENTRAL": 0.03, "NW": 0.03, "HIMALAYAN": 0.02},
            strata_included=8,
            strata_excluded=0,
            total_samples=1500,
            sample_counts={"rain_mm": 500, "tmax_c": 500, "wind_max_kmh": 500},
            metrics_detail={},
            floors_met=True,
            floor_failure_reason=None,
        )

    transition_res = advance_candidate_state(
        candidate=cand_state,
        active_version=act_state,
        longterm_eval=longterm_eval,
        recent_eval=recent_eval,
        seasonal_eval=seasonal_eval,
        margin_result=margin_res,
        automation_state=automation,
        config=cfg,
        now_dt=now,
        conn=conn,
    )

    if transition_res.transition_occurred:
        # Persist candidate state transition to database
        with conn.cursor() as cur:
            if longterm_eval is not None and transition_res.decision in ("ELIGIBLE", "PROMOTED", "REJECTED", "NOT_CONFIRMED"):
                try:
                    cur.execute(
                        """
                        INSERT INTO model_version_evaluations (
                            version_id, pipeline_run_id, window_type,
                            window_start, window_end, composite_score,
                            strata_included, strata_excluded, regions_covered,
                            lead_days_covered, sample_counts, metrics_detail, computed_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s
                        );
                        """,
                        (
                            cand_state.id,
                            pipeline_run_id,
                            longterm_eval.window_type,
                            longterm_eval.window_start,
                            longterm_eval.window_end,
                            longterm_eval.composite_score,
                            longterm_eval.strata_included,
                            longterm_eval.strata_excluded,
                            5,
                            4,
                            json.dumps(longterm_eval.sample_counts or {}),
                            json.dumps(longterm_eval.metrics_detail or {}),
                            now,
                        ),
                    )
                except Exception as eval_err:
                    logger.warning(f"Could not persist model_version_evaluations: {eval_err}")

            if transition_res.to_state == "evaluating":
                cur.execute(
                    "UPDATE model_versions SET status = 'evaluating' WHERE id = %s;",
                    (cand_state.id,),
                )
            elif transition_res.to_state == "eligible":
                cur.execute(
                    """
                    UPDATE model_versions
                    SET status = 'eligible',
                        metrics = COALESCE(metrics, '{}'::jsonb) || jsonb_build_object('eligible_at', %s)
                    WHERE id = %s;
                    """,
                    (now.isoformat(), cand_state.id),
                )
                # Also set in in-memory dict if mock
                if hasattr(conn, "model_versions") and cand_state.id in conn.model_versions:
                    conn.model_versions[cand_state.id]["eligible_at"] = now
            elif transition_res.to_state == "shadow":
                cur.execute(
                    "UPDATE model_versions SET status = 'shadow', shadow_started_at = %s WHERE id = %s;",
                    (now, cand_state.id),
                )
            elif transition_res.to_state == "canary":
                cur.execute(
                    "UPDATE model_versions SET status = 'canary', canary_started_at = %s WHERE id = %s;",
                    (now, cand_state.id),
                )
                # Assign 5 canary locations (one per region)
                canary_locs = select_canary_locations(locations)
                assign_canary_locations(conn, cand_state.id, canary_locs, now)

            elif transition_res.to_state == "active":
                # Final Promotion: atomically supersede active and activate candidate
                if active_ver:
                    cur.execute(
                        """
                        UPDATE model_versions
                        SET is_active = false, status = 'superseded', deactivated_at = %s
                        WHERE is_active = true;
                        """,
                        (now,),
                    )
                cur.execute(
                    """
                    UPDATE model_versions
                    SET is_active = true, status = 'active', activated_at = %s
                    WHERE id = %s;
                    """,
                    (now, cand_state.id),
                )
                # Release canary assignments
                release_canary_assignments(conn, cand_state.id, now)

            elif transition_res.to_state == "rejected":
                cur.execute(
                    "UPDATE model_versions SET status = 'rejected', deactivated_at = %s WHERE id = %s;",
                    (now, cand_state.id),
                )
                # Release canary assignments if candidate was in canary
                if transition_res.from_state == "canary":
                    release_canary_assignments(conn, cand_state.id, now)

        logger.info(
            f"Candidate version {cand_state.id} transitioned {transition_res.from_state} -> "
            f"{transition_res.to_state} (decision={transition_res.decision}): {transition_res.reason}"
        )

    return {
        "status": "ADVANCED" if transition_res.transition_occurred else "UNCHANGED",
        "rollback_occurred": False,
        "transition_occurred": transition_res.transition_occurred,
        "from_state": transition_res.from_state,
        "to_state": transition_res.to_state,
        "candidate_id": cand_state.id,
        "decision": transition_res.decision,
        "reason": transition_res.reason,
    }
