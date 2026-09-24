"""Tests for Phase 11: Personal Subscriptions API (PRD §6.12, §11, §12)."""

from __future__ import annotations

import time
import uuid

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from core.config import settings

TEST_JWT_SECRET = "test-phase-11-secret-key-very-secure-32-chars-long"


def create_test_jwt(
    user_id: str | None = None,
    email: str = "subscriber@aagam.gov.in",
    role: str = "public",
    secret: str = TEST_JWT_SECRET,
    expires_in: int = 3600,
) -> str:
    uid = user_id or str(uuid.uuid4())
    payload = {
        "sub": uid,
        "email": email,
        "role": "authenticated",
        "app_metadata": {"role": role},
        "user_metadata": {"role": role},
        "exp": int(time.time()) + expires_in,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def setup_test_auth(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", TEST_JWT_SECRET)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_unauthenticated_subscription_access_rejected(client):
    """Verify that unauthenticated access to /subscriptions/me is rejected with 401."""
    resp_get = client.get("/api/v1/subscriptions/me")
    assert resp_get.status_code == 401

    resp_put = client.put("/api/v1/subscriptions/me", json={"location_ids": [1]})
    assert resp_put.status_code == 401

    resp_del = client.delete("/api/v1/subscriptions/me")
    assert resp_del.status_code == 401


def test_authenticated_get_and_update_subscription(client):
    """Verify authenticated user can read and update their personal subscription."""
    user_id = str(uuid.uuid4())
    email = f"officer_{uuid.uuid4().hex[:6]}@sdma.gov.in"
    token = create_test_jwt(user_id=user_id, email=email)

    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    try:
        # Create auth user row
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO auth.users (id, email) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;",
                (user_id, email),
            )

        # GET creates default if not exists
        resp = client.get("/api/v1/subscriptions/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["user_id"] == user_id
        assert data["email"] == email
        assert data["active"] is True
        assert data["min_severity"] == "watch"

        # PUT updates preferences
        update_payload = {
            "location_ids": [1, 2, 3],
            "hazards": ["heavy_rain", "high_wind"],
            "min_severity": "alert",
            "daily_summary": False,
            "lifecycle_emails": True,
            "active": True,
        }
        resp_put = client.put(
            "/api/v1/subscriptions/me",
            headers={"Authorization": f"Bearer {token}"},
            json=update_payload,
        )
        assert resp_put.status_code == 200, resp_put.text
        updated = resp_put.json()
        assert updated["location_ids"] == [1, 2, 3]
        assert updated["hazards"] == ["heavy_rain", "high_wind"]
        assert updated["min_severity"] == "alert"
        assert updated["daily_summary"] is False

        # Soft unsubscribe via DELETE
        resp_del = client.delete("/api/v1/subscriptions/me", headers={"Authorization": f"Bearer {token}"})
        assert resp_del.status_code == 200, resp_del.text
        assert resp_del.json()["status"] == "unsubscribed"
        assert resp_del.json()["active"] is False

        # Verify DB state
        with conn.cursor() as cur:
            cur.execute("SELECT active, min_severity FROM subscriptions WHERE user_id = %s;", (user_id,))
            row = cur.fetchone()
            assert row[0] is False
            assert row[1] == "alert"

    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM subscriptions WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM auth.users WHERE id = %s;", (user_id,))
        conn.close()


def test_user_isolation(client):
    """Verify that User A and User B maintain completely isolated personal subscriptions."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    email_a = f"usera_{uuid.uuid4().hex[:6]}@sdma.gov.in"
    email_b = f"userb_{uuid.uuid4().hex[:6]}@sdma.gov.in"

    token_a = create_test_jwt(user_id=user_a, email=email_a)
    token_b = create_test_jwt(user_id=user_b, email=email_b)

    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (user_a, email_a))
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (user_b, email_b))

        # User A sets locations [1, 2]
        client.put(
            "/api/v1/subscriptions/me",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"location_ids": [1, 2], "min_severity": "alert"},
        )

        # User B sets locations [3, 4]
        client.put(
            "/api/v1/subscriptions/me",
            headers={"Authorization": f"Bearer {token_b}"},
            json={"location_ids": [3, 4], "min_severity": "watch"},
        )

        # Verify User A still sees [1, 2]
        resp_a = client.get("/api/v1/subscriptions/me", headers={"Authorization": f"Bearer {token_a}"})
        assert resp_a.json()["location_ids"] == [1, 2]
        assert resp_a.json()["min_severity"] == "alert"

        # Verify User B sees [3, 4]
        resp_b = client.get("/api/v1/subscriptions/me", headers={"Authorization": f"Bearer {token_b}"})
        assert resp_b.json()["location_ids"] == [3, 4]
        assert resp_b.json()["min_severity"] == "watch"

    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM subscriptions WHERE user_id IN (%s, %s);", (user_a, user_b))
            cur.execute("DELETE FROM auth.users WHERE id IN (%s, %s);", (user_a, user_b))
        conn.close()
