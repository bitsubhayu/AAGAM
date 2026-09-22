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


def test_ack_alert_event_viewer_forbidden(client):
    """POST /api/v1/alerts/events/{id}/ack with viewer role must return 403."""
    viewer_token = create_test_jwt(role="viewer")
    resp = client.post(
        "/api/v1/alerts/events/1/ack",
        headers={"Authorization": f"Bearer {viewer_token}"},
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


def test_ack_alert_event_admin_allowed(client):
    """POST /api/v1/alerts/events/{id}/ack with admin role allowed (or 404 if event absent)."""
    admin_token = create_test_jwt(role="admin")
    resp = client.post(
        "/api/v1/alerts/events/99999999/ack",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Admin is authorized to acknowledge; non-existent ID yields 404
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "EVENT_NOT_FOUND"
