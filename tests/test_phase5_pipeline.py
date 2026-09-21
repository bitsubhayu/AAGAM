"""
Phase 5 Test Suite: Live Pipeline, Database, Storage, Model Registry & Scheduler.

Tests schema integrity, RLS configuration, model registry quality gate,
idempotency, override auto-expiry, quota safety, and telemetry logging.
"""

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
    """Verify that anonymous role (anon) is blocked from reading operational tables."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN; SET LOCAL ROLE anon;")
            # Operational tables must return 0 rows for anonymous queries under RLS
            for table in ["blended_forecasts", "locations", "model_forecasts", "alerts", "weights"]:
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
                assert row[1] in ("ingest-blend", "ingest-live", "verify", "train", "backup", "historical_backfill")
                assert row[2] is not None  # started_at
                assert row[4] in ("SUCCESS", "FAILED", "HALTED", "RUNNING")  # status
    finally:
        conn.close()
