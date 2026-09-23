"""Comprehensive API Tests for Phase 10: Public Alerts, Window Modes, Event Detail, and Forecaster Ack.

Authoritative source: AAGAM_PRD.md §10.4, §11.1, §12 / AAGAM_TECH_STACK.md
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

import jwt
import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from core.config import settings

TEST_JWT_SECRET = "test-phase-10-secret-key-very-secure-32-chars-long"


def create_test_jwt(
    user_id: Optional[str] = None,
    email: str = "testuser@aagam.gov.in",
    role: str = "viewer",
    secret: str = TEST_JWT_SECRET,
    expires_in: int = 3600,
) -> str:
    """Generates a test JWT signed with TEST_JWT_SECRET carrying role metadata."""
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
    """Configures test JWT secret so verify_supabase_jwt decodes test tokens cleanly."""
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", TEST_JWT_SECRET)


@pytest.fixture
def client():
    """Provides TestClient with initialized lifespan."""
    with TestClient(app) as tc:
        yield tc


# ==============================================================================
# 1. Public Alerts Endpoint & Window Parameter Tests
# ==============================================================================
def test_public_alerts_endpoint_unauthenticated(client):
    """GET /api/v1/alerts must be accessible anonymously without auth headers."""
    resp = client.get("/api/v1/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert "alerts" in data
    assert isinstance(data["alerts"], list)


@pytest.mark.parametrize(
    "window_param",
    [
        "upcoming_2d",
        "upcoming_3d",
        "upcoming_7d",
        "past_24h",
        "past_7d",
    ],
)
def test_alerts_all_window_modes(client, window_param):
    """GET /api/v1/alerts?window= must support all 5 authorized window modes."""
    resp = client.get(f"/api/v1/alerts?window={window_param}")
    assert resp.status_code == 200
    data = resp.json()
    assert "alerts" in data
    assert "count" in data


def test_alerts_invalid_window_mode_returns_422(client):
    """Invalid window parameter returns 422 Validation Error per FastAPI query regex."""
    resp = client.get("/api/v1/alerts?window=invalid_window_name")
    assert resp.status_code == 422


def test_alerts_filters_anonymous(client):
    """Query parameters hazard, region, and min_severity work without authentication."""
    resp = client.get("/api/v1/alerts?hazard=heavy_rain&region=EAST_NE&min_severity=watch")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["alerts"]:
        assert item["hazard"] == "heavy_rain"
        assert item["severity"] in ("watch", "alert")


# ==============================================================================
# 2. Public Alert Event Detail Endpoint Tests
# ==============================================================================
def test_alert_event_detail_public_unauthenticated(client):
    """GET /api/v1/alerts/events/{id} must be public and return PRD §11.1 event detail."""
    resp_404 = client.get("/api/v1/alerts/events/99999999")
    assert resp_404.status_code == 404
    data_404 = resp_404.json()
    assert "error" in data_404
    assert data_404["error"]["code"] == "EVENT_NOT_FOUND"


# ==============================================================================
# 3. Role-Based Access for Alert Event Acknowledgement
# ==============================================================================
def test_ack_alert_event_unauthenticated_rejected(client):
    """POST /api/v1/alerts/events/{id}/ack without token must return 401."""
    resp = client.post("/api/v1/alerts/events/1/ack")
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


def test_ack_alert_event_public_forbidden(client):
    """POST /api/v1/alerts/events/{id}/ack with public role must return 403."""
    public_token = create_test_jwt(role="public")
    resp = client.post(
        "/api/v1/alerts/events/1/ack",
        headers={"Authorization": f"Bearer {public_token}"},
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["error"]["code"] == "FORBIDDEN"


def test_ack_alert_event_forecaster_allowed(client):
    """POST /api/v1/alerts/events/{id}/ack with forecaster role allowed (or 404 if event absent)."""
    forecaster_token = create_test_jwt(role="forecaster")
    resp = client.post(
        "/api/v1/alerts/events/99999999/ack",
        headers={"Authorization": f"Bearer {forecaster_token}"},
    )
    # If event 99999999 does not exist, it should return 404 (NOT 401/403)
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "EVENT_NOT_FOUND"


def test_ack_alert_event_coordinator_allowed(client):
    """POST /api/v1/alerts/events/{id}/ack with coordinator role allowed (or 404 if event absent)."""
    coordinator_token = create_test_jwt(role="coordinator")
    resp = client.post(
        "/api/v1/alerts/events/99999999/ack",
        headers={"Authorization": f"Bearer {coordinator_token}"},
    )
    # Coordinator is authorized to acknowledge; non-existent ID yields 404
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "EVENT_NOT_FOUND"


def test_ack_alert_event_preserves_status_and_acknowledges_child_alerts(client):
    """Verify that acknowledgement succeeds, keeps alert_events.status as 'active', and marks child alerts as acknowledged."""
    import psycopg2
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    seeded_event_id = None
    seeded_alert_id = None

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_events (
                    location_id, hazard, status, severity_peak, value_peak,
                    start_date, end_date, first_detected_at, last_updated_at
                ) VALUES (1, 'heavy_rain', 'active', 'alert', 110.0, CURRENT_DATE, CURRENT_DATE, NOW(), NOW())
                RETURNING id;
                """
            )
            seeded_event_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO alerts (
                    issue_time, location_id, hazard, severity, valid_date, lead_days,
                    value, models_over, spread, rule, status, event_id
                ) VALUES (
                    NOW(), 1, 'heavy_rain', 'alert', CURRENT_DATE, 1,
                    110.0, 4, 10.0, '{"trigger": "test_ack"}'::jsonb, 'active', %s
                )
                RETURNING id;
                """,
                (seeded_event_id,),
            )
            seeded_alert_id = cur.fetchone()[0]

        # Call acknowledgement endpoint with forecaster role
        forecaster_token = create_test_jwt(role="forecaster")
        resp = client.post(
            f"/api/v1/alerts/events/{seeded_event_id}/ack",
            headers={"Authorization": f"Bearer {forecaster_token}"},
        )
        assert resp.status_code == 200, f"Expected 200 OK, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["id"] == seeded_event_id
        # Status MUST remain a valid event lifecycle status ('active'), NOT 'acknowledged'
        assert data["status"] == "active"
        assert data["acknowledged_by"] is not None
        assert data["acknowledged_at"] is not None

        # Verify database state directly
        with conn.cursor() as cur:
            # 1. Event status remains 'active'
            cur.execute("SELECT status FROM alert_events WHERE id = %s;", (seeded_event_id,))
            evt_status = cur.fetchone()[0]
            assert evt_status == "active", f"Expected alert_events.status='active', found {evt_status}"

            # 2. Child alert status is updated to 'acknowledged' with audit fields
            cur.execute(
                "SELECT status, acknowledged_by, acknowledged_at FROM alerts WHERE id = %s;",
                (seeded_alert_id,),
            )
            row = cur.fetchone()
            assert row[0] == "acknowledged"
            assert row[1] is not None
            assert row[2] is not None

    finally:
        with conn.cursor() as cur:
            if seeded_alert_id:
                cur.execute("DELETE FROM alerts WHERE id = %s;", (seeded_alert_id,))
            if seeded_event_id:
                cur.execute("DELETE FROM alert_events WHERE id = %s;", (seeded_event_id,))
        conn.close()
