"""Tests for Phase 10: Database Schema, Indexes, and RLS Public Read / Protected Write Rules.

Authoritative source: AAGAM_PRD.md §11.1, §11.4, §12 / AAGAM_TECH_STACK.md
"""

import psycopg2
import pytest

from core.config import settings


def get_db_connection():
    return psycopg2.connect(settings.DATABASE_URL)


class TestPhase10DatabaseSchema:
    def test_alert_events_table_and_columns(self):
        """Verify alert_events table exists with all required Phase 10 columns and types."""
        conn = get_db_connection()
        expected_columns = {
            "id",
            "location_id",
            "hazard",
            "status",
            "severity_peak",
            "value_peak",
            "start_date",
            "end_date",
            "first_detected_at",
            "last_updated_at",
            "outcome",
            "verified_at",
        }
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'alert_events';
                    """
                )
                columns = {row[0] for row in cur.fetchall()}
                assert expected_columns.issubset(columns), f"Missing columns in alert_events: {expected_columns - columns}"
        finally:
            conn.close()

    def test_alerts_extended_columns(self):
        """Verify alerts table has Phase 10 extended columns."""
        conn = get_db_connection()
        expected_columns = {
            "event_id",
            "lifecycle_state",
            "previous_severity",
            "rarity_label",
        }
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'alerts';
                    """
                )
                columns = {row[0] for row in cur.fetchall()}
                assert expected_columns.issubset(columns), f"Missing columns in alerts: {expected_columns - columns}"
        finally:
            conn.close()

    def test_alert_events_required_index(self):
        """Verify required index (location_id, hazard, status) exists on alert_events."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE tablename = 'alert_events'
                    AND indexname = 'idx_alert_events_loc_hazard_status';
                    """
                )
                row = cur.fetchone()
                assert row is not None, "Index idx_alert_events_loc_hazard_status does not exist"
                assert "location_id" in row[1]
                assert "hazard" in row[1]
                assert "status" in row[1]
        finally:
            conn.close()


class TestPhase10RLSPolicies:
    def test_anonymous_public_read_access(self):
        """PRD §12 & Upgrade Pack: Anonymous role (anon) must have public read access to authorized tables."""
        conn = get_db_connection()
        public_tables = [
            "locations",
            "blended_forecasts",
            "weights",
            "skill_scores",
            "alerts",
            "alert_events",
        ]
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN; SET LOCAL ROLE anon;")
                for table in public_tables:
                    cur.execute(f"SELECT COUNT(*) FROM {table};")
                    count = cur.fetchone()[0]
                    assert count >= 0, f"Table {table} query failed for anon"
                cur.execute("ROLLBACK;")
        finally:
            conn.close()

    def test_protected_tables_block_anonymous_reads(self):
        """Protected tables must block anonymous users under RLS."""
        conn = get_db_connection()
        protected_tables = [
            "model_forecasts",
            "model_versions",
            "profiles",
            "weight_overrides",
            "pipeline_runs",
            "chat_audit",
        ]
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN; SET LOCAL ROLE anon;")
                for table in protected_tables:
                    cur.execute(f"SELECT COUNT(*) FROM {table};")
                    count = cur.fetchone()[0]
                    assert count == 0, f"Protected table {table} leaked {count} rows to anon"
                cur.execute("ROLLBACK;")
        finally:
            conn.close()

    def test_anonymous_write_operations_rejected(self):
        """Anonymous role (anon) must be rejected when attempting to write to alert_events or alerts."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN; SET LOCAL ROLE anon;")
                # Attempt insert into alert_events
                with pytest.raises(psycopg2.Error):
                    cur.execute(
                        """
                        INSERT INTO alert_events (location_id, hazard, status, severity_peak, start_date, end_date)
                        VALUES (1, 'heavy_rain', 'active', 'watch', CURRENT_DATE, CURRENT_DATE);
                        """
                    )
                cur.execute("ROLLBACK;")

            with conn.cursor() as cur:
                cur.execute("BEGIN; SET LOCAL ROLE anon;")
                # Attempt insert into alerts
                with pytest.raises(psycopg2.Error):
                    cur.execute(
                        """
                        INSERT INTO alerts (location_id, hazard, severity, valid_date, lead_days, issue_time)
                        VALUES (1, 'heavy_rain', 'watch', CURRENT_DATE, 1, NOW());
                        """
                    )
                cur.execute("ROLLBACK;")
        finally:
            conn.close()

    def test_alert_events_status_constraint_rejects_acknowledged(self):
        """Verify that alert_events.status strictly enforces ('active', 'expired', 'cancelled') and rejects 'acknowledged'."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN;")
                with pytest.raises(psycopg2.Error) as exc_info:
                    cur.execute(
                        """
                        INSERT INTO alert_events (location_id, hazard, status, severity_peak, start_date, end_date)
                        VALUES (1, 'heavy_rain', 'acknowledged', 'watch', CURRENT_DATE, CURRENT_DATE);
                        """
                    )
                assert "alert_events_status_check" in str(exc_info.value)
                cur.execute("ROLLBACK;")
        finally:
            conn.close()
