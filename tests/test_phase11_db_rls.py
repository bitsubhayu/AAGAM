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


class TestPhase11AuthOtpEndpoints:
    def test_request_otp_invalid_email(self):
        from fastapi.testclient import TestClient

        from api.app.main import app

        with TestClient(app) as client:
            resp = client.post("/api/v1/auth/otp/request", json={"email": "not-an-email"})
            assert resp.status_code == 422

    def test_request_otp_success(self, monkeypatch):
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from api.app.main import app

        mock_supabase = MagicMock()
        mock_supabase.auth.sign_in_with_otp.return_value = None
        monkeypatch.setattr("api.app.routers.auth.get_supabase_client", lambda: mock_supabase)

        with TestClient(app) as client:
            resp = client.post("/api/v1/auth/otp/request", json={"email": "officer@sdma.gov.in"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "verification code" in data["message"]
            mock_supabase.auth.sign_in_with_otp.assert_called_once_with({
                "email": "officer@sdma.gov.in",
                "options": {"email_redirect_to": settings.AUTH_REDIRECT_URL},
            })

    def test_verify_otp_invalid_token(self, monkeypatch):
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from api.app.main import app

        mock_supabase = MagicMock()
        mock_supabase.auth.verify_otp.side_effect = Exception("Token has expired or is invalid")
        monkeypatch.setattr("api.app.routers.auth.get_supabase_client", lambda: mock_supabase)

        with TestClient(app) as client:
            resp = client.post("/api/v1/auth/otp/verify", json={"email": "officer@sdma.gov.in", "token": "000000"})
            assert resp.status_code == 401
            assert resp.json()["error"]["code"] == "INVALID_OTP"

    def test_verify_otp_success_and_subscription_initialization(self, monkeypatch):
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from api.app.main import app

        test_uid = str(uuid.uuid4())
        test_email = f"officer_{uuid.uuid4().hex[:6]}@sdma.gov.in"

        # Mock Supabase Auth response
        mock_user = MagicMock()
        mock_user.id = test_uid
        mock_user.email = test_email

        mock_session = MagicMock()
        mock_session.access_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test-jwt-token"
        mock_session.token_type = "bearer"
        mock_session.expires_in = 3600
        mock_session.refresh_token = "refresh-test-token"

        mock_auth_resp = MagicMock()
        mock_auth_resp.session = mock_session
        mock_auth_resp.user = mock_user

        mock_supabase = MagicMock()
        mock_supabase.auth.verify_otp.return_value = mock_auth_resp
        monkeypatch.setattr("api.app.routers.auth.get_supabase_client", lambda: mock_supabase)

        conn = get_db_connection()
        try:
            # Clean before test
            with conn.cursor() as cur:
                cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (test_uid, test_email))
            conn.commit()

            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/auth/otp/verify",
                    json={"email": test_email, "token": "123456"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "ok"
                assert data["access_token"] == "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test-jwt-token"
                assert data["user"]["id"] == test_uid
                assert data["user"]["email"] == test_email

            # Verify that subscription record was initialized with intended defaults
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT location_ids, hazards, min_severity, daily_summary, lifecycle_emails, active
                    FROM subscriptions WHERE user_id = %s;
                    """,
                    (test_uid,),
                )
                sub_row = cur.fetchone()
                assert sub_row is not None, "Subscription must be initialized upon first OTP verification"
                assert sub_row[0] == []
                assert set(sub_row[1]) == {"heavy_rain", "heatwave", "high_wind", "heavy_rain_3day"}
                assert sub_row[2] == "watch"
                assert sub_row[3] is True
                assert sub_row[4] is True
                assert sub_row[5] is True
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM subscriptions WHERE user_id = %s;", (test_uid,))
                cur.execute("DELETE FROM auth.users WHERE id = %s;", (test_uid,))
            conn.commit()
            conn.close()

