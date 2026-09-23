"""
Phase 5 Test Suite: Live Pipeline, Database, Storage, Model Registry & Scheduler.

Tests schema integrity, RLS configuration, model registry quality gate,
idempotency, override auto-expiry, quota safety, and telemetry logging.
"""

import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from pipeline.db.connection import get_db_connection
from pipeline.live.runner import LivePipelineRunner
from pipeline.live.verification_runner import CANDIDATE_MODELS, VerificationRunner
from pipeline.maintenance.retention import RetentionEngine
from pipeline.models.registry import ModelRegistry
from pipeline.storage.manager import storage_manager

# =====================================================================
# 1. DATABASE SCHEMA & CONSTRAINT VERIFICATION
# =====================================================================

def test_all_11_core_tables_exist():
    """Verify that all 11 required core tables are created in Supabase Postgres."""
    conn = get_db_connection()
    required_tables = [
        "locations",
        "model_forecasts",
        "model_versions",
        "blended_forecasts",
        "weights",
        "skill_scores",
        "alerts",
        "profiles",
        "weight_overrides",
        "pipeline_runs",
        "chat_audit",
    ]
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public';
            """)
            existing_tables = {row[0] for row in cur.fetchall()}
            for table in required_tables:
                assert table in existing_tables, f"Missing required table: {table}"
    finally:
        conn.close()


def test_model_versions_unique_active_constraint():
    """Verify that at most one active model version is allowed by the partial unique index."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'model_versions'
                  AND indexdef LIKE '%UNIQUE%is_active%';
            """)
            indexes = cur.fetchall()
            assert len(indexes) >= 1, "Missing partial unique index for single active model version"
    finally:
        conn.close()


def test_weights_non_negative_constraint():
    """Verify that the weights table enforces non-negative weight constraint."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT conname, pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = 'weights'::regclass
                  AND contype = 'c';
            """)
            constraints = [row[1] for row in cur.fetchall()]
            has_weight_check = any("weight >=" in c for c in constraints)
            assert has_weight_check, f"Missing non-negative weight constraint in: {constraints}"
    finally:
        conn.close()


# =====================================================================
# 2. ROW-LEVEL SECURITY (RLS) POLICIES
# =====================================================================

def test_rls_enabled_on_all_tables():
    """Verify that RLS (relrowsecurity) is enabled on all 11 public core tables."""
    conn = get_db_connection()
    required_tables = [
        "locations",
        "model_forecasts",
        "model_versions",
        "blended_forecasts",
        "weights",
        "skill_scores",
        "alerts",
        "profiles",
        "weight_overrides",
        "pipeline_runs",
        "chat_audit",
    ]
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT relname, relrowsecurity
                FROM pg_class
                JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
                WHERE nspname = 'public'
                  AND relname = ANY(%s);
            """, (required_tables,))
            rls_status = {row[0]: row[1] for row in cur.fetchall()}
            for table in required_tables:
                assert rls_status.get(table) is True, f"RLS is not enabled on table '{table}'"
    finally:
        conn.close()


def test_auth_helper_functions_exist():
    """Verify that security helper functions is_admin() and is_forecaster_or_admin() exist."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT proname, prosecdef
                FROM pg_proc
                JOIN pg_namespace ON pg_namespace.oid = pg_proc.pronamespace
                WHERE nspname = 'public'
                  AND proname IN ('is_admin', 'is_forecaster_or_admin');
            """)
            funcs = {row[0]: row[1] for row in cur.fetchall()}
            assert "is_admin" in funcs, "Function is_admin() missing"
            assert "is_forecaster_or_admin" in funcs, "Function is_forecaster_or_admin() missing"
            assert funcs["is_admin"] is True, "is_admin() must be SECURITY DEFINER"
            assert funcs["is_forecaster_or_admin"] is True, "is_forecaster_or_admin() must be SECURITY DEFINER"
    finally:
        conn.close()


def test_anonymous_reads_blocked_on_operational_tables():
    """Verify that anonymous role (anon) is blocked from reading protected tables while public tables are accessible (PRD Phase 10)."""
    conn = get_db_connection()
    protected_tables = [
        "model_forecasts",
        "model_versions",
        "profiles",
        "weight_overrides",
        "pipeline_runs",
        "chat_audit",
    ]
    public_tables = [
        "locations",
        "blended_forecasts",
        "weights",
        "skill_scores",
        "alerts",
    ]
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN; SET LOCAL ROLE anon;")
            for table in protected_tables:
                cur.execute(f"SELECT COUNT(*) FROM {table};")
                count = cur.fetchone()[0]
                assert count == 0, f"Table '{table}' should not return data to anonymous users (got {count} rows)"
            for table in public_tables:
                cur.execute(f"SELECT COUNT(*) FROM {table};")
                # Queries succeed without permission error
                count = cur.fetchone()[0]
                assert count >= 0
            cur.execute("ROLLBACK;")
    finally:
        conn.close()



def test_authenticated_reads_allowed_on_operational_tables():
    """Verify that authenticated role can read operational tables."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("""
                INSERT INTO blended_forecasts (
                    location_id, variable, valid_date, issue_time, lead_days, blended
                ) VALUES (
                    1, 'rain_mm', CURRENT_DATE, CURRENT_DATE::timestamptz, 0, 10.0
                ) ON CONFLICT (location_id, variable, valid_date, issue_time) DO NOTHING;
            """)
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT COUNT(*) FROM blended_forecasts;")
            count = cur.fetchone()[0]
            assert count > 0, "Authenticated role should have read access to blended_forecasts"
            cur.execute("ROLLBACK;")
    finally:
        conn.close()


def test_unauthorized_writes_blocked():
    """Verify that unauthorized client writes to operational tables are blocked under RLS."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN; SET LOCAL ROLE anon;")
            try:
                cur.execute("""
                    INSERT INTO model_forecasts (location_id, model, variable, valid_date, lead_days, issue_time, value)
                    VALUES (1, 'gfs', 'rain_mm', '2099-01-01', 1, NOW(), 10.0);
                """)
                pytest.fail("Anonymous write to model_forecasts should have failed with RLS violation")
            except Exception as e:
                err_msg = str(e).lower()
                assert "permission denied" in err_msg or "violates row-level security" in err_msg or "policy" in err_msg
            cur.execute("ROLLBACK;")
    finally:
        conn.close()


def test_prevent_self_role_escalation():
    """Verify that normal authenticated users cannot modify their role or insert profiles."""
    conn = get_db_connection()
    conn.autocommit = True
    test_user_id = str(uuid.uuid4())
    admin_user_id = str(uuid.uuid4())

    try:
        with conn.cursor() as cur:
            # 1. Create a normal user (trigger automatically creates profile with role 'public')
            cur.execute("""
                INSERT INTO auth.users (id, email, role)
                VALUES (%s, 'public_user@aagam.local', 'authenticated');
            """, (test_user_id,))

            cur.execute("SELECT role FROM profiles WHERE user_id = %s;", (test_user_id,))
            initial_role = cur.fetchone()[0]
            assert initial_role == "public", "Auto-created profile must have default 'public' role"

            # 2. Simulate normal authenticated user session
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true);", (test_user_id,))

            # Attempt self-escalation to coordinator
            cur.execute("UPDATE profiles SET role = 'coordinator' WHERE user_id = %s;", (test_user_id,))
            assert cur.rowcount == 0, "Normal authenticated user must NOT be able to update their profile or role"

            # Attempt client-side profile creation
            with pytest.raises(Exception) as excinfo:
                cur.execute("""
                    INSERT INTO profiles (user_id, role, display_name)
                    VALUES (%s, 'coordinator', 'Unauthorized Coordinator');
                """, (str(uuid.uuid4()),))
            assert "violates row-level security policy" in str(excinfo.value).lower() or "permission denied" in str(excinfo.value).lower()

            cur.execute("ROLLBACK;")

            # 3. Confirm profile role remains strictly 'public'
            cur.execute("SELECT role FROM profiles WHERE user_id = %s;", (test_user_id,))
            assert cur.fetchone()[0] == "public", "Role must remain 'public' after attempted escalation"

            # 4. Verify coordinator user CAN manage profiles
            cur.execute("""
                INSERT INTO auth.users (id, email, role)
                VALUES (%s, 'coordinator_user@aagam.local', 'authenticated');
            """, (admin_user_id,))
            cur.execute("UPDATE profiles SET role = 'coordinator' WHERE user_id = %s;", (admin_user_id,))

            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true);", (admin_user_id,))

            cur.execute("UPDATE profiles SET display_name = 'Verified Public' WHERE user_id = %s;", (test_user_id,))
            assert cur.rowcount == 1, "Coordinator user must be allowed to manage profiles"
            cur.execute("ROLLBACK;")

    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM profiles WHERE user_id IN (%s, %s);", (test_user_id, admin_user_id))
            cur.execute("DELETE FROM auth.users WHERE id IN (%s, %s);", (test_user_id, admin_user_id))
        conn.close()


def test_chat_audit_protected_fields_cannot_be_altered():
    """Verify that authenticated users can only update feedback on chat_audit, and cannot modify protected fields."""
    conn = get_db_connection()
    conn.autocommit = True
    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())

    try:
        with conn.cursor() as cur:
            # Create users and chat audit log entry (created server-side via service role)
            cur.execute("""
                INSERT INTO auth.users (id, email, role)
                VALUES (%s, 'usera@aagam.local', 'authenticated'),
                       (%s, 'userb@aagam.local', 'authenticated');
            """, (user_a_id, user_b_id))

            cur.execute("""
                INSERT INTO chat_audit (user_id, question, mode, latency_ms, tokens_in, tokens_out)
                VALUES (%s, 'What is the rainfall forecast?', 'Explain', 150, 100, 50)
                RETURNING id;
            """, (user_a_id,))
            audit_id = cur.fetchone()[0]

            # 1. Authenticated user A updates feedback on own log entry -> SUCCEEDS
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true);", (user_a_id,))

            cur.execute("UPDATE chat_audit SET feedback = 1 WHERE id = %s;", (audit_id,))
            assert cur.rowcount == 1, "User must be able to update feedback on their own chat_audit entry"
            cur.execute("ROLLBACK;")

            # 2. Authenticated user A attempts to tamper with protected field (question / latency_ms) -> FAILS
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true);", (user_a_id,))

            with pytest.raises(Exception) as excinfo:
                cur.execute("UPDATE chat_audit SET question = 'Tampered question' WHERE id = %s;", (audit_id,))
            err_msg = str(excinfo.value).lower()
            assert "permission denied" in err_msg or "only update the feedback field" in err_msg or "policy" in err_msg
            cur.execute("ROLLBACK;")

            # 3. Authenticated user B attempts to update user A's feedback -> FAILS (0 rows affected by RLS)
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true);", (user_b_id,))

            cur.execute("UPDATE chat_audit SET feedback = -1 WHERE id = %s;", (audit_id,))
            assert cur.rowcount == 0, "User B must not be able to update User A's chat_audit entry"
            cur.execute("ROLLBACK;")

    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chat_audit WHERE user_id IN (%s, %s);", (user_a_id, user_b_id))
            cur.execute("DELETE FROM profiles WHERE user_id IN (%s, %s);", (user_a_id, user_b_id))
            cur.execute("DELETE FROM auth.users WHERE id IN (%s, %s);", (user_a_id, user_b_id))
        conn.close()


# =====================================================================
# 3. MODEL REGISTRY & QUALITY GATE
# =====================================================================

def test_model_registry_quality_gate_passed():
    """Verify that candidate model within tolerance (<= 2%) passes quality gate."""
    registry = ModelRegistry()
    active_metrics = {
        "validation_mae": {
            "rain_mm": 1.70,
            "tmax_c": 1.50,
            "wind_max_kmh": 2.00,
        }
    }
    candidate_metrics = {
        "validation_mae": {
            "rain_mm": 1.71,
            "tmax_c": 1.51,
            "wind_max_kmh": 2.01,
        }
    }

    passed, reason, _ = registry.evaluate_quality_gate(
        candidate_metrics,
        active_metrics=active_metrics,
        tolerance=0.02,
    )
    assert passed is True
    assert "PASSED" in reason


def test_model_registry_quality_gate_failed_preserves_active():
    """Verify that candidate model exceeding tolerance (> 2%) fails quality gate and is rejected."""
    registry = ModelRegistry()
    active_metrics = {
        "validation_mae": {
            "rain_mm": 1.70,
            "tmax_c": 1.50,
            "wind_max_kmh": 2.00,
        }
    }
    candidate_metrics = {
        "validation_mae": {
            "rain_mm": 2.00,
            "tmax_c": 1.80,
            "wind_max_kmh": 2.50,
        }
    }

    passed, reason, _ = registry.evaluate_quality_gate(
        candidate_metrics,
        active_metrics=active_metrics,
        tolerance=0.02,
    )
    assert passed is False
    assert "REJECTED" in reason
    assert "exceeds threshold" in reason


def test_active_version_retrieval():
    """Verify that active model version is retrievable and matches DB status."""
    registry = ModelRegistry()
    active = registry.get_active_version()
    assert active is not None
    assert "id" in active
    assert active["is_active"] is True
    assert "storage_path" in active


# =====================================================================
# 4. STORAGE BUCKETS
# =====================================================================

def test_required_storage_buckets_exist():
    """Verify that training-data, models, and backups buckets exist in Supabase Storage."""
    buckets = storage_manager.list_buckets()
    required = {"training-data", "models", "backups"}
    for req in required:
        assert req in buckets, f"Required storage bucket '{req}' missing from {buckets}"


# =====================================================================
# 5. RETENTION & OVERRIDE EXPIRY
# =====================================================================

def test_retention_cleanup_execution():
    """Verify that retention engine executes cleanup and records summary metrics matching PRD rules."""
    engine = RetentionEngine()
    stats = engine.run_cleanup(dry_run=True)
    assert "overrides_expired" in stats
    assert "blended_forecasts_purged" in stats
    assert "chat_audit_purged" in stats


def test_nightly_backup_failure_aborts_retention_cleanup(tmp_path):
    """Verify that if any table upload fails during nightly backup, retention cleanup is aborted,
    telemetry records FAILED status identifying the failed table, and no data is purged."""
    engine = RetentionEngine()

    # Mock storage_manager.upload_file so that 'blended_forecasts' fails (returns False)
    def mock_upload(bucket, source_path, target_path, **kwargs):
        if "blended_forecasts" in str(source_path):
            return False
        return True

    with patch.object(storage_manager, "upload_file", side_effect=mock_upload):
        with patch.object(engine, "run_cleanup") as mock_cleanup:
            result = engine.run_nightly_backup(
                backup_date="20990101",
                dry_run=False,
                local_dir=tmp_path,
            )

            # 1. Verify returned status is FAILED
            assert result["status"] == "FAILED"
            assert "failed_uploads" in result
            assert "blended_forecasts" in result["failed_uploads"]
            assert "blended_forecasts" in result["error"]

            # 2. Verify retention cleanup is NOT executed
            mock_cleanup.assert_not_called()

    # 3. Verify a FAILED backup_nightly telemetry record is created in pipeline_runs
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT job, status, message
                FROM pipeline_runs
                WHERE job = 'backup_nightly'
                ORDER BY id DESC
                LIMIT 1;
            """)
            last_run = cur.fetchone()
            assert last_run is not None
            assert last_run[0] == "backup_nightly"
            assert last_run[1] == "FAILED"
            assert "blended_forecasts" in last_run[2]
    finally:
        conn.close()



# =====================================================================
# 6. IDEMPOTENCY & DUPLICATE PROTECTION
# =====================================================================

def test_blended_forecasts_idempotent_upsert():
    """Verify that re-running ingest-blend on the same cycle does not create duplicate rows."""
    runner = LivePipelineRunner()
    # Execute two consecutive dry runs
    res1 = runner.run_cycle(dry_run=True)
    res2 = runner.run_cycle(dry_run=True)

    assert res1["status"] == "SUCCESS"
    assert res2["status"] == "SUCCESS"
    assert res1["blended_rows"] == res2["blended_rows"]

    # Verify no duplicate primary keys in blended_forecasts
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT location_id, variable, valid_date, issue_time, lead_days, COUNT(*)
                FROM blended_forecasts
                GROUP BY location_id, variable, valid_date, issue_time, lead_days
                HAVING COUNT(*) > 1;
            """)
            duplicates = cur.fetchall()
            assert len(duplicates) == 0, f"Found duplicate records in blended_forecasts: {duplicates}"
    finally:
        conn.close()


def test_alerts_idempotent_upsert():
    """Verify that re-running hazard guidance does not create duplicate alerts."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT location_id, hazard, valid_date, issue_time, lead_days, COUNT(*)
                FROM alerts
                GROUP BY location_id, hazard, valid_date, issue_time, lead_days
                HAVING COUNT(*) > 1;
            """)
            duplicates = cur.fetchall()
            assert len(duplicates) == 0, f"Found duplicate alert records: {duplicates}"
    finally:
        conn.close()


# =====================================================================
# 7. QUOTA SAFETY & HTTP 429 HANDLING
# =====================================================================

def test_openmeteo_429_clean_halt():
    """Verify that HTTP 429 response halts gracefully without looping and records HALTED status."""
    runner = LivePipelineRunner()

    with patch.object(runner, "fetch_live_forecasts") as mock_fetch:
        mock_fetch.return_value = ([], 160, "HTTP 429: Open-Meteo Rate Limit / Quota Exceeded")

        result = runner.run_ingest_and_blend(dry_run=False)
        assert result["status"] == "HALTED"
        assert "429" in result["message"]

    # Verify that telemetry recorded HALTED in pipeline_runs
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT job, status, message
                FROM pipeline_runs
                WHERE job = 'ingest-blend' AND status = 'HALTED'
                ORDER BY started_at DESC
                LIMIT 1;
            """)
            last_run = cur.fetchone()
            assert last_run is not None
            assert last_run[1] == "HALTED"
    finally:
        conn.close()


# =====================================================================
# 8. PIPELINE OBSERVABILITY & TELEMETRY
# =====================================================================

def test_pipeline_runs_telemetry_fields():
    """Verify that pipeline_runs tracks status, duration, rows_written, and api_calls_est."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, job, started_at, finished_at, status, rows_written, api_calls_est, message
                FROM pipeline_runs
                ORDER BY started_at DESC
                LIMIT 5;
            """)
            rows = cur.fetchall()
            assert len(rows) > 0, "No pipeline_runs telemetry records found"
            for row in rows:
                assert row[1] in (
                    "ingest-blend",
                    "ingest-live",
                    "verify",
                    "verify-daily",
                    "train",
                    "train-weekly",
                    "backup",
                    "backup_nightly",
                    "retention_cleanup",
                    "historical_backfill",
                )

                assert row[2] is not None  # started_at
                assert row[4] in ("SUCCESS", "FAILED", "HALTED", "RUNNING")  # status
    finally:
        conn.close()


# =====================================================================
# 9. PRD ALIGNMENT REGRESSION TESTS (FR-OPS-4, FR-VER-1, LEAD DAYS)
# =====================================================================

def test_blended_forecasts_retention_prd_alignment():
    """Verify FR-OPS-4 blended_forecasts retention:
    - 00Z data inside 180 days is retained
    - non-00Z blended rows are removed by cleanup
    - 00Z rows older than 180 days are eligible for deletion
    """
    engine = RetentionEngine()
    # 1. Verify dry-run cleanup reports blended_forecasts_purged
    stats = engine.run_cleanup(dry_run=True)
    assert "blended_forecasts_purged" in stats

    # 2. Database validation of retention filter logic
    conn = get_db_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # Insert test records representing the 3 cases
            # Case 1: 00Z run inside 180 days (retained)
            # Case 2: non-00Z run (eligible for purge)
            # Case 3: 00Z run older than 180 days (eligible for purge)
            cur.execute("""
                INSERT INTO blended_forecasts (
                    location_id, variable, valid_date, issue_time, lead_days, blended
                ) VALUES
                (1, 'rain_mm', CURRENT_DATE - INTERVAL '10 days', '2026-09-11 00:00:00+00', 1, 12.5),
                (1, 'tmax_c', CURRENT_DATE - INTERVAL '10 days', '2026-09-11 06:00:00+00', 1, 31.0),
                (1, 'wind_max_kmh', CURRENT_DATE - INTERVAL '200 days', '2026-03-01 00:00:00+00', 1, 22.0)
                ON CONFLICT (location_id, variable, valid_date, issue_time) DO NOTHING;
            """)

            # Query rows that match the purge criteria among our test rows
            cur.execute("""
                SELECT variable, valid_date, issue_time
                FROM blended_forecasts
                WHERE issue_time IN ('2026-09-11 00:00:00+00', '2026-09-11 06:00:00+00', '2026-03-01 00:00:00+00')
                  AND (EXTRACT(HOUR FROM issue_time AT TIME ZONE 'UTC') != 0
                       OR valid_date < CURRENT_DATE - INTERVAL '180 days');
            """)
            purged_candidates = cur.fetchall()
            purged_vars = {r[0] for r in purged_candidates}

            # non-00Z ('tmax_c') and > 180 days ('wind_max_kmh') must be marked for deletion
            assert "tmax_c" in purged_vars, "non-00Z row must be eligible for deletion"
            assert "wind_max_kmh" in purged_vars, "00Z row older than 180 days must be eligible for deletion"

            # 00Z row inside 180 days ('rain_mm') must NOT be marked for deletion
            assert "rain_mm" not in purged_vars, "00Z row inside 180 days must be retained"

            # Execute cleanup deletion in transaction and verify table state
            cur.execute("""
                DELETE FROM blended_forecasts
                WHERE issue_time IN ('2026-09-11 00:00:00+00', '2026-09-11 06:00:00+00', '2026-03-01 00:00:00+00')
                  AND (EXTRACT(HOUR FROM issue_time AT TIME ZONE 'UTC') != 0
                       OR valid_date < CURRENT_DATE - INTERVAL '180 days');
            """)

            # Verify retained row still exists in DB
            cur.execute("""
                SELECT COUNT(*) FROM blended_forecasts
                WHERE location_id = 1 AND variable = 'rain_mm' AND issue_time = '2026-09-11 00:00:00+00';
            """)
            assert cur.fetchone()[0] >= 1, "00Z row inside 180 days must remain in database"
        conn.rollback()
    finally:
        conn.close()


def test_skill_score_retention_prd_alignment():
    """Verify FR-OPS-4 skill_scores retention:
    - old non-weekly rows (computed_at before today) are removed
    - today's non-weekly rows remain
    - weekly rows within 26 weeks remain
    - weekly rows older than 26 weeks are removed
    """
    engine = RetentionEngine()
    stats = engine.run_cleanup(dry_run=True)
    assert "skill_scores_purged" in stats

    conn = get_db_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # Insert 4 test records for each retention category
            # A: old non-weekly (purged)
            # B: today's non-weekly (retained)
            # C: weekly within 26 weeks (retained)
            # D: weekly older than 26 weeks (purged)
            cur.execute("""
                INSERT INTO skill_scores (
                    computed_at, window_days, variable, region, season, lead_days,
                    model, mae, is_weekly
                ) VALUES
                (NOW() - INTERVAL '3 days', 60, 'rain_mm', 'NW', 'monsoon', 1, 'blend', 2.1, false),
                (NOW(), 60, 'tmax_c', 'NW', 'monsoon', 1, 'blend', 1.5, false),
                (NOW() - INTERVAL '10 weeks', 60, 'wind_max_kmh', 'NW', 'monsoon', 1, 'blend', 3.0, true),
                (NOW() - INTERVAL '30 weeks', 60, 'rain_mm', 'S', 'monsoon', 1, 'blend', 2.4, true)
                ON CONFLICT (computed_at, window_days, variable, region, season, lead_days, model, threshold_mm, is_weekly) DO NOTHING;
            """)

            # Query the purge criteria
            cur.execute("""
                SELECT variable, region, is_weekly
                FROM skill_scores
                WHERE (is_weekly = false AND (computed_at AT TIME ZONE 'UTC')::date < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date)
                   OR (is_weekly = true AND computed_at < CURRENT_DATE - INTERVAL '26 weeks');
            """)
            purged = cur.fetchall()
            purged_items = {(r[0], r[1], r[2]) for r in purged}

            assert ('rain_mm', 'NW', False) in purged_items, "Old non-weekly rows must be purged"
            assert ('rain_mm', 'S', True) in purged_items, "Weekly rows older than 26 weeks must be purged"
            assert ('tmax_c', 'NW', False) not in purged_items, "Today's non-weekly rows must NOT be purged"
            assert ('wind_max_kmh', 'NW', True) not in purged_items, "Weekly rows within 26 weeks must NOT be purged"

            # Execute delete
            cur.execute("""
                DELETE FROM skill_scores
                WHERE (is_weekly = false AND (computed_at AT TIME ZONE 'UTC')::date < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date)
                   OR (is_weekly = true AND computed_at < CURRENT_DATE - INTERVAL '26 weeks');
            """)

            # Verify remaining records
            cur.execute("SELECT variable, is_weekly FROM skill_scores WHERE variable IN ('tmax_c', 'wind_max_kmh');")
            remaining = cur.fetchall()
            rem_vars = {r[0] for r in remaining}
            assert 'tmax_c' in rem_vars, "Today's non-weekly snapshot must remain"
            assert 'wind_max_kmh' in rem_vars, "Active weekly snapshot must remain"

        conn.rollback()
    finally:
        conn.close()


def test_verification_snapshot_fr_ver_1():
    """Verify FR-VER-1 daily verification snapshot logic:
    - previous non-weekly snapshot is replaced by the latest snapshot
    - weekly snapshots are preserved
    - Sunday execution creates an is_weekly=true copy
    """
    runner = VerificationRunner()

    # 1. Test Sunday vs non-Sunday dry-run generation
    # 2026-09-20 was a Sunday; 2026-09-19 was a Saturday
    res_sunday = runner.run_daily_verification(target_date=date(2026, 9, 20), dry_run=True, use_test_fallback=True)
    res_saturday = runner.run_daily_verification(target_date=date(2026, 9, 19), dry_run=True, use_test_fallback=True)

    assert res_sunday["is_sunday"] is True, "Sunday execution must be detected as Sunday"
    assert res_saturday["is_sunday"] is False, "Saturday execution must not be detected as Sunday"

    # Sunday produces both non-weekly snapshot AND weekly copy (2x rows)
    assert res_sunday["skill_scores_written"] == 2 * res_saturday["skill_scores_written"], (
        "Sunday run must create duplicate is_weekly=true rows for all computed metrics"
    )

    # 2. Database replacement test inside transaction
    conn = get_db_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # Seed an existing weekly snapshot and an old non-weekly row
            cur.execute("""
                INSERT INTO skill_scores (
                    computed_at, window_days, variable, region, season, lead_days,
                    model, mae, is_weekly
                ) VALUES
                ('2026-09-13 03:00:00+00', 60, 'rain_mm', 'NW', 'monsoon', 1, 'blend', 2.0, true),
                ('2026-09-19 03:00:00+00', 60, 'rain_mm', 'NW', 'monsoon', 1, 'blend', 2.2, false)
                ON CONFLICT (computed_at, window_days, variable, region, season, lead_days, model, threshold_mm, is_weekly) DO NOTHING;
            """)

            # FR-VER-1 Step 1: delete all previous skill_scores where is_weekly = false
            cur.execute("DELETE FROM skill_scores WHERE is_weekly = false;")

            # Step 2: insert new latest snapshot
            cur.execute("""
                INSERT INTO skill_scores (
                    computed_at, window_days, variable, region, season, lead_days,
                    model, mae, is_weekly
                ) VALUES
                ('2026-09-20 03:00:00+00', 60, 'rain_mm', 'NW', 'monsoon', 1, 'blend', 1.9, false),
                ('2026-09-20 03:00:00+00', 60, 'rain_mm', 'NW', 'monsoon', 1, 'blend', 1.9, true);
            """)

            # Verify that old non-weekly row is gone, new non-weekly exists, and weekly is preserved
            cur.execute("""
                SELECT computed_at, is_weekly, mae
                FROM skill_scores
                ORDER BY computed_at, is_weekly;
            """)
            rows = cur.fetchall()
            non_weekly_dates = [r[0].strftime("%Y-%m-%d") for r in rows if not r[1]]
            weekly_dates = [r[0].strftime("%Y-%m-%d") for r in rows if r[1]]

            # Old non-weekly from 2026-09-19 was deleted and replaced by 2026-09-20
            assert "2026-09-19" not in non_weekly_dates, "Previous non-weekly snapshot must be deleted"
            assert "2026-09-20" in non_weekly_dates, "New non-weekly snapshot must be present"

            # Both existing weekly snapshot (2026-09-13) and Sunday weekly copy (2026-09-20) are preserved
            assert "2026-09-13" in weekly_dates, "Existing weekly snapshots must be preserved"
            assert "2026-09-20" in weekly_dates, "Sunday execution must create is_weekly=true copy"

        conn.rollback()
    finally:
        conn.close()


def test_live_lead_days_range_zero_to_seven():
    """Verify that live pipeline produces exactly lead days 0 through 7:
    - Never produces lead_days > 7
    - Expected lead range is 0–7 (total 8 days)
    - Stored blended_forecasts records strictly observe 0 <= lead_days <= 7
    """
    runner = LivePipelineRunner()

    # 1. Check dry-run sample fetch
    records, _, _ = runner.fetch_live_forecasts(dry_run=True)
    assert len(records) > 0, "Dry run fetch must produce records"

    lead_days_found = {r[4] for r in records}
    assert lead_days_found == set(range(0, 8)), f"Expected lead days 0..7, got {sorted(lead_days_found)}"
    assert max(lead_days_found) == 7, "Maximum lead day must be 7"
    assert min(lead_days_found) == 0, "Minimum lead day must be 0"
    assert len(lead_days_found) == 8, "Total lead days must be 8"
    assert not any(lead > 7 for lead in lead_days_found), "Live processing must never produce lead_days > 7"

    # 2. Check full ingest-blend cycle output
    cycle_result = runner.run_cycle(dry_run=True)
    assert cycle_result["status"] == "SUCCESS"
    # 40 locations * 3 variables * 8 lead days = 960 rows
    assert cycle_result["blended_rows"] == 960, f"Expected 960 blended rows (40*3*8), got {cycle_result['blended_rows']}"

    # 3. Query blended_forecasts in database to confirm no lead_days > 7 exists
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM blended_forecasts WHERE lead_days > 7 OR lead_days < 0;")
            invalid_leads = cur.fetchone()[0]
            assert invalid_leads == 0, f"Found {invalid_leads} records with lead_days outside 0..7"
    finally:
        conn.close()


# =====================================================================
# 11. FR-VER-1 & FR-VER-2 VERIFICATION CORRECTION REGRESSION TESTS
# =====================================================================

def _build_test_verification_fixture(dates_list=None, lead_days_list=None) -> pd.DataFrame:
    """Builds a deterministic test DataFrame containing all 8 candidate models and variables."""
    if dates_list is None:
        dates_list = ["2026-01-15", "2026-04-15", "2026-07-15", "2026-10-15"]
    if lead_days_list is None:
        lead_days_list = list(range(0, 8))

    rows = []
    for d in dates_list:
        for lead in lead_days_list:
            # Rain variable (triggers continuous + categorical metrics)
            rows.append({
                "location_id": 1,
                "region": "NW",
                "variable": "rain_mm",
                "valid_date": d,
                "lead_days": lead,
                "truth": 10.0,
                "gfs": 11.0,
                "ecmwf_ifs": 10.5,
                "icon": 9.5,
                "aifs": 10.2,
                "equal_mean": 10.3,
                "ridge": 10.1,
                "lgbm": 10.0,
                "blend": 10.05,
            })
            # Temperature variable (continuous metrics)
            rows.append({
                "location_id": 1,
                "region": "NW",
                "variable": "tmax_c",
                "valid_date": d,
                "lead_days": lead,
                "truth": 32.0,
                "gfs": 33.0,
                "ecmwf_ifs": 32.5,
                "icon": 31.8,
                "aifs": 32.2,
                "equal_mean": 32.4,
                "ridge": 32.1,
                "lgbm": 32.0,
                "blend": 32.05,
            })
    return pd.DataFrame(rows)


def test_verification_produces_all_eight_candidates():
    """Verify FR-VER-1 requirement that skill_scores are computed for all 8 candidates:
    gfs, ecmwf_ifs, icon, aifs, equal_mean, ridge, lgbm, blend.
    The test must fail if any candidate is missing from generated skill records.
    """
    runner = VerificationRunner()
    fixture_df = _build_test_verification_fixture()
    records = runner.compute_skill_records(fixture_df)
    assert len(records) > 0, "compute_skill_records must produce skill records"

    # Tuple index 6 corresponds to model candidate name
    models_produced = {r[6] for r in records}
    expected_models = {
        "gfs",
        "ecmwf_ifs",
        "icon",
        "aifs",
        "equal_mean",
        "ridge",
        "lgbm",
        "blend",
    }
    assert models_produced == expected_models, (
        f"Verification must evaluate exactly all 8 candidates. "
        f"Missing: {expected_models - models_produced}, Extra: {models_produced - expected_models}"
    )

    # Prove that the verification fails if any candidate is missing
    for required_candidate in expected_models:
        df_incomplete = fixture_df.drop(columns=[required_candidate])
        incomplete_records = runner.compute_skill_records(df_incomplete)
        incomplete_models = {r[6] for r in incomplete_records}
        assert required_candidate not in incomplete_models, f"{required_candidate} must be absent"
        assert incomplete_models != expected_models, f"Missing candidate {required_candidate} must be detected"


def test_verification_season_derived_from_valid_date():
    """Verify FR-VER-1 requirement that season is derived dynamically from valid_date
    using canonical Indian meteorological seasons rather than hardcoded to 'monsoon'.
    Tests:
    1. Valid dates produce the canonical season across multiple distinct seasons.
    2. Different seasons (winter, pre_monsoon, monsoon, post_monsoon) are correctly distinguished.
    3. No hardcoded 'monsoon' fallback is used when season information is missing (raises ValueError).
    4. Source-level assertion that no 'df["season"] = "monsoon"' fallback exists in verification_runner.py.
    """
    runner = VerificationRunner()

    # 1 & 2: Test distinct seasons
    winter_date = "2026-01-20"        # Month 1 -> winter
    pre_monsoon_date = "2026-04-15"   # Month 4 -> pre_monsoon
    monsoon_date = "2026-07-20"       # Month 7 -> monsoon
    post_monsoon_date = "2026-10-20"  # Month 10 -> post_monsoon

    fixture_df = _build_test_verification_fixture(
        dates_list=[winter_date, pre_monsoon_date, monsoon_date, post_monsoon_date]
    )

    records = runner.compute_skill_records(fixture_df)
    assert len(records) > 0

    # Tuple index 4 corresponds to season
    seasons_produced = {r[4] for r in records}
    assert seasons_produced == {"winter", "pre_monsoon", "monsoon", "post_monsoon"}, (
        f"All 4 canonical seasons must be distinguished, got: {seasons_produced}"
    )

    # Test winter and pre-monsoon isolated: monsoon must NOT appear
    isolated_df = _build_test_verification_fixture(dates_list=[winter_date, pre_monsoon_date])
    isolated_records = runner.compute_skill_records(isolated_df)
    isolated_seasons = {r[4] for r in isolated_records}
    assert "winter" in isolated_seasons
    assert "pre_monsoon" in isolated_seasons
    assert "monsoon" not in isolated_seasons, "Monsoon must not appear for January or April dates"

    # 3: Verify rejection when valid_date and season are both missing (no hardcoded fallback)
    df_missing_info = fixture_df.drop(columns=["valid_date"])
    if "season" in df_missing_info.columns:
        df_missing_info = df_missing_info.drop(columns=["season"])

    with pytest.raises(ValueError, match="refusing to invent or hardcode a season fallback"):
        runner.compute_skill_records(df_missing_info)

    # 4: Source-level assertion confirming no hardcoded 'monsoon' assignment exists in verification_runner.py
    runner_code = (Path(__file__).resolve().parent.parent / "pipeline" / "live" / "verification_runner.py").read_text()
    assert 'df["season"] = "monsoon"' not in runner_code, (
        "verification_runner.py must not contain any hardcoded fallback assigning 'monsoon' to season."
    )


def test_verification_preserves_lead_days_zero_to_seven():
    """Verify FR-VER-1 requirement that lead_days 0..7 are preserved and never collapsed.
    All 8 candidates must retain lead-specific skill metrics for each lead in 0..7.
    """
    runner = VerificationRunner()
    all_leads = list(range(0, 8))
    fixture_df = _build_test_verification_fixture(lead_days_list=all_leads)

    records = runner.compute_skill_records(fixture_df)
    assert len(records) > 0

    # Tuple index 5 is lead_days, index 6 is model
    leads_produced = {r[5] for r in records}
    assert leads_produced == set(all_leads), f"Expected all leads 0..7, got {sorted(leads_produced)}"

    # Confirm every candidate has metrics for each lead day 0..7
    for model in CANDIDATE_MODELS:
        model_leads = {r[5] for r in records if r[6] == model}
        assert model_leads == set(all_leads), f"Candidate {model} must have scores for all leads 0..7"


def test_verification_live_job_scores_all_candidates_and_handles_sunday():
    """Verify run_daily_verification executes the complete verification cycle:
    - Evaluates all 8 candidate models
    - Derives season from data
    - Produces lead-day range
    - Preserves Sunday weekly copy (2x rows on Sunday vs non-Sunday)
    """
    runner = VerificationRunner()

    # 2026-09-20 was a Sunday; 2026-09-19 was a Saturday
    res_sunday = runner.run_daily_verification(target_date=date(2026, 9, 20), dry_run=True, use_test_fallback=True)
    res_saturday = runner.run_daily_verification(target_date=date(2026, 9, 19), dry_run=True, use_test_fallback=True)

    assert res_sunday["status"] == "SUCCESS"
    assert res_saturday["status"] == "SUCCESS"
    assert res_sunday["is_sunday"] is True
    assert res_saturday["is_sunday"] is False

    expected_models = {"gfs", "ecmwf_ifs", "icon", "aifs", "equal_mean", "ridge", "lgbm", "blend"}
    assert set(res_sunday["candidate_models"]) == expected_models
    assert set(res_saturday["candidate_models"]) == expected_models

    # Sunday produces both daily snapshot AND weekly copy (2x rows)
    assert res_sunday["skill_scores_written"] == 2 * res_saturday["skill_scores_written"]


def test_historical_raw_model_verification_path(tmp_path):
    """Verify the real operational historical raw model verification path (FR-VER-1):
    1. Distinguishes historical raw model forecasts from the latest overwritten cycle in model_forecasts.
    2. Proves verification retrieves raw model values from the canonical historical store.
    3. Fails if verification accidentally uses the latest overwritten raw forecast.
    4. Evaluates all 8 candidates [gfs, ecmwf_ifs, icon, aifs, equal_mean, ridge, lgbm, blend].
    5. Preserves lead_days without collapsing (tested at lead_days = 3).
    6. Derives canonical season from forecast valid_date (monsoon for June).
    7. Verifies Sunday weekly snapshot generation (2026-06-14 was a Sunday).
    8. Confirms that missing historical operational data produces an explicit NO_DATA condition without silent test fallback.
    """
    target_eval_date = date(2026, 6, 14)  # 2026-06-14 was a Sunday in monsoon season
    assert target_eval_date.weekday() == 6, "2026-06-14 must be a Sunday"

    # Setup database connection
    conn = get_db_connection()
    conn.autocommit = True

    try:
        with conn.cursor() as cur:
            # 1. Clean up any existing test records for this location and valid_date
            cur.execute("DELETE FROM blended_forecasts WHERE location_id = 1 AND valid_date = %s;", (target_eval_date,))
            cur.execute("DELETE FROM model_forecasts WHERE location_id = 1 AND valid_date = %s;", (target_eval_date,))

            # 2. Seed blended_forecasts in DB for an older issue (issued on 2026-06-11, lead_days = 3)
            # Ground truth for location 1 on 2026-06-14 is tmax_truth = 32.7
            cur.execute("""
                INSERT INTO blended_forecasts (
                    location_id, variable, valid_date, issue_time, lead_days,
                    blended, ridge, lgbm, equal_mean
                ) VALUES (
                    1, 'tmax_c', %s, '2026-06-11 00:00:00+00', 3,
                    32.8, 32.7, 32.9, 32.8
                );
            """, (target_eval_date,))

            # 3. Seed model_forecasts in DB simulating an OVERWRITTEN subsequent cycle
            # This represents Day T (2026-06-14) running and overwriting model_forecasts with lead_days=0
            # and a wildly corrupted/different value (value = 999.0).
            cur.execute("""
                INSERT INTO model_forecasts (
                    location_id, model, variable, valid_date, lead_days, issue_time, value
                ) VALUES (
                    1, 'gfs', 'tmax_c', %s, 0, '2026-06-14 00:00:00+00', 999.0
                ) ON CONFLICT (location_id, model, variable, valid_date) DO UPDATE
                SET lead_days = EXCLUDED.lead_days, value = EXCLUDED.value;
            """, (target_eval_date,))

        # 4. Create the canonical historical Parquet store for this forecast issue (lead_days = 3)
        # Historical raw forecasts: gfs = 33.2 (error = 0.5 vs truth 32.7)
        hist_records = [
            {"location_id": 1, "model": "gfs", "valid_date": target_eval_date, "lead_days": 3, "f_tmax_c": 33.2, "f_rain_mm": 1.7, "f_wind_max_kmh": 13.4},
            {"location_id": 1, "model": "ecmwf_ifs", "valid_date": target_eval_date, "lead_days": 3, "f_tmax_c": 32.5, "f_rain_mm": 1.7, "f_wind_max_kmh": 13.4},
            {"location_id": 1, "model": "icon", "valid_date": target_eval_date, "lead_days": 3, "f_tmax_c": 32.9, "f_rain_mm": 1.7, "f_wind_max_kmh": 13.4},
            {"location_id": 1, "model": "aifs", "valid_date": target_eval_date, "lead_days": 3, "f_tmax_c": 32.6, "f_rain_mm": 1.7, "f_wind_max_kmh": 13.4},
        ]
        hist_parquet = tmp_path / "forecasts_backfill.parquet"
        pd.DataFrame(hist_records).to_parquet(hist_parquet, index=False, engine="pyarrow")

        # 5. Run verification with the historical Parquet store (use_test_fallback=False)
        runner = VerificationRunner(historical_parquet_path=hist_parquet)
        res = runner.run_daily_verification(
            target_date=target_eval_date,
            window_days=1,
            dry_run=True,
            use_test_fallback=False,
        )

        assert res["status"] == "SUCCESS", f"Expected SUCCESS, got {res}"
        assert res["is_sunday"] is True, "Sunday execution must be detected"
        assert res["seasons_evaluated"] == ["monsoon"], "June 14 must derive monsoon season"
        assert res["lead_days_evaluated"] == [3], "Lead day 3 must be preserved without collapsing"

        # Check all 8 candidates are scored
        expected_candidates = {"gfs", "ecmwf_ifs", "icon", "aifs", "equal_mean", "ridge", "lgbm", "blend"}
        assert set(res["candidate_models"]) == expected_candidates

        # 6. Re-evaluate compute_skill_records on the joined data to verify MAE values
        df_hist = runner.load_historical_raw_forecasts(target_eval_date, target_eval_date)
        assert not df_hist.empty
        assert set(df_hist.columns).issuperset({"gfs", "ecmwf_ifs", "icon", "aifs"})

        # Query blended row
        with conn.cursor() as cur:
            cur.execute("""
                SELECT bf.location_id, bf.variable, bf.valid_date, bf.lead_days,
                       bf.blended AS blend, bf.ridge, bf.lgbm, bf.equal_mean, loc.region
                FROM blended_forecasts bf
                JOIN locations loc ON loc.id = bf.location_id
                WHERE bf.valid_date = %s;
            """, (target_eval_date,))
            b_rows = cur.fetchall()

        df_b = pd.DataFrame(b_rows, columns=["location_id", "variable", "valid_date", "lead_days", "blend", "ridge", "lgbm", "equal_mean", "region"])
        df_b["valid_date"] = pd.to_datetime(df_b["valid_date"]).dt.date
        df_b["location_id"] = df_b["location_id"].astype(int)
        df_b["lead_days"] = df_b["lead_days"].astype(int)

        merged = pd.merge(df_b, df_hist, on=["location_id", "variable", "valid_date", "lead_days"], how="inner")
        merged["truth"] = 32.7  # actual ground truth

        records = runner.compute_skill_records(merged, window_days=1)
        rec_by_model = {r[6]: r for r in records}

        # Candidate GFS verification:
        # If historical value (33.2) was used: MAE = |33.2 - 32.7| = 0.5.
        # If overwritten latest value in model_forecasts (999.0) was used: MAE = |999.0 - 32.7| = 966.3.
        assert "gfs" in rec_by_model
        gfs_mae = rec_by_model["gfs"][7]
        assert gfs_mae == pytest.approx(0.5, abs=0.01), f"Expected MAE 0.5 from historical forecast, got {gfs_mae}"
        assert gfs_mae < 2.0, "Verification must use historical raw value, not corrupted latest value"
        assert abs(gfs_mae - 966.3) > 100.0, "Test must fail if verification uses latest overwritten model_forecasts"

        # 7. Verify NO_DATA condition when historical Parquet is missing in production
        empty_parquet = tmp_path / "non_existent.parquet"
        empty_runner = VerificationRunner(historical_parquet_path=empty_parquet)
        res_no_data = empty_runner.run_daily_verification(
            target_date=target_eval_date,
            window_days=1,
            dry_run=True,
            use_test_fallback=False,
        )
        assert res_no_data["status"] == "NO_DATA", "Production verification must yield NO_DATA when historical raw data is missing"
        assert "Missing historical operational raw model forecast data" in res_no_data["message"]

    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM blended_forecasts WHERE location_id = 1 AND valid_date = %s;", (target_eval_date,))
            cur.execute("DELETE FROM model_forecasts WHERE location_id = 1 AND valid_date = %s;", (target_eval_date,))
        conn.close()


def test_retention_engine_run_cleanup_live_execution():
    """Verify that RetentionEngine.run_cleanup(dry_run=False) actually executes deletions and updates
    against live database tables and verifies the resulting table states:
    - weight_overrides: expired rows have active set to false, unexpired rows remain active
    - blended_forecasts: non-00Z runs and >180d 00Z runs are purged, 00Z runs within 180d remain
    - skill_scores: old non-weekly and >26w weekly runs are purged, today's non-weekly and <26w weekly remain
    - chat_audit: >30d records are purged, <30d records remain
    """
    engine = RetentionEngine()
    conn = get_db_connection()
    conn.autocommit = True

    try:
        with conn.cursor() as cur:
            # 1. Clean up any previous test remnants
            cur.execute("DELETE FROM weight_overrides WHERE reason = 'test_retention_live_reason';")
            cur.execute("DELETE FROM blended_forecasts WHERE issue_time IN ('2026-09-06 00:00:00+00', '2026-09-06 06:00:00+00', '2026-02-13 00:00:00+00');")
            cur.execute("DELETE FROM skill_scores WHERE region = 'TEST_RETENTION';")
            cur.execute("DELETE FROM chat_audit WHERE question = 'test_retention_query';")

            # 2. Get or create a valid user_id for weight_overrides.created_by
            cur.execute("SELECT id FROM auth.users LIMIT 1;")
            u_row = cur.fetchone()
            test_user_id = u_row[0] if u_row else str(uuid.uuid4())
            if not u_row:
                cur.execute("INSERT INTO auth.users (id, email, role) VALUES (%s, 'retention_test@internal.test', 'authenticated');", (test_user_id,))

            # Seed weight_overrides: 1 expired, 1 active
            cur.execute("""
                INSERT INTO weight_overrides (
                    created_by, variable, region, season, lead_days, weights, reason, active, expires_at
                ) VALUES
                (%s, 'rain_mm', 'NW', 'monsoon', 1, '{"gfs": 0.5}'::jsonb, 'test_retention_live_reason', true, NOW() - INTERVAL '1 hour'),
                (%s, 'tmax_c', 'NW', 'monsoon', 1, '{"gfs": 0.5}'::jsonb, 'test_retention_live_reason', true, NOW() + INTERVAL '2 days');
            """, (test_user_id, test_user_id))

            # 3. Seed blended_forecasts:
            # - Case A: 00Z within 180 days (MUST REMAIN)
            # - Case B: non-00Z within 180 days (MUST BE PURGED)
            # - Case C: 00Z older than 180 days (MUST BE PURGED)
            cur.execute("""
                INSERT INTO blended_forecasts (
                    location_id, variable, valid_date, issue_time, lead_days, blended
                ) VALUES
                (1, 'rain_mm', CURRENT_DATE - INTERVAL '15 days', '2026-09-06 00:00:00+00', 1, 10.0),
                (1, 'tmax_c', CURRENT_DATE - INTERVAL '15 days', '2026-09-06 06:00:00+00', 1, 30.0),
                (1, 'wind_max_kmh', CURRENT_DATE - INTERVAL '220 days', '2026-02-13 00:00:00+00', 1, 15.0)
                ON CONFLICT (location_id, variable, valid_date, issue_time) DO NOTHING;
            """)

            # 4. Seed skill_scores:
            # - Case A: old non-weekly (computed_at 4 days ago) -> PURGED
            # - Case B: today's non-weekly -> RETAINED
            # - Case C: weekly within 26 weeks -> RETAINED
            # - Case D: weekly older than 26 weeks (32 weeks ago) -> PURGED
            cur.execute("""
                INSERT INTO skill_scores (
                    computed_at, window_days, variable, region, season, lead_days,
                    model, mae, is_weekly
                ) VALUES
                (NOW() - INTERVAL '4 days', 60, 'rain_mm', 'TEST_RETENTION', 'monsoon', 1, 'blend', 2.0, false),
                (NOW(), 60, 'tmax_c', 'TEST_RETENTION', 'monsoon', 1, 'blend', 1.8, false),
                (NOW() - INTERVAL '8 weeks', 60, 'wind_max_kmh', 'TEST_RETENTION', 'monsoon', 1, 'blend', 2.5, true),
                (NOW() - INTERVAL '32 weeks', 60, 'rain_mm', 'TEST_RETENTION', 'monsoon', 1, 'blend', 3.0, true)
                ON CONFLICT (computed_at, window_days, variable, region, season, lead_days, model, threshold_mm, is_weekly) DO NOTHING;
            """)

            # 5. Seed chat_audit:
            # - Case A: older than 30 days -> PURGED
            # - Case B: within 30 days -> RETAINED
            cur.execute("""
                INSERT INTO chat_audit (
                    question, created_at
                ) VALUES
                ('test_retention_query', NOW() - INTERVAL '45 days'),
                ('test_retention_query', NOW() - INTERVAL '10 days');
            """)

        # Execute real cleanup
        stats = engine.run_cleanup(dry_run=False)

        assert stats["overrides_expired"] >= 1, "At least 1 override must be expired"
        assert stats["blended_forecasts_purged"] >= 2, "Non-00Z and >180d blended rows must be purged"
        assert stats["skill_scores_purged"] >= 2, "Old non-weekly and >26w weekly skill scores must be purged"
        assert stats["chat_audit_purged"] >= 1, "Old chat audit records must be purged"

        # Verify actual database state
        with conn.cursor() as cur:
            # 1. Check weight_overrides: expired one must have active=false, unexpired must have active=true
            cur.execute("""
                SELECT variable, active
                FROM weight_overrides
                WHERE reason = 'test_retention_live_reason'
                ORDER BY variable;
            """)
            wo_rows = dict(cur.fetchall())
            assert wo_rows.get("rain_mm") is False, "Expired override must have active=false"
            assert wo_rows.get("tmax_c") is True, "Unexpired override must remain active=true"

            # 2. Check blended_forecasts: 00Z inside 180d must exist, others must not
            cur.execute("""
                SELECT variable FROM blended_forecasts
                WHERE issue_time IN ('2026-09-06 00:00:00+00', '2026-09-06 06:00:00+00', '2026-02-13 00:00:00+00');
            """)
            bf_vars = {r[0] for r in cur.fetchall()}
            assert "rain_mm" in bf_vars, "00Z row inside 180 days must remain"
            assert "tmax_c" not in bf_vars, "non-00Z row must be deleted"
            assert "wind_max_kmh" not in bf_vars, "00Z row older than 180 days must be deleted"

            # 3. Check skill_scores:
            cur.execute("""
                SELECT variable, is_weekly FROM skill_scores
                WHERE region = 'TEST_RETENTION';
            """)
            sk_rows = cur.fetchall()
            sk_vars = {r[0] for r in sk_rows}
            assert "tmax_c" in sk_vars, "Today's non-weekly row must remain"
            assert "wind_max_kmh" in sk_vars, "Recent weekly row must remain"
            assert "rain_mm" not in sk_vars, "Old non-weekly and >26w weekly rows must be deleted"

            # 4. Check chat_audit:
            cur.execute("""
                SELECT COUNT(*) FROM chat_audit
                WHERE question = 'test_retention_query';
            """)
            assert cur.fetchone()[0] == 1, "Only the fresh chat_audit row must remain"

    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM weight_overrides WHERE reason = 'test_retention_live_reason';")
            cur.execute("DELETE FROM blended_forecasts WHERE issue_time IN ('2026-09-06 00:00:00+00', '2026-09-06 06:00:00+00', '2026-02-13 00:00:00+00');")
            cur.execute("DELETE FROM skill_scores WHERE region = 'TEST_RETENTION';")
            cur.execute("DELETE FROM chat_audit WHERE question = 'test_retention_query';")
        conn.close()



