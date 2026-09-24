"""Unit tests for the append-only audit trail logger and invariants.

Authoritative source: AAGAM_MODEL_VERSIONING_DESIGN.md §R, §S

ARCHITECTURAL PRINCIPLES:
1. Pure library isolation: pipeline/versioning/ has zero mandatory runtime
   dependency on an active database. Functions accept an optional `conn` parameter.
2. In-memory by default: When conn=None, write_decision() produces a complete,
   valid audit dictionary without contacting any network service or database.
3. Isolated integration check: The live database test strictly uses an uncommitted
   transaction with mandatory rollback, never writes production data, and skips
   gracefully if a database is unreachable.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Optional, Tuple
from unittest.mock import MagicMock
from urllib.parse import urlparse

import psycopg2
import pytest

from core.config import settings
from pipeline.versioning.decisions import VALID_DECISIONS, write_decision


def resolve_safe_test_database_url() -> Tuple[Optional[str], Optional[str]]:
    """Resolves and validates that the database URL points strictly to an authorized,
    explicitly identified test or disposable database.

    HARDENED SAFETY RULES:
    1. Production Environment Prohibitions:
       If ENVIRONMENT, AAGAM_ENV, or APP_ENV is 'production' or 'prod',
       execution is ALWAYS BLOCKED regardless of connection string or opt-in flags.
    2. Universal Validation:
       EVERY connection URL—including TEST_DATABASE_URL, AAGAM_TEST_DATABASE_URL,
       and DATABASE_URL—must pass the exact same strict safety validation.
    3. Production Target Prohibitions:
       If the hostname or dbname contains 'prod' or 'production', execution is ALWAYS BLOCKED.
    4. Localhost / Loopback Exemption:
       Localhost / loopback hosts (localhost, 127.0.0.1, ::1, test-db) are allowed
       as local developer / disposable instances (provided production environment is false).
    5. Remote Database Strict Requirements:
       For any remote database, execution is permitted ONLY when ALL THREE hold:
       a) Production environment is false, AND
       b) Hostname or database name contains an explicit non-production target marker:
          ('test', 'testing', 'staging', 'disposable', 'dev', 'development', 'ci'), AND
       c) Explicit opt-in flag AAGAM_ALLOW_LIVE_DB_TESTS is 'true'/'1'/'yes'.
       The opt-in flag MUST NOT substitute for the target marker.
       An arbitrary remote database without a target marker is ALWAYS BLOCKED,
       even if ENVIRONMENT=test or opt-in is enabled.

    Returns:
        Tuple[Optional[str], Optional[str]]: (valid_safe_url, skip_reason)
    """
    # Rule 1: Absolute production environment block
    for env_var in ("ENVIRONMENT", "AAGAM_ENV", "APP_ENV"):
        val = os.environ.get(env_var, "").strip().lower()
        if val in ("production", "prod"):
            return None, f"Blocked: Environment variable '{env_var}={val}' marks environment as production. Live DB tests are strictly prohibited."

    # Rule 2: Resolve candidate URL from any configured source
    url_source = "TEST_DATABASE_URL"
    candidate_url = os.environ.get("TEST_DATABASE_URL")
    if not candidate_url:
        url_source = "AAGAM_TEST_DATABASE_URL"
        candidate_url = os.environ.get("AAGAM_TEST_DATABASE_URL")
    if not candidate_url:
        url_source = "DATABASE_URL"
        candidate_url = os.environ.get("DATABASE_URL") or getattr(settings, "DATABASE_URL", None)

    if not candidate_url:
        return None, "No database connection configured (TEST_DATABASE_URL, AAGAM_TEST_DATABASE_URL, and DATABASE_URL not set)."

    try:
        parsed = urlparse(candidate_url)
    except Exception as e:
        return None, f"Database URL could not be parsed: {e}"

    hostname = (parsed.hostname or "").lower()
    dbname = (parsed.path or "").lstrip("/").lower()

    # Rule 3: Check for production markers in the connection target itself
    if "prod" in hostname or "production" in hostname or "prod" in dbname or "production" in dbname:
        return None, f"Blocked: Target database URL indicates a production instance (host='{hostname}', db='{dbname}')."

    # Rule 4: Localhost / loopback is inherently a safe local test database
    if hostname in ("localhost", "127.0.0.1", "::1", "test-db"):
        return candidate_url, None

    # Rule 5: Remote database rules — MUST have explicit target marker AND explicit opt-in
    target_markers = ("test", "testing", "staging", "disposable", "dev", "development", "ci")
    has_target_marker = any(marker in hostname or marker in dbname for marker in target_markers)
    allow_live = os.environ.get("AAGAM_ALLOW_LIVE_DB_TESTS", "").strip().lower() in ("true", "1", "yes")

    if not has_target_marker:
        return None, (
            f"Blocked: Remote database from {url_source} (host='{hostname}', db='{dbname}') "
            "does not have an explicit non-production target marker (test/testing/staging/disposable/dev/development/ci). "
            "Arbitrary remote databases are prohibited even if ENVIRONMENT=test or opt-in is enabled."
        )

    if not allow_live:
        return None, (
            f"Blocked: Remote test/staging database from {url_source} (host='{hostname}', db='{dbname}') "
            "requires explicit opt-in AAGAM_ALLOW_LIVE_DB_TESTS=true to execute live DB tests."
        )

    return candidate_url, None


class TestDatabaseSafetyGuard:
    """Verifies that the live DB safety guard prevents accidental execution against production."""

    def test_guard_blocks_remote_db_without_target_marker_even_with_test_env_and_opt_in(self, monkeypatch):
        """ENVIRONMENT=test + opt-in + arbitrary remote DB WITHOUT target marker => BLOCK."""
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("AAGAM_ALLOW_LIVE_DB_TESTS", "true")
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@remote.example.com:5432/main_db")
        url, reason = resolve_safe_test_database_url()
        assert url is None
        assert "does not have an explicit non-production target marker" in reason

    def test_guard_permits_staging_env_with_opt_in_and_staging_target(self, monkeypatch):
        """ENVIRONMENT=staging + opt-in + explicit staging target => ALLOW."""
        monkeypatch.setenv("ENVIRONMENT", "staging")
        monkeypatch.setenv("AAGAM_ALLOW_LIVE_DB_TESTS", "true")
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@remote.staging.supabase.com:5432/app_staging")
        url, reason = resolve_safe_test_database_url()
        assert url is not None
        assert reason is None

    def test_guard_permits_test_env_with_opt_in_and_test_target(self, monkeypatch):
        """ENVIRONMENT=test + opt-in + explicit test target => ALLOW."""
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("AAGAM_ALLOW_LIVE_DB_TESTS", "true")
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@remote.example.com:5432/aagam_test")
        url, reason = resolve_safe_test_database_url()
        assert url is not None
        assert reason is None

    def test_guard_blocks_production_environment_with_any_combination(self, monkeypatch):
        """production + any combination => BLOCK (even with opt-in and localhost)."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("AAGAM_ALLOW_LIVE_DB_TESTS", "true")
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
        url, reason = resolve_safe_test_database_url()
        assert url is None
        assert "marks environment as production" in reason

    def test_guard_blocks_production_environment_with_staging_target_and_opt_in(self, monkeypatch):
        """production + staging target + opt-in => BLOCK."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("AAGAM_ALLOW_LIVE_DB_TESTS", "true")
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@remote.staging.example.com:5432/app_staging")
        url, reason = resolve_safe_test_database_url()
        assert url is None
        assert "marks environment as production" in reason

    def test_guard_blocks_test_database_url_pointing_to_production(self, monkeypatch):
        """TEST_DATABASE_URL pointing to production host is blocked."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://postgres:pass@aws-0-prod.pooler.supabase.com:6543/postgres")
        url, reason = resolve_safe_test_database_url()
        assert url is None
        assert "production" in reason

    def test_guard_blocks_aagam_test_database_url_pointing_to_production(self, monkeypatch):
        """AAGAM_TEST_DATABASE_URL pointing to production database is blocked."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("AAGAM_TEST_DATABASE_URL", "postgresql://postgres:pass@aws-0-ap-south-1.pooler.supabase.com:6543/production_db")
        url, reason = resolve_safe_test_database_url()
        assert url is None
        assert "production" in reason

    def test_guard_blocks_remote_supabase_production_url_through_test_database_url(self, monkeypatch):
        """Remote Supabase production URL is blocked even when supplied through TEST_DATABASE_URL."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("AAGAM_ALLOW_LIVE_DB_TESTS", raising=False)
        monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://postgres.gmjkcf:pass@aws-0-ap-south-1.pooler.supabase.com:6543/postgres")
        url, reason = resolve_safe_test_database_url()
        assert url is None
        assert "does not have an explicit non-production target marker" in reason

    def test_guard_blocks_remote_target_marker_without_opt_in(self, monkeypatch):
        """Remote test database without explicit opt-in flag is blocked."""
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.delenv("AAGAM_ALLOW_LIVE_DB_TESTS", raising=False)
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@remote.example.com:5432/aagam_test")
        url, reason = resolve_safe_test_database_url()
        assert url is None
        assert "requires explicit opt-in" in reason

    def test_guard_permits_localhost_without_opt_in(self, monkeypatch):
        """Localhost connection is permitted as local disposable test database."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.delenv("AAGAM_ALLOW_LIVE_DB_TESTS", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/postgres")
        url, reason = resolve_safe_test_database_url()
        assert url is not None
        assert reason is None


class TestAuditDecisions:
    """Tests durable append-only decision logging."""

    def test_valid_decisions_set(self):
        """All 11 required decision types (including Phase 4 UNFROZEN) are defined."""
        expected = {
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
        assert VALID_DECISIONS == expected

    def test_invalid_decision_raises_value_error(self):
        """Writing an unrecognized decision raises ValueError."""
        with pytest.raises(ValueError, match="Invalid decision 'INVALID_STATUS'"):
            write_decision(decision="INVALID_STATUS", reason="Testing invalid")

    def test_write_decision_record_structure(self):
        """Case 14: Decision record structure contains all required audit fields in-memory."""
        rec = write_decision(
            decision="ELIGIBLE",
            reason="Candidate cleared operational margin (+0.035 >= +0.020).",
            previous_version_id=2,
            candidate_version_id=3,
            composite_longterm_cand=0.035,
            sample_counts={"total_qualifying": 1200, "strata_count": 6},
            evaluation_window_start=date(2026, 3, 1),
            evaluation_window_end=date(2026, 8, 31),
            triggered_by="weekly_retrain",
            pipeline_run_id=42,
            algorithm_version="staged_v2",
        )

        assert rec["decision"] == "ELIGIBLE"
        assert rec["previous_version_id"] == 2
        assert rec["candidate_version_id"] == 3
        assert rec["composite_longterm_cand"] == 0.035
        assert rec["sample_counts"]["total_qualifying"] == 1200
        assert rec["evaluation_window_start"] == "2026-03-01"
        assert rec["evaluation_window_end"] == "2026-08-31"
        assert rec["algorithm_version"] == "staged_v2"
        assert "Candidate cleared operational margin" in rec["reason"]
        assert "id" not in rec  # In-memory execution: no DB id

    def test_write_decision_with_mock_connection_success(self):
        """Tests database insertion path using an in-memory mock connection (pure unit test)."""
        mock_cursor = MagicMock()
        created_at_dt = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
        mock_cursor.fetchone.return_value = (101, created_at_dt)
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.__exit__.return_value = None

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        rec = write_decision(
            decision="ELIGIBLE",
            reason="Mock test insertion",
            previous_version_id=2,
            candidate_version_id=3,
            conn=mock_conn,
        )

        assert mock_conn.cursor.called
        assert mock_cursor.execute.called
        assert rec["id"] == 101
        assert rec["created_at"] == created_at_dt.isoformat()

    def test_write_decision_db_exception_reraises(self):
        """Covers error-handling path: database execution exceptions are logged and re-raised."""
        mock_cursor = MagicMock()
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.__exit__.return_value = None
        mock_cursor.execute.side_effect = psycopg2.DatabaseError("Simulated PostgreSQL connection failure")

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with pytest.raises(psycopg2.DatabaseError, match="Simulated PostgreSQL connection failure"):
            write_decision(
                decision="ELIGIBLE",
                reason="Test error handling path",
                conn=mock_conn,
            )

    def test_live_database_decision_insert(self):
        """Integration validation against Phase 1 model_version_decisions table.

        WHAT THIS VALIDATES:
        1. That the SQL INSERT statement in write_decision matches the exact
           PostgreSQL column names, data types, and check constraints deployed
           in migration 20260924000008_model_version_switching.sql.
        2. That the jsonb sample_counts serialization works against PostgreSQL.
        3. That the returned sequence ID and created_at timestamp are populated.

        HARD SAFETY GUARANTEES:
        - Evaluated via resolve_safe_test_database_url().
        - If the database is not explicitly identified as a test/disposable database,
          or if environment is production, the test strictly SKIPS.
        - Never connects to production merely because DATABASE_URL is set.
        - When connecting to an authorized test database, runs inside an uncommitted
          transaction with a mandatory rollback in a finally block.
        - Skips gracefully if the test database is not available.
        - Does NOT create a runtime dependency for library evaluation.
        """
        db_url, skip_reason = resolve_safe_test_database_url()
        if not db_url:
            pytest.skip(f"Live database test skipped by safety guard: {skip_reason}")

        try:
            conn = psycopg2.connect(db_url, connect_timeout=3)
        except Exception as e:
            pytest.skip(f"Test database not reachable ({e}), skipping live integration test.")

        inserted_id = None
        try:
            # Ensure autocommit is disabled so this remains inside a disposable transaction
            conn.autocommit = False
            rec = write_decision(
                decision="ELIGIBLE",
                reason="Phase 2 library integration validation (disposable transaction)",
                previous_version_id=2,
                candidate_version_id=None,
                sample_counts={"validation_test": True},
                conn=conn,
            )
            assert "id" in rec
            assert rec["id"] is not None
            inserted_id = rec["id"]

            # Verify readability within the same transaction
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT decision, reason FROM model_version_decisions WHERE id = %s;",
                    (inserted_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] == "ELIGIBLE"
                assert "Phase 2 library integration validation" in row[1]
        finally:
            # MANDATORY ROLLBACK: Never persist test data
            conn.rollback()
            conn.close()
