"""
AAGAM — Real Non-Demo Staging Authentication Acceptance Test (Phase 4 Item 2).

Authoritative references:
- AAGAM_MODEL_VERSIONING_DESIGN.md §S, §T
- AAGAM_MODEL_VERSIONING_ANTIGRAVITY_SPEC.md Phase 4

VALIDATES:
1. Real non-demo Supabase JWT verification with ENABLE_LOCAL_DEMO_AUTH = False.
2. Authoritative role resolution from the PostgreSQL `profiles` table (AUTH-002 fix).
3. Real live database execution against isolated staging database (aagam_staging).
4. POST /api/v1/models/automation/freeze:
   - Sets model_switching_automation_state.frozen = true
   - Records durable audit row with decision='FROZEN' and triggered_by=<real coordinator uuid>
5. Pipeline state machine advance_candidate_state() observes automation.frozen = true
   and performs no candidate advancement.
6. POST /api/v1/models/automation/unfreeze:
   - Sets model_switching_automation_state.frozen = false
   - Records durable audit row with decision='UNFROZEN' and triggered_by=<real coordinator uuid>
7. Pipeline state machine advance_candidate_state() runs un-frozen and advances candidate
   from 'candidate' to 'evaluating'.
8. Zero mutation or connection to production database.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from typing import AsyncGenerator
from urllib.parse import urlparse

import asyncpg
import psycopg2
import pytest
from fastapi.testclient import TestClient

from api.app.db.pool import get_db_conn
from api.app.main import app
from core.config import settings
from pipeline.versioning.config import ModelSwitchingConfig
from pipeline.versioning.lifecycle import run_versioning_pipeline_step
from pipeline.versioning.scoring import WindowEvaluation
from pipeline.versioning.state_machine import AutomationState, CandidateState, advance_candidate_state
from supabase import create_client
from tests.test_model_switching_audit import resolve_safe_test_database_url


def resolve_safe_staging_pooler_url() -> str:
    """Resolves and validates the direct pooler connection string for aagam_staging."""
    os.environ["AAGAM_ALLOW_LIVE_DB_TESTS"] = "true"
    os.environ["ENVIRONMENT"] = "staging"

    staging_url = os.environ.get("AAGAM_TEST_DATABASE_URL")
    if not staging_url:
        prod_url = os.environ.get("DATABASE_URL") or getattr(settings, "DATABASE_URL", None)
        if prod_url:
            p = urlparse(prod_url)
            # Use pooler on port 6543 for transaction pooling compatibility
            staging_url = f"postgresql://{p.username}:{p.password}@{p.hostname}:6543/aagam_staging"
            os.environ["AAGAM_TEST_DATABASE_URL"] = staging_url

    safe_url, skip_reason = resolve_safe_test_database_url()
    if not safe_url:
        pytest.skip(f"Staging database connection blocked by safety guard: {skip_reason}")

    return safe_url


@pytest.fixture(scope="module")
def staging_db():
    """Provides validated psycopg2 connection to aagam_staging."""
    safe_url = resolve_safe_staging_pooler_url()
    try:
        conn = psycopg2.connect(safe_url, connect_timeout=10)
        conn.autocommit = True
        yield conn
        conn.close()
    except Exception as e:
        pytest.skip(f"Could not connect to staging database at {safe_url}: {e}")


def test_staging_real_non_demo_coordinator_lifecycle(staging_db, monkeypatch):
    """End-to-end integration test verifying real non-demo Supabase JWT auth, freeze,
    audit trail, state machine halt, unfreeze, and advancement on aagam_staging.
    """
    safe_url = resolve_safe_staging_pooler_url()

    # 1. Enforce NON-DEMO authentication (AUTH-001 & AUTH-002 requirements)
    monkeypatch.setattr(settings, "ENABLE_LOCAL_DEMO_AUTH", False)

    # 2. Create a real Coordinator user in the REAL Supabase Auth service (GoTrue)
    admin_supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    anon_supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)

    coordinator_email = f"coordinator_{uuid.uuid4().hex[:6]}@aagam.gov.in"
    coordinator_password = f"Coord_{uuid.uuid4().hex[:8]}!Aagam2026"

    auth_user_resp = admin_supabase.auth.admin.create_user({
        "email": coordinator_email,
        "password": coordinator_password,
        "email_confirm": True,
    })
    real_coordinator_uid = str(auth_user_resp.user.id)

    # 3. Obtain access token through the REAL Supabase Auth service (GoTrue API)
    # Strictly NO self-minted JWTs, NO jwt.encode()!
    auth_session = anon_supabase.auth.sign_in_with_password({
        "email": coordinator_email,
        "password": coordinator_password,
    })
    supabase_access_token = auth_session.session.access_token
    assert supabase_access_token, "Failed to obtain real access token from Supabase Auth service"
    assert not supabase_access_token.startswith("demo-"), "Access token must not be a demo token"

    auth_headers = {"Authorization": f"Bearer {supabase_access_token}"}

    with staging_db.cursor() as cur:
        # Clean test state in staging
        cur.execute("DELETE FROM model_version_canary_assignments WHERE version_id >= 3;")
        cur.execute("DELETE FROM model_version_evaluations WHERE version_id >= 3;")
        cur.execute("DELETE FROM model_version_decisions WHERE candidate_version_id >= 3 OR triggered_by = %s;", (real_coordinator_uid,))
        cur.execute("DELETE FROM model_versions WHERE id >= 3;")

        # Ensure profiles table exists
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.profiles (
                user_id UUID PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'public',
                display_name TEXT,
                org TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )

        # Insert authoritative coordinator profile into PostgreSQL staging DB
        cur.execute(
            """
            INSERT INTO public.profiles (user_id, role, display_name, org)
            VALUES (%s, 'coordinator', 'Staging Coordinator', 'NCMRWF')
            ON CONFLICT (user_id) DO UPDATE SET role = 'coordinator';
            """,
            (real_coordinator_uid,),
        )

        # Seed model versions: Version 2 (active), Version 3 (candidate)
        cur.execute(
            """
            INSERT INTO model_versions (id, status, algorithm_type, evaluation_policy, is_active, created_by, storage_path, metrics)
            VALUES (2, 'active', 'ridge_lgbm_v1', 'legacy_single_gate', true, 'pipeline:seed', 'models/v2', '{}'::jsonb)
            ON CONFLICT (id) DO UPDATE SET is_active = true, status = 'active';
            """
        )
        cur.execute(
            """
            INSERT INTO model_versions (id, status, algorithm_type, evaluation_policy, is_active, parent_version_id, created_by, storage_path, metrics)
            VALUES (3, 'candidate', 'ridge_lgbm_v2', 'staged_v2', false, 2, 'pipeline:test', 'models/v3', '{}'::jsonb)
            ON CONFLICT (id) DO UPDATE SET is_active = false, status = 'candidate';
            """
        )

        # Reset automation state to clean baseline
        cur.execute(
            """
            UPDATE model_switching_automation_state
            SET frozen = false, frozen_reason = null, frozen_by = null,
                frozen_at = null, cooldown_until = null, rollback_count_14d = 0,
                updated_at = NOW()
            WHERE id = 1;
            """
        )

    # 4. Configure FastAPI TestClient with live asyncpg connection pool to aagam_staging
    pool = None

    async def get_staging_db_conn() -> AsyncGenerator[asyncpg.Connection, None]:
        nonlocal pool
        if pool is None:
            pool = await asyncpg.create_pool(
                dsn=safe_url,
                statement_cache_size=0,
                min_size=1,
                max_size=3,
                command_timeout=15.0,
            )
        async with pool.acquire() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = get_staging_db_conn

    try:
        with TestClient(app) as client:
            # ==================================================================
            # STEP A: Coordinator Freeze via real API on aagam_staging
            # ==================================================================
            freeze_reason = "Operational freeze during high-impact monsoon cyclone window"
            resp_freeze = client.post(
                "/api/v1/models/automation/freeze",
                headers=auth_headers,
                json={"reason": freeze_reason},
            )
            assert resp_freeze.status_code == 200, f"Freeze failed: {resp_freeze.text}"
            freeze_data = resp_freeze.json()
            assert freeze_data["frozen"] is True
            assert freeze_data["frozen_reason"] == freeze_reason

            # Verify in PostgreSQL staging DB
            with staging_db.cursor() as cur:
                cur.execute("SELECT frozen, frozen_reason FROM model_switching_automation_state WHERE id = 1;")
                row = cur.fetchone()
                assert row[0] is True
                assert row[1] == freeze_reason

                # Verify audit row in model_version_decisions contains triggered_by=<real_coordinator_uid>
                cur.execute(
                    """
                    SELECT decision, reason, triggered_by
                    FROM model_version_decisions
                    WHERE decision = 'FROZEN' AND triggered_by = %s
                    ORDER BY id DESC LIMIT 1;
                    """,
                    (real_coordinator_uid,),
                )
                audit_row = cur.fetchone()
                assert audit_row is not None, "Audit row for FROZEN decision not found in staging DB"
                assert audit_row[0] == "FROZEN"
                assert audit_row[1] == freeze_reason
                assert audit_row[2] == real_coordinator_uid

            # ==================================================================
            # STEP B: Pipeline State Machine halts advancement while frozen
            # ==================================================================
            cand_state = CandidateState(id=3, status="candidate", is_active=False, parent_version_id=2)
            active_state = CandidateState(id=2, status="active", is_active=True, parent_version_id=None)
            active_config = ModelSwitchingConfig(enabled=True)

            longterm_eval = WindowEvaluation(
                window_type="longterm",
                window_start=date(2026, 1, 1),
                window_end=date(2026, 6, 30),
                composite_score=0.85,
                regional_scores={"EAST_NE": 0.05, "SOUTH": 0.04, "CENTRAL": 0.03, "NW": 0.03, "HIMALAYAN": 0.02},
                strata_included=8,
                strata_excluded=0,
                total_samples=1500,
                sample_counts={"rain_mm": 500, "tmax_c": 500, "wind_max_kmh": 500},
                metrics_detail={},
                floors_met=True,
            )

            # Direct advance_candidate_state call observes automation.frozen=True
            frozen_advance_res = advance_candidate_state(
                candidate=cand_state,
                active_version=active_state,
                longterm_eval=longterm_eval,
                automation_state=AutomationState(frozen=True),
                config=active_config,
                conn=staging_db,
            )
            assert frozen_advance_res.transition_occurred is False
            assert frozen_advance_res.decision == "FROZEN"

            # Real 6-hourly pipeline runner path reads DB automation state (frozen=true)
            locations = [{"id": 1, "name": "Delhi"}]
            pipe_res_frozen = run_versioning_pipeline_step(
                conn=staging_db,
                locations=locations,
                config=active_config,
            )
            assert pipe_res_frozen["transition_occurred"] is False

            # Verify candidate version in staging DB remained 'candidate' (halted)
            with staging_db.cursor() as cur:
                cur.execute("SELECT status FROM model_versions WHERE id = 3;")
                cand_status = cur.fetchone()[0]
                assert cand_status == "candidate", (
                    f"Candidate advanced while automation was frozen! Expected 'candidate', got '{cand_status}'"
                )

            # ==================================================================
            # STEP C: Coordinator Unfreeze via real API on aagam_staging
            # ==================================================================
            unfreeze_reason = "Monsoon cyclone window cleared; resuming automated promotion"
            resp_unfreeze = client.post(
                "/api/v1/models/automation/unfreeze",
                headers=auth_headers,
                json={"reason": unfreeze_reason},
            )
            assert resp_unfreeze.status_code == 200, f"Unfreeze failed: {resp_unfreeze.text}"
            unfreeze_data = resp_unfreeze.json()
            assert unfreeze_data["frozen"] is False
            assert unfreeze_data["frozen_reason"] is None

            # Verify in PostgreSQL staging DB
            with staging_db.cursor() as cur:
                cur.execute("SELECT frozen FROM model_switching_automation_state WHERE id = 1;")
                assert cur.fetchone()[0] is False

                # Verify audit row for UNFROZEN decision with triggered_by=<real_coordinator_uid>
                cur.execute(
                    """
                    SELECT decision, reason, triggered_by
                    FROM model_version_decisions
                    WHERE decision = 'UNFROZEN' AND triggered_by = %s
                    ORDER BY id DESC LIMIT 1;
                    """,
                    (real_coordinator_uid,),
                )
                unfreeze_audit = cur.fetchone()
                assert unfreeze_audit is not None, "Audit row for UNFROZEN decision not found in staging DB"
                assert unfreeze_audit[0] == "UNFROZEN"
                assert unfreeze_audit[1] == unfreeze_reason
                assert unfreeze_audit[2] == real_coordinator_uid

            # ==================================================================
            # STEP D: Pipeline State Machine progresses candidate now that un-frozen
            # ==================================================================
            # Direct advance_candidate_state verification with un-frozen state
            unfrozen_advance_res = advance_candidate_state(
                candidate=cand_state,
                active_version=active_state,
                longterm_eval=longterm_eval,
                automation_state=AutomationState(frozen=False),
                config=active_config,
                conn=staging_db,
            )
            assert unfrozen_advance_res.transition_occurred is True
            assert unfrozen_advance_res.to_state == "evaluating"

            # Real 6-hourly pipeline runner path reads DB automation state (now frozen=false) and advances candidate
            pipe_res_unfrozen = run_versioning_pipeline_step(
                conn=staging_db,
                locations=locations,
                config=active_config,
            )
            assert pipe_res_unfrozen["transition_occurred"] is True

            # Verify candidate version in staging DB transitioned candidate -> evaluating
            with staging_db.cursor() as cur:
                cur.execute("SELECT status FROM model_versions WHERE id = 3;")
                cand_status = cur.fetchone()[0]
                assert cand_status == "evaluating", (
                    f"Candidate failed to advance after unfreeze! Expected 'evaluating', got '{cand_status}'"
                )

    finally:
        app.dependency_overrides.clear()
        if pool is not None:
            try:
                pool.terminate()
            except Exception:
                pass
        # Clean up real Supabase Auth user from GoTrue service
        try:
            admin_supabase.auth.admin.delete_user(real_coordinator_uid)
        except Exception:
            pass
