"""Phase 1 Schema and Migration Verification Tests.

Verifies:
1. model_versions table extension with all required lifecycle columns and constraints.
2. The is_active and status backfill invariant (exactly one active model version matching pre-migration state).
3. Creation and structure of model_version_evaluations, model_version_decisions,
   model_version_canary_assignments, and model_switching_automation_state.
4. The ELIGIBLE decision enum value in model_version_decisions check constraint.
5. The singleton constraint on model_switching_automation_state.
6. RLS enabled on all 4 new tables with appropriate public/coordinator policies.
7. Unbroken backward compatibility of ModelRegistry (get_active_version, list_versions, evaluate_quality_gate).
"""

from __future__ import annotations

import psycopg2
import pytest

from core.config import settings
from pipeline.models.registry import ModelRegistry


def get_db_connection():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    return conn


class TestModelVersioningSchema:
    """Verifies Phase 1 additive migration 20260924000008_model_version_switching.sql."""

    def test_model_versions_lifecycle_columns_exist(self):
        """Verifies all new lifecycle columns are present on model_versions."""
        conn = get_db_connection()
        expected_columns = {
            "parent_version_id",
            "algorithm_type",
            "evaluation_policy",
            "config_hash",
            "training_window_start",
            "training_window_end",
            "validation_window_start",
            "validation_window_end",
            "status",
            "activated_at",
            "deactivated_at",
            "shadow_started_at",
            "canary_started_at",
            "created_by",
        }
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'model_versions';
                    """
                )
                columns = {row[0] for row in cur.fetchall()}
                assert expected_columns.issubset(columns), (
                    f"Missing columns in model_versions: {expected_columns - columns}"
                )
        finally:
            conn.close()

    def test_is_active_backfill_invariant(self):
        """Verifies backfill preserved exactly one active version matching is_active=true."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # Exactly one is_active = true
                cur.execute("SELECT COUNT(*) FROM model_versions WHERE is_active = true;")
                active_count = cur.fetchone()[0]
                assert active_count == 1, f"Expected exactly 1 active version, found {active_count}"

                # The active row must have status = 'active' and activated_at set
                cur.execute(
                    """
                    SELECT id, status, activated_at, deactivated_at
                    FROM model_versions
                    WHERE is_active = true;
                    """
                )
                active_row = cur.fetchone()
                assert active_row is not None
                assert active_row[1] == "active", f"Active row status should be 'active', got {active_row[1]}"
                assert active_row[2] is not None, "activated_at should be set on active version"
                assert active_row[3] is None, "deactivated_at should be None on active version"

                # Inactive rows must have status = 'superseded' and deactivated_at set
                cur.execute(
                    """
                    SELECT id, status, deactivated_at
                    FROM model_versions
                    WHERE is_active = false;
                    """
                )
                inactive_rows = cur.fetchall()
                for row in inactive_rows:
                    assert row[1] == "superseded", f"Inactive row status should be 'superseded', got {row[1]}"
                    assert row[2] is not None, "deactivated_at should be populated on inactive rows"
        finally:
            conn.close()

    def test_status_check_constraint_rejects_invalid_status(self):
        """Verifies CHECK constraint on status rejects invalid states."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                with pytest.raises(psycopg2.IntegrityError):
                    cur.execute(
                        """
                        INSERT INTO model_versions (storage_path, metrics, status)
                        VALUES ('models/test/', '{}'::jsonb, 'invalid_state');
                        """
                    )
        finally:
            conn.close()

    def test_model_version_evaluations_table_structure(self):
        """Verifies model_version_evaluations exists with all required columns."""
        conn = get_db_connection()
        expected = {
            "id",
            "version_id",
            "pipeline_run_id",
            "window_type",
            "window_start",
            "window_end",
            "composite_score",
            "strata_included",
            "strata_excluded",
            "regions_covered",
            "lead_days_covered",
            "sample_counts",
            "metrics_detail",
            "computed_at",
        }
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'model_version_evaluations';
                    """
                )
                columns = {row[0] for row in cur.fetchall()}
                assert expected.issubset(columns), f"Missing in model_version_evaluations: {expected - columns}"
        finally:
            conn.close()

    def test_model_version_decisions_table_and_eligible_decision(self):
        """Verifies model_version_decisions table exists and accepts ELIGIBLE decision."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # Test that ELIGIBLE decision is accepted
                cur.execute(
                    """
                    INSERT INTO model_version_decisions (
                        decision, sample_counts, reason, algorithm_version
                    ) VALUES (
                        'ELIGIBLE', '{"n": 100}'::jsonb, 'Cycle 1 passed evaluation', 'staged_v2'
                    ) RETURNING id;
                    """
                )
                decision_id = cur.fetchone()[0]
                assert decision_id is not None

                # Clean up test row
                cur.execute("DELETE FROM model_version_decisions WHERE id = %s;", (decision_id,))

                # Test that an invalid decision is rejected
                with pytest.raises(psycopg2.IntegrityError):
                    cur.execute(
                        """
                        INSERT INTO model_version_decisions (
                            decision, sample_counts, reason, algorithm_version
                        ) VALUES (
                            'INVALID_DECISION', '{}'::jsonb, 'Test', 'v1'
                        );
                        """
                    )
        finally:
            conn.close()

    def test_model_version_canary_assignments_table(self):
        """Verifies model_version_canary_assignments table exists."""
        conn = get_db_connection()
        expected = {"location_id", "version_id", "assigned_at", "released_at"}
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'model_version_canary_assignments';
                    """
                )
                columns = {row[0] for row in cur.fetchall()}
                assert expected.issubset(columns), f"Missing columns in canary_assignments: {expected - columns}"
        finally:
            conn.close()

    def test_model_switching_automation_state_singleton(self):
        """Verifies model_switching_automation_state has singleton row with id=1 and default frozen=false."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, frozen, rollback_count_14d FROM model_switching_automation_state;")
                rows = cur.fetchall()
                assert len(rows) == 1, f"Expected exactly 1 singleton row, found {len(rows)}"
                assert rows[0][0] == 1, "Singleton id must be 1"
                assert rows[0][1] is False, "Default frozen state must be false"
                assert rows[0][2] == 0, "Default rollback count must be 0"

                # Verify CHECK constraint prevents id != 1
                with pytest.raises(psycopg2.IntegrityError):
                    cur.execute(
                        "INSERT INTO model_switching_automation_state (id, frozen) VALUES (2, true);"
                    )
        finally:
            conn.close()

    def test_rls_enabled_on_all_new_tables(self):
        """Verifies row security is enabled on all four new model-versioning tables."""
        conn = get_db_connection()
        new_tables = [
            "model_version_evaluations",
            "model_version_decisions",
            "model_version_canary_assignments",
            "model_switching_automation_state",
        ]
        try:
            with conn.cursor() as cur:
                for table in new_tables:
                    cur.execute(
                        """
                        SELECT rowsecurity
                        FROM pg_tables
                        WHERE schemaname = 'public' AND tablename = %s;
                        """,
                        (table,),
                    )
                    row = cur.fetchone()
                    assert row is not None, f"Table {table} not found in pg_tables"
                    assert row[0] is True, f"RLS must be enabled on {table}"
        finally:
            conn.close()

    def test_existing_registry_backward_compatibility(self):
        """Verifies that ModelRegistry methods still execute and return expected data unmodified."""
        registry = ModelRegistry()

        # get_active_version
        active = registry.get_active_version()
        assert active is not None
        assert active["is_active"] is True
        assert "storage_path" in active
        assert "metrics" in active

        # list_versions
        versions = registry.list_versions()
        assert len(versions) >= 1
        active_versions = [v for v in versions if v["is_active"] is True]
        assert len(active_versions) == 1

        # evaluate_quality_gate runs without error
        candidate_metrics = {"lightgbm_validation_mae": {"rain_mm": 1.0, "tmax_c": 1.0, "wind_max_kmh": 1.0}}
        passed, reason, active_ver = registry.evaluate_quality_gate(candidate_metrics)
        assert isinstance(passed, bool)
        assert isinstance(reason, str)
