"""Tests for Phase 11: Supabase OTP Authentication Flow (PRD §6.9, §12)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import psycopg2
import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from core.config import settings


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_request_otp_success(client, monkeypatch):
    """Verify that requesting an OTP returns 200 and dispatches to Supabase Auth."""
    mock_supabase = MagicMock()
    mock_supabase.auth.sign_in_with_otp.return_value = {"status": "ok"}
    monkeypatch.setattr("api.app.routers.auth.get_supabase_client", lambda: mock_supabase)

    resp = client.post(
        "/api/v1/auth/otp/request",
        json={"email": "officer@example.gov.in"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    mock_supabase.auth.sign_in_with_otp.assert_called_once_with({"email": "officer@example.gov.in"})


def test_request_otp_invalid_email(client):
    """Verify that malformed email inputs are rejected with 422."""
    resp = client.post(
        "/api/v1/auth/otp/request",
        json={"email": "not-a-valid-email"},
    )
    assert resp.status_code == 422


def test_verify_otp_success_and_seeds_subscription(client, monkeypatch):
    """Verify that successful OTP verification returns session and creates default subscriptions record."""
    test_user_id = str(uuid.uuid4())
    test_email = f"officer_{uuid.uuid4().hex[:6]}@example.gov.in"

    mock_user = MagicMock()
    mock_user.id = test_user_id
    mock_user.email = test_email

    mock_session = MagicMock()
    mock_session.access_token = "mock-supabase-access-token-12345"
    mock_session.refresh_token = "mock-refresh-token"
    mock_session.expires_in = 3600

    mock_auth_resp = MagicMock()
    mock_auth_resp.user = mock_user
    mock_auth_resp.session = mock_session

    mock_supabase = MagicMock()
    mock_supabase.auth.verify_otp.return_value = mock_auth_resp
    monkeypatch.setattr("api.app.routers.auth.get_supabase_client", lambda: mock_supabase)

    # First insert a real user into auth.users so foreign key succeeds
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth.users (id, email)
                VALUES (%s, %s)
                ON CONFLICT (id) DO NOTHING;
                """,
                (test_user_id, test_email),
            )

        resp = client.post(
            "/api/v1/auth/otp/verify",
            json={"email": test_email, "token": "654321"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "ok"
        assert data["access_token"] == "mock-supabase-access-token-12345"
        assert data["user"]["id"] == test_user_id
        assert data["user"]["email"] == test_email

        # Verify default subscription was seeded in the database
        with conn.cursor() as cur:
            cur.execute("SELECT active, min_severity FROM subscriptions WHERE user_id = %s;", (test_user_id,))
            sub_row = cur.fetchone()
            assert sub_row is not None, "Expected subscriptions record to be automatically created"
            assert sub_row[0] is True
            assert sub_row[1] == "watch"

    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM subscriptions WHERE user_id = %s;", (test_user_id,))
            cur.execute("DELETE FROM auth.users WHERE id = %s;", (test_user_id,))
        conn.close()


def test_verify_otp_invalid_code(client, monkeypatch):
    """Verify that incorrect or expired verification codes return 401 UNAUTHORIZED."""
    mock_supabase = MagicMock()
    mock_supabase.auth.verify_otp.side_effect = Exception("Invalid OTP code supplied")
    monkeypatch.setattr("api.app.routers.auth.get_supabase_client", lambda: mock_supabase)

    resp = client.post(
        "/api/v1/auth/otp/verify",
        json={"email": "officer@example.gov.in", "token": "000000"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "INVALID_OTP"
