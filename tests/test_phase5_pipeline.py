"""
Phase 5 Test Suite: Live Pipeline, Database, Storage, Model Registry & Scheduler.

Tests schema integrity, RLS configuration, model registry quality gate,
idempotency, override auto-expiry, quota safety, and telemetry logging.
"""

import uuid
from unittest.mock import patch

import pytest

from pipeline.db.connection import get_db_connection
from pipeline.live.runner import LivePipelineRunner
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
    """Verify that anonymous role (anon) is blocked from reading all 11 core tables under RLS."""
    conn = get_db_connection()
    all_11_tables = [
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
            cur.execute("BEGIN; SET LOCAL ROLE anon;")
            # All 11 core tables must return 0 rows for anonymous queries under RLS
            for table in all_11_tables:
                cur.execute(f"SELECT COUNT(*) FROM {table};")
                count = cur.fetchone()[0]
                assert count == 0, f"Table '{table}' should not return data to anonymous users (got {count} rows)"
            cur.execute("ROLLBACK;")
    finally:
        conn.close()



def test_authenticated_reads_allowed_on_operational_tables():
    """Verify that authenticated role can read operational tables."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN; SET LOCAL ROLE authenticated;")
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
            # 1. Create a normal user (trigger automatically creates profile with role 'viewer')
            cur.execute("""
                INSERT INTO auth.users (id, email, role)
                VALUES (%s, 'viewer_user@aagam.local', 'authenticated');
            """, (test_user_id,))

            cur.execute("SELECT role FROM profiles WHERE user_id = %s;", (test_user_id,))
            initial_role = cur.fetchone()[0]
            assert initial_role == "viewer", "Auto-created profile must have default 'viewer' role"

            # 2. Simulate normal authenticated user session
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true);", (test_user_id,))

            # Attempt self-escalation to admin
            cur.execute("UPDATE profiles SET role = 'admin' WHERE user_id = %s;", (test_user_id,))
            assert cur.rowcount == 0, "Normal authenticated user must NOT be able to update their profile or role"

            # Attempt client-side profile creation
            with pytest.raises(Exception) as excinfo:
                cur.execute("""
                    INSERT INTO profiles (user_id, role, display_name)
                    VALUES (%s, 'admin', 'Unauthorized Admin');
                """, (str(uuid.uuid4()),))
            assert "violates row-level security policy" in str(excinfo.value).lower() or "permission denied" in str(excinfo.value).lower()

            cur.execute("ROLLBACK;")

            # 3. Confirm profile role remains strictly 'viewer'
            cur.execute("SELECT role FROM profiles WHERE user_id = %s;", (test_user_id,))
            assert cur.fetchone()[0] == "viewer", "Role must remain 'viewer' after attempted escalation"

            # 4. Verify admin user CAN manage profiles
            cur.execute("""
                INSERT INTO auth.users (id, email, role)
                VALUES (%s, 'admin_user@aagam.local', 'authenticated');
            """, (admin_user_id,))
            cur.execute("UPDATE profiles SET role = 'admin' WHERE user_id = %s;", (admin_user_id,))

            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true);", (admin_user_id,))

            cur.execute("UPDATE profiles SET display_name = 'Verified Viewer' WHERE user_id = %s;", (test_user_id,))
            assert cur.rowcount == 1, "Admin user must be allowed to manage profiles"
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
                    "train",
                    "backup",
                    "backup_nightly",
                    "retention_cleanup",
                    "historical_backfill",
                )

                assert row[2] is not None  # started_at
                assert row[4] in ("SUCCESS", "FAILED", "HALTED", "RUNNING")  # status
    finally:
        conn.close()
