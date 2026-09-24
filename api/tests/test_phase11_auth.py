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
    mock_supabase.auth.sign_in_with_otp.assert_called_once_with({
        "email": "officer@example.gov.in",
        "options": {"email_redirect_to": settings.AUTH_REDIRECT_URL},
    })


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


def test_request_otp_production_configured_redirect(client, monkeypatch):
    """Verify that when AUTH_REDIRECT_URL is set for production, OTP requests dispatch with that URL."""
    prod_url = "https://aagam-mlb8.vercel.app"
    monkeypatch.setattr(settings, "AUTH_REDIRECT_URL", prod_url)

    mock_supabase = MagicMock()
    mock_supabase.auth.sign_in_with_otp.return_value = {"status": "ok"}
    monkeypatch.setattr("api.app.routers.auth.get_supabase_client", lambda: mock_supabase)

    resp = client.post(
        "/api/v1/auth/otp/request",
        json={"email": "officer@example.gov.in"},
    )
    assert resp.status_code == 200, resp.text
    mock_supabase.auth.sign_in_with_otp.assert_called_once_with({
        "email": "officer@example.gov.in",
        "options": {"email_redirect_to": prod_url},
    })


def test_request_forecaster_otp_uses_configured_redirect(client, monkeypatch):
    """Verify that forecaster OTP requests use settings.AUTH_REDIRECT_URL and include profile metadata for approved accounts."""
    custom_url = "https://custom.weather.gov.in"
    monkeypatch.setattr(settings, "AUTH_REDIRECT_URL", custom_url)
    async def mock_approved(*args, **kwargs):
        return True
    monkeypatch.setattr("api.app.routers.auth._is_email_approved_forecaster", mock_approved)

    mock_supabase = MagicMock()
    mock_supabase.auth.sign_in_with_otp.return_value = {"status": "ok"}
    monkeypatch.setattr("api.app.routers.auth.get_supabase_client", lambda: mock_supabase)

    resp = client.post(
        "/api/v1/auth/forecaster/otp/request",
        json={
            "email": "forecaster@imd.gov.in",
            "name": "Dr. A. Sharma",
            "institution": "IMD Pune",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    mock_supabase.auth.sign_in_with_otp.assert_called_once_with({
        "email": "forecaster@imd.gov.in",
        "options": {
            "data": {
                "display_name": "Dr. A. Sharma",
                "institution": "IMD Pune",
            },
            "email_redirect_to": custom_url,
        },
    })


def test_request_forecaster_otp_rejected_for_unapproved_email(client, monkeypatch):
    """Verify that unapproved email cannot request forecaster OTP and receives 403 ACCESS_NOT_APPROVED."""
    async def mock_unapproved(*args, **kwargs):
        return False
    monkeypatch.setattr("api.app.routers.auth._is_email_approved_forecaster", mock_unapproved)

    resp = client.post(
        "/api/v1/auth/forecaster/otp/request",
        json={"email": "random_public@gmail.com"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ACCESS_NOT_APPROVED"


def test_no_hardcoded_localhost_in_auth_router():
    """Verify that api/app/routers/auth.py contains zero hardcoded localhost auth redirect URLs."""
    import re
    from pathlib import Path

    auth_file = Path(__file__).resolve().parent.parent / "app" / "routers" / "auth.py"
    content = auth_file.read_text(encoding="utf-8")

    # Ensure no email_redirect_to points to localhost
    matches = re.findall(r'["\']email_redirect_to["\']\s*:\s*["\'][^"\']*localhost[^"\']*["\']', content)
    assert matches == [], f"Found hardcoded localhost auth redirects in auth.py: {matches}"


@pytest.mark.parametrize("invalid_token", [
    "12345",       # 5 digits (too short)
    "1234567",     # 7 digits (too long)
    "12345678",    # 8 digits (old Supabase default, must be rejected)
    "123456789",   # 9 digits
    "1234567890",  # 10 digits
    "12345a",      # non-numeric letter
    "abcdef",      # alphabetic
    "12 456",      # space inside
    " 123456 ",    # unstripped with spaces outside
    "",            # empty
])
def test_verify_otp_token_length_and_format_validation(client, invalid_token):
    """Verify that normal OTP verification strictly rejects any token that is not exactly 6 digits."""
    resp = client.post(
        "/api/v1/auth/otp/verify",
        json={"email": "officer@example.gov.in", "token": invalid_token},
    )
    assert resp.status_code == 422, f"Expected 422 for token '{invalid_token}', got {resp.status_code}: {resp.text}"


@pytest.mark.parametrize("invalid_token", [
    "12345",       # 5 digits
    "1234567",     # 7 digits
    "12345678",    # 8 digits
    "123456789",   # 9 digits
    "1234567890",  # 10 digits
    "12345a",      # non-numeric
    "abcdef",      # alphabetic
])
def test_verify_forecaster_otp_token_length_and_format_validation(client, invalid_token):
    """Verify that forecaster OTP verification strictly rejects any token that is not exactly 6 digits."""
    resp = client.post(
        "/api/v1/auth/forecaster/otp/verify",
        json={"email": "forecaster@imd.gov.in", "token": invalid_token},
    )
    assert resp.status_code == 422, f"Expected 422 for forecaster token '{invalid_token}', got {resp.status_code}: {resp.text}"


def test_verify_otp_exact_6_digits_accepted(client, monkeypatch):
    """Verify that an exact 6-digit numeric OTP is accepted by schema and dispatched to Supabase."""
    mock_supabase = MagicMock()
    mock_auth_resp = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid.uuid4())
    mock_user.email = "valid6@example.gov.in"
    mock_session = MagicMock()
    mock_session.access_token = "valid-access-token"
    mock_session.refresh_token = "valid-refresh-token"
    mock_session.expires_in = 3600
    mock_auth_resp.user = mock_user
    mock_auth_resp.session = mock_session
    mock_supabase.auth.verify_otp.return_value = mock_auth_resp
    monkeypatch.setattr("api.app.routers.auth.get_supabase_client", lambda: mock_supabase)

    # Insert test user into auth.users so foreign key constraint passes
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO auth.users (id, email) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;",
                (mock_user.id, mock_user.email),
            )
        resp = client.post(
            "/api/v1/auth/otp/verify",
            json={"email": mock_user.email, "token": "654321"},
        )
        assert resp.status_code == 200, resp.text
        mock_supabase.auth.verify_otp.assert_called_once_with({
            "email": mock_user.email,
            "token": "654321",
            "type": "email",
        })
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM subscriptions WHERE user_id = %s;", (mock_user.id,))
            cur.execute("DELETE FROM auth.users WHERE id = %s;", (mock_user.id,))
        conn.close()
