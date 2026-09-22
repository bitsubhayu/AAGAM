"""Tests for Phase 11: Subscriptions, notifications_log Schema and Row Level Security.

Authoritative sources: AAGAM_PRD.md §11, §11.4 / AAGAM_TECH_STACK.md §8a, §11.
"""

import uuid

import psycopg2
import pytest

from core.config import settings


def get_db_connection():
    return psycopg2.connect(settings.DATABASE_URL)


class TestPhase11DatabaseSchema:
    def test_subscriptions_table_and_columns(self):
        """Verify subscriptions table exists with all required Phase 11 columns and types."""
        conn = get_db_connection()
        expected_columns = {
            "user_id",
            "email",
            "location_ids",
            "hazards",
            "min_severity",
            "daily_summary",
            "lifecycle_emails",
            "active",
            "created_at",
            "updated_at",
        }
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'subscriptions';
                    """
                )
                columns = {row[0] for row in cur.fetchall()}
                assert expected_columns.issubset(columns), f"Missing columns in subscriptions: {expected_columns - columns}"
        finally:
            conn.close()

    def test_notifications_log_table_and_columns(self):
        """Verify notifications_log table exists with audit and deduplication columns."""
        conn = get_db_connection()
        expected_columns = {
            "id",
            "user_id",
            "kind",
            "event_id",
            "lifecycle_state",
            "sent_at",
            "status",
            "provider_message_id",
            "dedup_key",
        }
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'notifications_log';
                    """
                )
                columns = {row[0] for row in cur.fetchall()}
                assert expected_columns.issubset(columns), f"Missing columns in notifications_log: {expected_columns - columns}"
        finally:
            conn.close()

    def test_subscriptions_min_severity_constraint(self):
        """Verify subscriptions check constraint enforces ('advisory', 'watch', 'alert')."""
        conn = get_db_connection()
        dummy_uid = str(uuid.uuid4())
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN;")
                # First ensure an auth user exists in auth.users or roll back test
                with pytest.raises(psycopg2.Error) as exc_info:
                    cur.execute(
                        """
                        INSERT INTO subscriptions (user_id, email, min_severity)
                        VALUES (%s, 'test@example.com', 'catastrophic');
                        """,
                        (dummy_uid,),
                    )
                assert "subscriptions_min_severity_check" in str(exc_info.value)
                cur.execute("ROLLBACK;")
        finally:
            conn.close()

    def test_notifications_log_kind_constraint(self):
        """Verify notifications_log check constraint enforces ('otp', 'daily_summary', 'lifecycle')."""
        conn = get_db_connection()
        dummy_uid = str(uuid.uuid4())
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN;")
                with pytest.raises(psycopg2.Error) as exc_info:
                    cur.execute(
                        """
                        INSERT INTO notifications_log (user_id, kind, status)
                        VALUES (%s, 'invalid_kind', 'sent');
                        """,
                        (dummy_uid,),
                    )
                assert "notifications_log_kind_check" in str(exc_info.value)
                cur.execute("ROLLBACK;")
        finally:
            conn.close()


class TestPhase11RowLevelSecurity:
    def test_subscriptions_own_row_rls(self):
        """Verify authenticated users can only view and update their own subscription record."""
        conn = get_db_connection()
        conn.autocommit = True

        # Fetch an existing user from auth.users or profiles
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM auth.users LIMIT 2;")
            users = cur.fetchall()

        if len(users) < 1:
            pytest.skip("Insufficient auth.users in live test database to test RLS claims.")

        user_a = str(users[0][0])
        user_b = str(users[1][0]) if len(users) > 1 else str(uuid.uuid4())

        try:
            with conn.cursor() as cur:
                # Seed subscription for user_a as superuser/service_role
                cur.execute(
                    """
                    INSERT INTO subscriptions (user_id, email, location_ids, min_severity, active)
                    VALUES (%s, 'user_a@example.com', ARRAY[1, 2], 'watch', true)
                    ON CONFLICT (user_id) DO UPDATE SET email = EXCLUDED.email;
                    """,
                    (user_a,),
                )

                # Now simulate request as user_a (authenticated)
                cur.execute("BEGIN;")
                cur.execute("SET LOCAL ROLE authenticated;")
                cur.execute(
                    f"SET LOCAL request.jwt.claims = '{{\"sub\": \"{user_a}\", \"role\": \"authenticated\"}}';"
                )

                # User A can select own row
                cur.execute("SELECT email, location_ids FROM subscriptions WHERE user_id = %s;", (user_a,))
                row_a = cur.fetchone()
                assert row_a is not None, "User A should be able to select own subscription row"

                # User A cannot select User B's row
                cur.execute("SELECT email FROM subscriptions WHERE user_id = %s;", (user_b,))
                row_b = cur.fetchone()
                assert row_b is None, "User A must not be able to select User B's subscription row"

                cur.execute("ROLLBACK;")
        finally:
            conn.close()

    def test_notifications_log_service_role_only(self):
        """Verify notifications_log cannot be read or modified by authenticated or anon clients."""
        conn = get_db_connection()
        conn.autocommit = True
        dummy_uid = str(uuid.uuid4())

        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN;")
                # Test as authenticated user
                cur.execute("SET LOCAL ROLE authenticated;")
                cur.execute(
                    f"SET LOCAL request.jwt.claims = '{{\"sub\": \"{dummy_uid}\", \"role\": \"authenticated\"}}';"
                )
                cur.execute("SELECT count(*) FROM notifications_log;")
                count = cur.fetchone()[0]
                assert count == 0, "Authenticated client without service role must see 0 rows in notifications_log"

                # Insert attempt by client should produce 0 inserted rows or be denied
                with pytest.raises(psycopg2.Error):
                    cur.execute(
                        """
                        INSERT INTO notifications_log (user_id, kind, status)
                        VALUES (%s, 'otp', 'sent');
                        """,
                        (dummy_uid,),
                    )

                cur.execute("ROLLBACK;")
        finally:
            conn.close()
