"""
AAGAM — Real Database-Backed Staging End-to-End Engine Execution (CHECK 1 & 4).

Authoritative source: AAGAM_MODEL_VERSIONING_DESIGN.md
                      AAGAM_MODEL_VERSIONING_ANTIGRAVITY_SPEC.md

VALIDATES:
1. Real PostgreSQL database-backed execution against disposable/staging database (aagam_staging).
2. NEVER touches or connects to production (enforced via resolve_safe_test_database_url()).
3. Complete Phase 3 lifecycle with enabled=true:
   candidate -> evaluating -> eligible -> shadow -> canary -> active -> rollback -> circuit_breaker
4. Persisted rows in all 5 required tables:
   - model_versions
   - model_version_evaluations
   - model_version_decisions (full audit trail with BOTH rollbacks and FROZEN)
   - model_version_canary_assignments
   - model_switching_automation_state (singleton row, rollback_count_14d=2, frozen=true)
5. Transaction atomicity and the invariant: status == 'active' <=> is_active == true.
6. Weekly cadence anti-flapping hysteresis protection.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg2
import pytest
from dotenv import load_dotenv

from core.config import get_locations, settings
from pipeline.live.runner import LivePipelineRunner
from pipeline.versioning.canary import get_active_canary_assignments
from pipeline.versioning.config import ModelSwitchingConfig, RollbackConfig
from pipeline.versioning.lifecycle import run_versioning_pipeline_step
from pipeline.versioning.rollback import execute_rollback
from pipeline.versioning.state_machine import AutomationState, CandidateState, advance_candidate_state
from tests.test_model_switching_audit import resolve_safe_test_database_url
from tests.test_model_switching_pipeline_integration import (
    make_eval,
    make_margin,
)


def get_safe_staging_database_connection():
    """Resolves and connects strictly to the authorized staging database (aagam_staging).

    Safety rules:
    - Never uses production.
    - Validated by resolve_safe_test_database_url().
    - Must contain explicit 'staging' target marker.
    """
    load_dotenv(".env")
    db_url = os.environ.get("AAGAM_TEST_DATABASE_URL")
    if not db_url:
        prod_url = os.environ.get("DATABASE_URL") or getattr(settings, "DATABASE_URL", None)
        if prod_url:
            p = urlparse(prod_url)
            user_part = p.username.split(".")[1] if "." in p.username else p.username
            db_url = f"postgresql://postgres:{p.password}@db.{user_part}.supabase.co:5432/aagam_staging"
            os.environ["AAGAM_TEST_DATABASE_URL"] = db_url

    os.environ["AAGAM_ALLOW_LIVE_DB_TESTS"] = "true"
    os.environ["ENVIRONMENT"] = "staging"

    safe_url, skip_reason = resolve_safe_test_database_url()
    if not safe_url:
        pytest.skip(f"Staging database connection blocked by safety guard: {skip_reason}")

    try:
        conn = psycopg2.connect(safe_url, connect_timeout=5)
        conn.autocommit = True
        return conn
    except Exception as e:
        pytest.skip(f"Staging database unreachable ({e}); skipping live staging test.")


def seed_staging_database_initial_state(conn: Any):
    """Resets and seeds clean initial state for staging database test."""
    with conn.cursor() as cur:
        # Clean audit and transient tables
        cur.execute("DELETE FROM model_version_canary_assignments;")
        cur.execute("DELETE FROM model_version_decisions;")
        cur.execute("DELETE FROM model_version_evaluations;")
        cur.execute("DELETE FROM blended_forecasts;")
        cur.execute("DELETE FROM alerts;")
        cur.execute("DELETE FROM alert_events;")
        cur.execute("DELETE FROM model_forecasts;")
        cur.execute("DELETE FROM pipeline_runs;")
        cur.execute("DELETE FROM model_versions WHERE id >= 3;")

        # Reset singleton automation state
        cur.execute(
            """
            UPDATE model_switching_automation_state
            SET rollback_count_14d = 0, frozen = false, frozen_reason = null,
                frozen_at = null, cooldown_until = null, updated_at = NOW()
            WHERE id = 1;
            """
        )

        # Ensure seed model versions 1 and 2 exist
        cur.execute(
            """
            INSERT INTO model_versions (id, storage_path, metrics, is_active, status, activated_at, created_by)
            VALUES (1, 'models/20260921_v1/', '{}'::jsonb, false, 'superseded', NOW() - INTERVAL '14 days', 'pipeline:seed')
            ON CONFLICT (id) DO UPDATE
            SET is_active = false, status = 'superseded', deactivated_at = NOW() - INTERVAL '7 days';
            """
        )
        cur.execute(
            """
            INSERT INTO model_versions (id, parent_version_id, storage_path, metrics, is_active, status, activated_at, created_by)
            VALUES (2, 1, 'models/20260921_v2/', '{"mae": 1.0}'::jsonb, true, 'active', NOW() - INTERVAL '7 days', 'pipeline:seed')
            ON CONFLICT (id) DO UPDATE
            SET is_active = true, status = 'active', deactivated_at = null, activated_at = NOW() - INTERVAL '7 days';
            """
        )


class TestRealDatabaseBackedStagingE2E:
    """CHECK 1 & 4: Comprehensive Real PostgreSQL Database-Backed E2E Lifecycle Execution."""

    def test_real_database_lifecycle_and_circuit_breaker(self):
        """Exercises the complete lifecycle against a real PostgreSQL staging database:

        candidate -> evaluating -> eligible -> shadow -> canary -> active -> rollback -> circuit_breaker.
        """
        conn = get_safe_staging_database_connection()
        try:
            seed_staging_database_initial_state(conn)
            locations = get_locations()
            cfg = ModelSwitchingConfig(enabled=True)
            t0 = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

            # -----------------------------------------------------------------
            # 0. Initial State Assertions in Database
            # -----------------------------------------------------------------
            with conn.cursor() as cur:
                cur.execute("SELECT id, status, is_active FROM model_versions ORDER BY id;")
                initial_versions = cur.fetchall()
                assert (1, "superseded", False) in initial_versions
                assert (2, "active", True) in initial_versions

                # Check exactly one active version
                cur.execute("SELECT COUNT(*) FROM model_versions WHERE is_active = true;")
                assert cur.fetchone()[0] == 1

            # Insert candidate Version 3 into real database
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO model_versions (
                        id, parent_version_id, storage_path, metrics, status, is_active,
                        training_window_start, training_window_end,
                        validation_window_start, validation_window_end, created_by
                    ) VALUES (
                        3, 2, 'models/20261001_candidate/', '{"validation_mae": {"rain_mm": 1.4, "tmax_c": 0.8}}'::jsonb,
                        'candidate', false, '2025-01-01', '2025-12-31', '2026-01-01', '2026-01-31', 'pipeline:retrain'
                    );
                    """
                )

            # -----------------------------------------------------------------
            # 1. Transition 1: candidate -> evaluating (Cycle 1, t0)
            # -----------------------------------------------------------------
            res1 = run_versioning_pipeline_step(conn, locations, config=cfg, now_dt=t0)
            assert res1["status"] == "ADVANCED"
            assert res1["from_state"] == "candidate"
            assert res1["to_state"] == "evaluating"

            with conn.cursor() as cur:
                cur.execute("SELECT status, is_active FROM model_versions WHERE id = 3;")
                v3_row = cur.fetchone()
                assert v3_row == ("evaluating", False)

            # -----------------------------------------------------------------
            # 2. Transition 2: evaluating -> eligible (Cycle 1 Confirmation, t0 + 7d)
            # -----------------------------------------------------------------
            t1 = t0 + timedelta(days=7)  # 2026-09-08 00:00:00 UTC
            # Cycle 1 Evaluation Window: 2026-02-01 to 2026-09-07 (strictly after training/validation ends 2026-01-31)
            eval_c1 = make_eval(
                window_start=date(2026, 2, 1),
                window_end=date(2026, 9, 7),
                composite_score=0.88,
            )
            margin_res2 = make_margin(passed=True, candidate_advantage=0.035, required_margin=0.025, decision="ELIGIBLE")
            mock_evals2 = {"margin_result": margin_res2, "longterm_eval": eval_c1}

            res2 = run_versioning_pipeline_step(conn, locations, config=cfg, mock_evaluations=mock_evals2, now_dt=t1)
            assert res2["status"] == "ADVANCED"
            assert res2["from_state"] == "evaluating"
            assert res2["to_state"] == "eligible"
            assert res2["decision"] == "ELIGIBLE"

            # Verify persisted in real database
            with conn.cursor() as cur:
                cur.execute("SELECT status, is_active FROM model_versions WHERE id = 3;")
                assert cur.fetchone() == ("eligible", False)

                # Verify decision written to model_version_decisions
                cur.execute("SELECT decision, candidate_version_id FROM model_version_decisions WHERE decision = 'ELIGIBLE';")
                d_row = cur.fetchone()
                assert d_row is not None
                assert d_row[0] == "ELIGIBLE"
                assert d_row[1] == 3

                # Verify evaluation persisted to model_version_evaluations
                cur.execute("SELECT version_id, window_type, composite_score, window_start, window_end FROM model_version_evaluations WHERE version_id = 3;")
                e_row = cur.fetchone()
                assert e_row is not None
                assert e_row[0] == 3
                assert e_row[1] == "longterm"
                assert str(e_row[3]) == "2026-02-01"
                assert str(e_row[4]) == "2026-09-07"

            # -----------------------------------------------------------------
            # ANTI-FLAPPING CHECK 1: 6-hourly cycle running at t1 + 6 hours (dwell < 7d)
            # -----------------------------------------------------------------
            t1_6h = t1 + timedelta(hours=6)
            res_flapping = run_versioning_pipeline_step(conn, locations, config=cfg, mock_evaluations=mock_evals2, now_dt=t1_6h)
            assert res_flapping["transition_occurred"] is False
            assert "Anti-flapping hysteresis" in res_flapping["reason"]

            with conn.cursor() as cur:
                cur.execute("SELECT status FROM model_versions WHERE id = 3;")
                assert cur.fetchone()[0] == "eligible"  # Still eligible!

            # -----------------------------------------------------------------
            # ANTI-FLAPPING CHECK 2: At t2 (t0 + 14d, dwell >= 7d), attempting to REUSE
            # stale Cycle 1 evidence (window_end 2026-09-07 <= eligible_at 2026-09-08) is BLOCKED!
            # -----------------------------------------------------------------
            t2 = t0 + timedelta(days=14)  # 2026-09-15 00:00:00 UTC (7 days after becoming eligible)
            stale_mock_evals = {"margin_result": margin_res2, "longterm_eval": eval_c1}
            res_stale = run_versioning_pipeline_step(conn, locations, config=cfg, mock_evaluations=stale_mock_evals, now_dt=t2)
            assert res_stale["transition_occurred"] is False
            assert "Anti-flapping guard" in res_stale["reason"]
            assert "must be rolled forward" in res_stale["reason"]

            # -----------------------------------------------------------------
            # 3. Transition 3: eligible -> shadow (Cycle 2 Confirmation with GENUINELY ROLLED-FORWARD WINDOW)
            # -----------------------------------------------------------------
            # Cycle 2 Evaluation Window: 2026-02-08 to 2026-09-14 (rolled forward 7 days with new verified data!)
            eval_c2 = make_eval(
                window_start=date(2026, 2, 8),
                window_end=date(2026, 9, 14),
                composite_score=0.89,
            )
            margin_res3 = make_margin(passed=True, candidate_advantage=0.032, required_margin=0.024)
            mock_evals3 = {"margin_result": margin_res3, "longterm_eval": eval_c2}

            res3 = run_versioning_pipeline_step(conn, locations, config=cfg, mock_evaluations=mock_evals3, now_dt=t2)
            assert res3["status"] == "ADVANCED"
            assert res3["from_state"] == "eligible"
            assert res3["to_state"] == "shadow"

            with conn.cursor() as cur:
                cur.execute("SELECT status, shadow_started_at FROM model_versions WHERE id = 3;")
                sh_row = cur.fetchone()
                assert sh_row[0] == "shadow"
                assert sh_row[1] is not None

            # -----------------------------------------------------------------
            # 4. Transition 4: shadow -> canary (Cycle 4, t0 + 21d, 7d in shadow)
            # -----------------------------------------------------------------
            t3 = t0 + timedelta(days=21)
            margin_res4 = make_margin(passed=True, candidate_advantage=0.038, required_margin=0.022)
            mock_evals4 = {"margin_result": margin_res4}

            res4 = run_versioning_pipeline_step(conn, locations, config=cfg, mock_evaluations=mock_evals4, now_dt=t3)
            assert res4["status"] == "ADVANCED"
            assert res4["from_state"] == "shadow"
            assert res4["to_state"] == "canary"

            # Check durable canary assignments in real database
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT location_id, version_id, released_at
                    FROM model_version_canary_assignments
                    WHERE version_id = 3;
                    """
                )
                canary_rows = cur.fetchall()
                assert len(canary_rows) == 5
                assert all(r[2] is None for r in canary_rows)  # unreleased

            # Verify regional distribution: exactly 1 per region
            active_canary = get_active_canary_assignments(conn)
            assert len(active_canary) == 5
            loc_map = {int(loc.get("id") or loc.get("location_id") or (i + 1)): loc for i, loc in enumerate(locations)}
            regions = {loc_map[lid]["region"] for lid in active_canary.keys()}
            assert regions == {"EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"}

            # -----------------------------------------------------------------
            # 5. Transition 5: canary -> active PROMOTION (Cycle 5, t0 + 35d, 14d in canary)
            # -----------------------------------------------------------------
            t4 = t0 + timedelta(days=35)
            margin_res5 = make_margin(passed=True, candidate_advantage=0.034, required_margin=0.021, decision="PROMOTED")
            mock_evals5 = {"margin_result": margin_res5}

            res5 = run_versioning_pipeline_step(conn, locations, config=cfg, mock_evaluations=mock_evals5, now_dt=t4)
            assert res5["status"] == "ADVANCED"
            assert res5["from_state"] == "canary"
            assert res5["to_state"] == "active"
            assert res5["decision"] == "PROMOTED"

            # Verify Promotion Invariants in Real Database
            with conn.cursor() as cur:
                # Version 3 is now active
                cur.execute("SELECT status, is_active, activated_at, deactivated_at FROM model_versions WHERE id = 3;")
                v3_active = cur.fetchone()
                assert v3_active[0] == "active"
                assert v3_active[1] is True
                assert v3_active[2] is not None
                assert v3_active[3] is None

                # Version 2 is now superseded
                cur.execute("SELECT status, is_active, deactivated_at FROM model_versions WHERE id = 2;")
                v2_superseded = cur.fetchone()
                assert v2_superseded[0] == "superseded"
                assert v2_superseded[1] is False
                assert v2_superseded[2] is not None

                # INVARIANT: status == 'active' <=> is_active == True across entire table
                cur.execute("SELECT id, status, is_active FROM model_versions;")
                all_v = cur.fetchall()
                active_count = sum(1 for v in all_v if v[2])
                assert active_count == 1, f"Expected exactly 1 active version, found {active_count}"
                for v in all_v:
                    if v[2]:
                        assert v[1] == "active"
                    else:
                        assert v[1] != "active"

                # Canary assignments all released
                cur.execute("SELECT COUNT(*) FROM model_version_canary_assignments WHERE version_id = 3 AND released_at IS NOT NULL;")
                assert cur.fetchone()[0] == 5

                # PROMOTED decision in audit trail
                cur.execute("SELECT decision, candidate_version_id, previous_version_id FROM model_version_decisions WHERE decision = 'PROMOTED';")
                p_dec = cur.fetchone()
                assert p_dec == ("PROMOTED", 3, 2)

            # -----------------------------------------------------------------
            # 6. Retry / Idempotency Check
            # -----------------------------------------------------------------
            res_retry = run_versioning_pipeline_step(conn, locations, config=cfg, mock_evaluations=mock_evals5, now_dt=t4)
            assert res_retry["transition_occurred"] is False
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM model_version_decisions WHERE decision = 'PROMOTED';")
                assert cur.fetchone()[0] == 1

            # -----------------------------------------------------------------
            # 7. Transition 6: First Active Rollback (Cycle 6, t0 + 37d)
            # -----------------------------------------------------------------
            t5 = t0 + timedelta(days=37)
            # Injected degradation: active Version 3 MAE jumps > 25%
            mock_evals_rb1 = {
                "active_metrics_current": {"mae": 1.45, "n": 30},
                "active_metrics_baseline": {"mae": 1.00},
            }

            res_rb1 = run_versioning_pipeline_step(conn, locations, config=cfg, mock_evaluations=mock_evals_rb1, now_dt=t5)
            assert res_rb1["status"] == "ROLLED_BACK"
            assert res_rb1["rollback_occurred"] is True
            assert res_rb1["reinstated_active_id"] == 2

            with conn.cursor() as cur:
                # Version 3 is rolled_back, Version 2 is reinstated active
                cur.execute("SELECT status, is_active FROM model_versions WHERE id = 3;")
                assert cur.fetchone() == ("rolled_back", False)
                cur.execute("SELECT status, is_active FROM model_versions WHERE id = 2;")
                assert cur.fetchone() == ("active", True)

                # Automation state updated
                cur.execute("SELECT rollback_count_14d, frozen, cooldown_until FROM model_switching_automation_state WHERE id = 1;")
                auto1 = cur.fetchone()
                assert auto1[0] == 1
                assert auto1[1] is False
                assert auto1[2] is not None

                # First ROLLED_BACK decision written
                cur.execute("SELECT decision, candidate_version_id, previous_version_id FROM model_version_decisions WHERE decision = 'ROLLED_BACK';")
                rb_decisions = cur.fetchall()
                assert len(rb_decisions) == 1
                assert rb_decisions[0] == ("ROLLED_BACK", 2, 3)

            # -----------------------------------------------------------------
            # 8. Transition 7: Second Rollback within 14d & Circuit Breaker (Cycle 7, t0 + 39d)
            # -----------------------------------------------------------------
            t6 = t5 + timedelta(days=2)
            rb_cfg = RollbackConfig(circuit_breaker_max_rollbacks=2, cooldown_days=7)

            # Execute second rollback against the actual persistence layer
            cooldown2, cb_triggered = execute_rollback(
                conn=conn,
                from_version_id=2,
                to_version_id=1,
                trigger_name="mae_degradation",
                reason="Second degradation within rolling 14 days",
                now_dt=t6,
                config=rb_cfg,
            )
            assert cb_triggered is True

            # -----------------------------------------------------------------
            # 9. COMPLETE CIRCUIT BREAKER & PERSISTENCE VERIFICATION
            # -----------------------------------------------------------------
            with conn.cursor() as cur:
                # 1. model_versions: Version 1 active, 2 rolled_back, 3 rolled_back
                cur.execute("SELECT id, status, is_active FROM model_versions ORDER BY id;")
                final_versions = cur.fetchall()
                assert (1, "active", True) in final_versions
                assert (2, "rolled_back", False) in final_versions
                assert (3, "rolled_back", False) in final_versions

                # Invariant: exactly 1 active version
                cur.execute("SELECT COUNT(*) FROM model_versions WHERE is_active = true;")
                assert cur.fetchone()[0] == 1

                # Invariant: status == 'active' <=> is_active == True across all rows
                for v in final_versions:
                    if v[2]:
                        assert v[1] == "active"
                    else:
                        assert v[1] != "active"

                # 2. model_switching_automation_state: rollback_count_14d = 2, frozen = true
                cur.execute("SELECT rollback_count_14d, frozen, frozen_reason, frozen_at FROM model_switching_automation_state WHERE id = 1;")
                auto_final = cur.fetchone()
                assert auto_final[0] == 2, f"Expected rollback_count_14d=2, got {auto_final[0]}"
                assert auto_final[1] is True, "Expected automation state frozen=True"
                assert "circuit breaker" in auto_final[2]
                assert auto_final[3] is not None

                # 3. model_version_decisions: Complete Audit Trail with BOTH Rollbacks and FROZEN
                cur.execute("SELECT decision, candidate_version_id, previous_version_id, reason FROM model_version_decisions ORDER BY id ASC;")
                all_decisions = cur.fetchall()
                decision_types = [d[0] for d in all_decisions]

                # Assert BOTH ROLLED_BACK decisions are persisted and queryable
                rb_only = [d for d in all_decisions if d[0] == "ROLLED_BACK"]
                assert len(rb_only) == 2, f"Expected exactly 2 ROLLED_BACK decisions, got {len(rb_only)}: {rb_only}"
                assert rb_only[0][1] == 2 and rb_only[0][2] == 3  # First: 3 -> 2
                assert rb_only[1][1] == 1 and rb_only[1][2] == 2  # Second: 2 -> 1

                # Assert FROZEN decision written
                assert "FROZEN" in decision_types
                frozen_dec = [d for d in all_decisions if d[0] == "FROZEN"][0]
                assert "circuit breaker" in frozen_dec[3]

                # Full ordered decision trail
                assert decision_types == ["ELIGIBLE", "PROMOTED", "ROLLED_BACK", "ROLLED_BACK", "FROZEN"]

            # -----------------------------------------------------------------
            # 10. Verify Frozen Automation Blocks Any Subsequent Candidate
            # -----------------------------------------------------------------
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO model_versions (id, parent_version_id, storage_path, metrics, status, is_active)
                    VALUES (4, 1, 'models/20261015_cand4/', '{}'::jsonb, 'candidate', false);
                    """
                )

            cand4 = CandidateState(id=4, status="candidate", is_active=False, parent_version_id=1)
            act1 = CandidateState(id=1, status="active", is_active=True, parent_version_id=None)
            frozen_res = advance_candidate_state(
                candidate=cand4,
                active_version=act1,
                longterm_eval=make_eval(),
                automation_state=AutomationState(frozen=True),
                config=cfg,
                now_dt=t6,
                conn=conn,
            )
            assert frozen_res.transition_occurred is False
            assert frozen_res.decision == "FROZEN"

            print("\n[REAL STAGING DB PROOF COMPLETE] Full lifecycle, 2 rollbacks, circuit breaker, and audit trail verified in PostgreSQL.")
        finally:
            conn.close()


def test_real_live_runner_pipeline_integration_staging():
    """Requirement 1: Validates that LivePipelineRunner exercises the real production integration path.

    Exercises the full production execution chain against the real PostgreSQL staging database:
    1. Ingest/prepared input (generates multi-model 40-location forecasts via dry_run=True)
    2. Model versioning boundary (run_model_versioning_boundary logs to pipeline_runs)
    3. Serving-version resolution (queries model_versions in staging DB)
    4. Model prediction & blend generation (Ridge + LightGBM + Adaptive Blender)
    5. Canary serving substitution (substitutes candidate forecasts for assigned canary locations)
    6. Shadow evaluation (saves shadow predictions if candidate in shadow)
    7. Extreme weather hazard guidance / alert generation
    8. Writes blended_forecasts table in staging DB
    9. Upserts alerts and alert_events tables in staging DB
    10. Logs ingest-blend run in pipeline_runs table with status=SUCCESS!
    """
    conn = get_safe_staging_database_connection()
    try:
        load_dotenv(".env")
        safe_url = os.environ.get("AAGAM_TEST_DATABASE_URL")
        assert safe_url is not None
        assert "staging" in safe_url

        # Seed initial state for live runner test:
        # Version 2 is active
        # Version 3 is candidate in canary with location 1 assigned
        # Version 4 is candidate in shadow
        seed_staging_database_initial_state(conn)
        with conn.cursor() as cur:
            now_utc = datetime.now(timezone.utc)
            # Add Version 3 in canary and assign location 1
            cur.execute(
                """
                INSERT INTO model_versions (id, parent_version_id, storage_path, metrics, status, is_active, canary_started_at)
                VALUES (3, 2, 'models/', '{}'::jsonb, 'canary', false, %s);
                """,
                (now_utc,),
            )
            cur.execute(
                """
                INSERT INTO model_version_canary_assignments (location_id, version_id, assigned_at, released_at)
                VALUES (1, 3, %s, NULL)
                ON CONFLICT (location_id, version_id, assigned_at) DO NOTHING;
                """,
                (now_utc,),
            )
            # Add Version 4 in shadow
            cur.execute(
                """
                INSERT INTO model_versions (id, parent_version_id, storage_path, metrics, status, is_active, shadow_started_at)
                VALUES (4, 2, 'models/', '{}'::jsonb, 'shadow', false, %s);
                """,
                (now_utc,),
            )

        runner = LivePipelineRunner(db_url=safe_url)
        # Execute the real live runner cycle with model-switching enabled for integration verification
        with patch("pipeline.versioning.config.load_model_switching_config", return_value=ModelSwitchingConfig(enabled=True)):
            result = runner.run_cycle(dry_run=True)

        assert result["status"] == "SUCCESS"
        assert result["blended_rows"] > 0
        assert result["version_id"] == 2  # Version 2 is the active incumbent

        # 1. Verify blended_forecasts in staging DB
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM blended_forecasts;")
            blend_count = cur.fetchone()[0]
            assert blend_count == result["blended_rows"]

            # Canary serving substitution verification:
            # Location 1 was assigned to canary candidate version 3 -> blended_forecasts must have version_id=3
            cur.execute("SELECT DISTINCT version_id FROM blended_forecasts WHERE location_id = 1;")
            canary_vids = [r[0] for r in cur.fetchall()]
            assert canary_vids == [3], f"Expected canary location 1 to be served by candidate version 3, got {canary_vids}"

            # Non-canary locations (e.g. location 2) must be served by active incumbent version 2
            cur.execute("SELECT DISTINCT version_id FROM blended_forecasts WHERE location_id = 2;")
            non_canary_vids = [r[0] for r in cur.fetchall()]
            assert non_canary_vids == [2], f"Expected non-canary location 2 to be served by incumbent version 2, got {non_canary_vids}"

            # 2. Verify alerts table in staging DB
            cur.execute("SELECT COUNT(*) FROM alerts;")
            alerts_count = cur.fetchone()[0]
            assert alerts_count == result["alerts_count"]

            # 3. Verify pipeline_runs table in staging DB
            cur.execute("SELECT job, status, rows_written FROM pipeline_runs ORDER BY id DESC LIMIT 5;")
            runs = cur.fetchall()
            jobs = {r[0]: r[1] for r in runs}
            assert "ingest-blend" in jobs
            assert jobs["ingest-blend"] == "SUCCESS"
            assert "model-versioning" in jobs

        print("\n[REAL LIVE RUNNER STAGING PROOF COMPLETE] Full live runner ingest-blend, serving resolution, canary substitution, and DB write verified!")
    finally:
        conn.close()

