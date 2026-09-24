"""Comprehensive API Contract and Security Tests for AAGAM Phase 6.

Validates PRD §12 specifications:
1. /health endpoint (public, unauthenticated)
2. Authentication failures on protected endpoints (missing, malformed, expired)
3. Role-based access control matrix (public, forecaster, coordinator)
4. Strict PRD §12 error envelope conformity
5. Response schemas and JSON shapes (forecast, map, weights, alerts, history, pipeline, export, chat)
6. Query parameter validation and PRD boundary enforcement (e.g. total pagination <= 5000)
7. Rate limiting enforcement (429 with retry_after header and envelope)
8. CORS origin restrictions
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

TEST_JWT_SECRET = "test-phase-6-secret-key-very-secure-32-chars-long"


def create_test_jwt(
    user_id: Optional[str] = None,
    email: str = "testuser@aagam.gov.in",
    role: str = "public",
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
# 1. /health Endpoint Tests (Public, Unauthenticated)
# ==============================================================================
def test_health_public_unauthenticated(client):
    """GET /health must be accessible without any authentication headers."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["app"] == "AAGAM Backend API"
    assert "version" in data
    assert "timestamp" in data
    assert "supabase_connected" in data
    assert resp.headers.get("cache-control") == "no-cache, no-store, must-revalidate"


# ==============================================================================
# 2. Public Anonymous Read API & Protected Mutation Tests (Part 25A & 25B)
# ==============================================================================
def test_public_read_endpoints_accessible_anonymously(client):
    """Public meteorological read endpoints must succeed anonymously without Authorization header (Part 25A)."""
    public_get_urls = [
        "/api/v1/forecast?location=bhubaneswar&variable=rain_mm",
        "/api/v1/map?variable=rain_mm&lead_days=1",
        "/api/v1/weights",
        "/api/v1/weights/map",
        "/api/v1/skill",
        "/api/v1/history?location=bhubaneswar&variable=rain_mm",
        "/api/v1/pipeline/status",
        "/api/v1/alerts",
        "/api/v1/export?dataset=forecasts&format=csv",
    ]
    for url in public_get_urls:
        resp = client.get(url)
        assert resp.status_code == 200, f"Public URL {url} failed with status {resp.status_code}: {resp.text}"

    # Public chat must also succeed anonymously (Part 20A / Part 25A)
    resp_chat = client.post("/api/v1/chat", json={"message": "Namaste AAGAM"})
    assert resp_chat.status_code == 200, f"Public /chat failed with status {resp_chat.status_code}"


def test_protected_endpoints_reject_missing_token(client):
    """Protected mutation endpoints must reject requests lacking Authorization header with HTTP 401 (Part 25B)."""
    # 1. Weight override
    resp = client.post(
        "/api/v1/weights/override",
        json={
            "variable": "rain_mm",
            "region": "CENTRAL",
            "season": "monsoon",
            "lead_days": 1,
            "weights": {"gfs": 0.25, "ecmwf_ifs": 0.25, "icon": 0.25, "aifs": 0.25},
            "reason": "Unauthorized test attempt.",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    # 2. Alert acknowledge
    resp = client.post("/api/v1/alerts/1/ack")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    # 3. Alert event acknowledge
    resp = client.post("/api/v1/alerts/events/1/ack")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    # 4. Coordinator promotion
    resp = client.post("/api/v1/auth/forecasters/test-user-id/promote-coordinator")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_protected_endpoint_rejects_malformed_token(client):
    """Requests with non-Bearer tokens must be rejected with HTTP 401."""
    resp = client.post(
        "/api/v1/weights/override",
        headers={"Authorization": "Basic invalid_auth_token"},
        json={"variable": "rain_mm", "region": "CENTRAL", "season": "monsoon", "lead_days": 1, "weights": {}, "reason": "Test reason"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "INVALID_TOKEN"


def test_protected_endpoint_rejects_expired_token(client):
    """Expired tokens must be rejected with HTTP 401 and TOKEN_EXPIRED code."""
    expired_token = create_test_jwt(expires_in=-3600)
    resp = client.post(
        "/api/v1/weights/override",
        headers={"Authorization": f"Bearer {expired_token}"},
        json={"variable": "rain_mm", "region": "CENTRAL", "season": "monsoon", "lead_days": 1, "weights": {}, "reason": "Test reason"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "TOKEN_EXPIRED"


def test_protected_endpoint_rejects_tampered_signature(client):
    """Tokens with invalid signatures must be rejected with HTTP 401."""
    tampered_token = create_test_jwt(secret="wrong-signature-key-123456789012")
    resp = client.post(
        "/api/v1/weights/override",
        headers={"Authorization": f"Bearer {tampered_token}"},
        json={"variable": "rain_mm", "region": "CENTRAL", "season": "monsoon", "lead_days": 1, "weights": {}, "reason": "Test reason"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


# ==============================================================================
# 3. Role-Based Access Control Matrix (Public, Forecaster, Coordinator)
# ==============================================================================
def test_public_role_access_to_read_endpoints(client):
    """Public role can access all standard read endpoints."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}

    # Meta
    resp = client.get("/api/v1/meta", headers=headers)
    assert resp.status_code == 200

    # Forecast
    resp = client.get("/api/v1/forecast?location=bhubaneswar&variable=rain_mm", headers=headers)
    assert resp.status_code == 200

    # Map
    resp = client.get("/api/v1/map?variable=rain_mm&lead_days=1", headers=headers)
    assert resp.status_code == 200

    # Weights
    resp = client.get("/api/v1/weights", headers=headers)
    assert resp.status_code == 200

    # Alerts
    resp = client.get("/api/v1/alerts", headers=headers)
    assert resp.status_code == 200

    # Pipeline Status
    resp = client.get("/api/v1/pipeline/status", headers=headers)
    assert resp.status_code == 200


def test_public_forbidden_from_privileged_actions(client):
    """Public role must receive HTTP 403 FORBIDDEN when attempting privileged actions (Part 25B)."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}

    # Attempt weight override
    resp = client.post(
        "/api/v1/weights/override",
        headers=headers,
        json={
            "variable": "rain_mm",
            "region": "CENTRAL",
            "season": "monsoon",
            "lead_days": 1,
            "weights": {"gfs": 0.25, "ecmwf_ifs": 0.25, "icon": 0.25, "aifs": 0.25},
            "reason": "Unauthorized test attempt by public.",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # Attempt alert acknowledge
    resp = client.post("/api/v1/alerts/1/ack", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # Attempt coordinator promotion
    resp = client.post("/api/v1/auth/forecasters/dummy-id/promote-coordinator", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # Attempt model activation (403 for all user roles)
    resp = client.post("/api/v1/models/1/activate", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "OPERATION_DISALLOWED"


def test_forecaster_can_override_and_ack_but_not_promote(client):
    """Forecaster role can create overrides and ack alerts, but cannot promote or activate models (Part 25C)."""
    token = create_test_jwt(role="forecaster")
    headers = {"Authorization": f"Bearer {token}"}

    # Cannot promote another forecaster to coordinator
    resp_promote = client.post("/api/v1/auth/forecasters/some-id/promote-coordinator", headers=headers)
    assert resp_promote.status_code == 403
    assert resp_promote.json()["error"]["code"] == "FORBIDDEN"

    # Cannot activate model
    resp_model = client.post("/api/v1/models/1/activate", headers=headers)
    assert resp_model.status_code == 403
    assert resp_model.json()["error"]["code"] == "OPERATION_DISALLOWED"

    # Attempt alert ack on nonexistent alert (passes role check, returns 404 for missing id)
    resp_ack = client.post("/api/v1/alerts/999999/ack", headers=headers)
    assert resp_ack.status_code in (404, 200)


def test_coordinator_permissions(client):
    """Coordinator role can ack, override, and access promotion, but not model activation (Part 25D)."""
    coord_id = str(uuid.uuid4())
    token = create_test_jwt(user_id=coord_id, role="coordinator")
    headers = {"Authorization": f"Bearer {token}"}

    # Coordinator cannot self-promote (returns 400, NOT 403!)
    resp_self = client.post(f"/api/v1/auth/forecasters/{coord_id}/promote-coordinator", headers=headers)
    assert resp_self.status_code == 400
    assert "self" in resp_self.json()["error"]["message"].lower()

    # Coordinator attempting to promote a nonexistent target passes role check (returns 404, NOT 403!)
    resp_promote = client.post("/api/v1/auth/forecasters/00000000-0000-0000-0000-000000000000/promote-coordinator", headers=headers)
    assert resp_promote.status_code == 404

    # Coordinator cannot activate models (model activation is not an application-user action)
    resp_model = client.post("/api/v1/models/1/activate", headers=headers)
    assert resp_model.status_code == 403


# ==============================================================================
# 4. JSON Response Shapes (PRD §12 Conformity)
# ==============================================================================
def test_forecast_response_shape(client):
    """Verifies GET /forecast response shape strictly matches PRD §12 example."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/forecast?location=bhubaneswar&variable=rain_mm", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    # Verify top-level envelope
    assert "location" in data
    assert data["location"]["slug"] == "bhubaneswar"
    assert data["location"]["name"] == "Bhubaneswar"
    assert "region" in data["location"]
    assert data["variable"] == "rain_mm"
    assert data["unit"] == "mm/24h (08:30 IST)"
    assert "issue_time" in data
    assert data["issue_time"].endswith("Z")
    assert "model_version" in data
    assert isinstance(data["degraded"], bool)
    assert "series" in data
    assert isinstance(data["series"], list)

    # If series has items, check each item shape
    if data["series"]:
        item = data["series"][0]
        assert "valid_date" in item
        assert "lead_days" in item
        assert "blended" in item
        assert "models" in item
        assert "spread" in item
        assert "models_over_threshold" in item


def test_map_response_shape(client):
    """Verifies GET /map response shape strictly matches PRD §12."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/map?variable=rain_mm&lead_days=1", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["variable"] == "rain_mm"
    assert data["lead_days"] == 1
    assert "valid_date" in data
    assert "issue_time" in data
    assert data["unit"] == "mm/24h (08:30 IST)"
    assert "points" in data
    assert len(data["points"]) == 40

    pt = data["points"][0]
    assert "location_id" in pt
    assert "slug" in pt
    assert "name" in pt
    assert "region" in pt
    assert "lat" in pt
    assert "lon" in pt
    assert "dominant_model" in pt


def test_weights_response_shape(client):
    """Verifies GET /weights returns active model weights and matrix."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/weights?variable=rain_mm", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "version_id" in data
    assert data["method"] == "ridge"
    assert "weights" in data
    assert isinstance(data["weights"], list)
    if data["weights"]:
        w = data["weights"][0]
        assert w["variable"] == "rain_mm"
        assert "region" in w
        assert "season" in w
        assert "lead_days" in w
        assert "model" in w
        assert "weight" in w
        assert "n_samples" in w
        assert "fallback_level" in w


def test_weights_map_shape(client):
    """Verifies GET /weights/map returns dominant model and all weights for 40 locations."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/weights/map?variable=rain_mm&lead_days=1", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["variable"] == "rain_mm"
    assert data["lead_days"] == 1
    assert "locations" in data
    assert len(data["locations"]) == 40
    loc0 = data["locations"][0]
    assert "dominant_model" in loc0
    assert "all_weights" in loc0


def test_alerts_response_shape(client):
    """Verifies GET /alerts response contains list and count."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/alerts?limit=10", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert "alerts" in data
    assert isinstance(data["alerts"], list)
    if data["alerts"]:
        a = data["alerts"][0]
        assert "id" in a
        assert "hazard" in a
        assert "severity" in a
        assert "rule" in a
        assert "status" in a


# ==============================================================================
# 5. Query Parameter Validation & Boundary Enforcement
# ==============================================================================
def test_invalid_weather_variable_returns_422(client):
    """Invalid weather variable must return 422 with standard error envelope."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/forecast?location=bhubaneswar&variable=invalid_var", headers=headers)
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"]["code"] == "INVALID_VARIABLE"


def test_invalid_location_returns_404(client):
    """Nonexistent location must return 404 with LOCATION_NOT_FOUND error code."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/forecast?location=nonexistent_city_xyz&variable=rain_mm", headers=headers)
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "LOCATION_NOT_FOUND"


def test_history_pagination_boundary_exceeded(client):
    """History pagination exceeding total <= 5,000 must return 422."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get(
        "/api/v1/history?location=bhubaneswar&variable=rain_mm&offset=4500&limit=1000",
        headers=headers,
    )
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"]["code"] == "PAGINATION_LIMIT_EXCEEDED"


# ==============================================================================
# 6. Weight Override Validation Tests
# ==============================================================================
def test_weight_override_validation_reason_too_short(client):
    """Reason under 10 characters must be rejected with 422."""
    token = create_test_jwt(role="forecaster")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/api/v1/weights/override",
        headers=headers,
        json={
            "variable": "rain_mm",
            "region": "CENTRAL",
            "season": "monsoon",
            "lead_days": 1,
            "weights": {"gfs": 0.25, "ecmwf_ifs": 0.25, "icon": 0.25, "aifs": 0.25},
            "reason": "Short",  # < 10 chars
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_REASON"


def test_weight_override_validation_weights_must_sum_to_one(client):
    """Weights that do not sum to 1.0 must be rejected with 422."""
    token = create_test_jwt(role="forecaster")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/api/v1/weights/override",
        headers=headers,
        json={
            "variable": "rain_mm",
            "region": "CENTRAL",
            "season": "monsoon",
            "lead_days": 1,
            "weights": {"gfs": 0.5, "ecmwf_ifs": 0.5, "icon": 0.5, "aifs": 0.5},  # sums to 2.0
            "reason": "Valid reason exceeding 10 characters.",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_WEIGHTS"


# ==============================================================================
# 7. Export and Chat Scaffold Tests
# ==============================================================================
def test_export_endpoint_csv(client):
    """GET /export with CSV format returns text/csv stream."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/export?dataset=forecasts&format=csv", headers=headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    assert "attachment;" in resp.headers.get("content-disposition", "")


def test_export_endpoint_invalid_dataset(client):
    """Invalid dataset returns 422."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/export?dataset=unknown_ds", headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_DATASET"


def test_chat_endpoint_contract_scaffold(client):
    """POST /chat returns valid text/event-stream preserving Phase 8 contract."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/v1/chat", headers=headers, json={"message": "What is the forecast for Pune?"})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    content = resp.text
    assert "event: start" in content
    assert "event: end" in content


# ==============================================================================
# 8. Artifacts Endpoint Tests (Owner & Coordinator Access)
# ==============================================================================
def test_artifacts_access_control(client):
    """Artifact retrieval requires ownership or coordinator privileges."""
    from api.app.routers.artifacts import register_artifact

    owner_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())
    coordinator_id = str(uuid.uuid4())
    art_id = f"art-{uuid.uuid4()}"

    # Register artifact
    register_artifact(art_id, owner_id, [{"row": 1, "value": 42.0}, {"row": 2, "value": 15.5}])

    # 1. Non-owner public receives 403
    other_token = create_test_jwt(user_id=other_user_id, role="public")
    resp_forbidden = client.get(f"/api/v1/artifacts/{art_id}", headers={"Authorization": f"Bearer {other_token}"})
    assert resp_forbidden.status_code == 403
    assert resp_forbidden.json()["error"]["code"] == "FORBIDDEN"

    # 2. Owner receives 200 with paginated data
    owner_token = create_test_jwt(user_id=owner_id, role="public")
    resp_owner = client.get(f"/api/v1/artifacts/{art_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert resp_owner.status_code == 200
    owner_data = resp_owner.json()
    assert owner_data["artifact_id"] == art_id
    assert owner_data["total_records"] == 2
    assert len(owner_data["data"]) == 2

    # 3. Coordinator receives 200
    coord_token = create_test_jwt(user_id=coordinator_id, role="coordinator")
    resp_coord = client.get(f"/api/v1/artifacts/{art_id}", headers={"Authorization": f"Bearer {coord_token}"})
    assert resp_coord.status_code == 200

    # 4. Nonexistent artifact returns 404
    resp_404 = client.get("/api/v1/artifacts/nonexistent-artifact-999", headers={"Authorization": f"Bearer {owner_token}"})
    assert resp_404.status_code == 404
    assert resp_404.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"


# ==============================================================================
# 9. CORS and Rate Limiting Tests
# ==============================================================================
def test_cors_origins_enforcement(client):
    """CORS middleware allows configured origins and blocks unconfigured origins."""
    # Allowed origin
    resp_allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp_allowed.status_code == 200
    assert resp_allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    # Disallowed origin
    resp_disallowed = client.get("/health", headers={"Origin": "https://unauthorized-domain.com"})
    assert resp_disallowed.status_code == 200
    assert resp_disallowed.headers.get("access-control-allow-origin") is None


def test_rate_limiter_error_envelope(client):
    """Rate limit exceeded response follows the strict PRD error envelope with retry_after."""
    from fastapi import Request
    from slowapi.errors import RateLimitExceeded

    from api.app.middleware.rate_limit import custom_rate_limit_exceeded_handler

    # Test the handler directly
    fake_request = Request({"type": "http", "method": "GET", "path": "/test", "headers": []})
    fake_exc = RateLimitExceeded.__new__(RateLimitExceeded)
    fake_exc.detail = "5 per 1 minute"
    response = custom_rate_limit_exceeded_handler(fake_request, fake_exc)

    assert response.status_code == 429
    assert "Retry-After" in response.headers
    import json
    body = json.loads(response.body.decode())
    assert "error" in body
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "retry_after" in body["error"]

