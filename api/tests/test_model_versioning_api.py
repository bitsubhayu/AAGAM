"""Unit and integration contract tests for Phase 4: Model Versioning API Endpoints.

Authoritative references:
- AAGAM_MODEL_VERSIONING_DESIGN.md §S, §T
- AAGAM_MODEL_VERSIONING_ANTIGRAVITY_SPEC.md Phase 4
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from api.app.db.pool import get_db_conn
from api.app.main import app
from core.config import settings
from pipeline.versioning.decisions import write_decision

TEST_JWT_SECRET = "test-phase-4-secret-key-very-secure-32-chars-long"


def create_test_jwt(
    user_id: Optional[str] = None,
    email: str = "user@aagam.gov.in",
    role: str = "public",
    secret: str = TEST_JWT_SECRET,
    expires_in: int = 3600,
) -> str:
    """Generates a test JWT signed with TEST_JWT_SECRET with authoritative role claims."""
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


class MockTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockAsyncDBConnection:
    """In-memory mock of asyncpg.Connection populated with standard model versioning state."""

    def __init__(self):
        now = datetime.now(timezone.utc)
        self.model_versions: Dict[int, Dict[str, Any]] = {
            1: {
                "id": 1,
                "status": "superseded",
                "algorithm_type": "ridge_lgbm_v1",
                "evaluation_policy": "legacy_single_gate",
                "is_active": False,
                "parent_version_id": None,
                "created_at": now,
                "activated_at": now,
                "deactivated_at": now,
                "created_by": "pipeline:legacy",
            },
            2: {
                "id": 2,
                "status": "active",
                "algorithm_type": "ridge_lgbm_v1",
                "evaluation_policy": "legacy_single_gate",
                "is_active": True,
                "parent_version_id": 1,
                "created_at": now,
                "activated_at": now,
                "deactivated_at": None,
                "created_by": "pipeline:legacy",
            },
            3: {
                "id": 3,
                "status": "candidate",
                "algorithm_type": "ridge_lgbm_v2",
                "evaluation_policy": "staged_v2",
                "is_active": False,
                "parent_version_id": 2,
                "created_at": now,
                "activated_at": None,
                "deactivated_at": None,
                "created_by": "pipeline:train-weekly",
                "shadow_started_at": None,
                "canary_started_at": None,
            },
        }

        self.evaluations: List[Dict[str, Any]] = [
            {
                "id": 101,
                "version_id": 2,
                "pipeline_run_id": 501,
                "window_type": "recent",
                "window_start": "2026-09-01",
                "window_end": "2026-09-14",
                "composite_score": 0.885,
                "strata_included": 45,
                "strata_excluded": 3,
                "regions_covered": 5,
                "locations_covered": 40,
                "lead_days_covered": 8,
                "sample_counts": {"rain_mm": 560, "tmax_c": 560, "wind_max_kmh": 560},
                "metrics_detail": {"composite_mae": 1.25, "csi": 0.65},
                "computed_at": now,
            }
        ]

        self.decisions: List[Dict[str, Any]] = [
            {
                "id": 1,
                "decision": "PROMOTED",
                "previous_version_id": 1,
                "candidate_version_id": 2,
                "composite_recent_prev": 0.82,
                "composite_recent_cand": 0.885,
                "composite_seasonal_prev": 0.80,
                "composite_seasonal_cand": 0.85,
                "composite_longterm_prev": 0.79,
                "composite_longterm_cand": 0.84,
                "sample_counts": {"total": 1200},
                "evaluation_window_start": "2026-08-01",
                "evaluation_window_end": "2026-09-01",
                "reason": "Passed multi-metric evaluation gate",
                "triggered_by": "pipeline:scheduled",
                "pipeline_run_id": 500,
                "algorithm_version": "staged_v2",
                "created_at": now,
            }
        ]

        self.automation_state = {
            "id": 1,
            "frozen": False,
            "frozen_reason": None,
            "frozen_by": None,
            "frozen_at": None,
            "cooldown_until": None,
            "rollback_count_14d": 0,
            "updated_at": now,
        }

    def transaction(self):
        return MockTransaction()

    async def execute(self, query: str, *args) -> str:
        q = query.strip()
        if "UPDATE model_switching_automation_state" in q:
            if "SET frozen = true" in q:
                self.automation_state["frozen"] = True
                self.automation_state["frozen_reason"] = args[0]
                if len(args) > 1 and args[1]:
                    self.automation_state["frozen_by"] = args[1]
                self.automation_state["frozen_at"] = datetime.now(timezone.utc)
            elif "SET frozen = false" in q:
                self.automation_state["frozen"] = False
                self.automation_state["frozen_reason"] = None
                self.automation_state["frozen_by"] = None
                self.automation_state["frozen_at"] = None
            self.automation_state["updated_at"] = datetime.now(timezone.utc)
            return "UPDATE 1"

        if "INSERT INTO model_version_decisions" in q:
            decision = args[0]
            if len(args) == 5:
                # frozen / unfreeze
                reason = args[1]
                triggered_by = args[2]
                algo_ver = args[3]
                new_id = len(self.decisions) + 1
                self.decisions.insert(
                    0,
                    {
                        "id": new_id,
                        "decision": decision,
                        "previous_version_id": None,
                        "candidate_version_id": None,
                        "composite_recent_prev": None,
                        "composite_recent_cand": None,
                        "composite_seasonal_prev": None,
                        "composite_seasonal_cand": None,
                        "composite_longterm_prev": None,
                        "composite_longterm_cand": None,
                        "sample_counts": {},
                        "evaluation_window_start": None,
                        "evaluation_window_end": None,
                        "reason": reason,
                        "triggered_by": triggered_by,
                        "pipeline_run_id": None,
                        "algorithm_version": algo_ver,
                        "created_at": datetime.now(timezone.utc),
                    },
                )
            elif len(args) == 6:
                # candidate disable: decision, candidate_id, reason, triggered_by, algo_ver, sample_counts
                cand_id = args[1]
                reason = args[2]
                triggered_by = args[3]
                algo_ver = args[4]
                new_id = len(self.decisions) + 1
                self.decisions.insert(
                    0,
                    {
                        "id": new_id,
                        "decision": decision,
                        "previous_version_id": None,
                        "candidate_version_id": cand_id,
                        "composite_recent_prev": None,
                        "composite_recent_cand": None,
                        "composite_seasonal_prev": None,
                        "composite_seasonal_cand": None,
                        "composite_longterm_prev": None,
                        "composite_longterm_cand": None,
                        "sample_counts": {},
                        "evaluation_window_start": None,
                        "evaluation_window_end": None,
                        "reason": reason,
                        "triggered_by": triggered_by,
                        "pipeline_run_id": None,
                        "algorithm_version": algo_ver,
                        "created_at": datetime.now(timezone.utc),
                    },
                )
            elif len(args) == 7:
                # force-last-known-good: decision, prev_id, cand_id, reason, triggered_by, algo_ver, counts
                prev_id = args[1]
                cand_id = args[2]
                reason = args[3]
                triggered_by = args[4]
                algo_ver = args[5]
                new_id = len(self.decisions) + 1
                self.decisions.insert(
                    0,
                    {
                        "id": new_id,
                        "decision": decision,
                        "previous_version_id": prev_id,
                        "candidate_version_id": cand_id,
                        "composite_recent_prev": None,
                        "composite_recent_cand": None,
                        "composite_seasonal_prev": None,
                        "composite_seasonal_cand": None,
                        "composite_longterm_prev": None,
                        "composite_longterm_cand": None,
                        "sample_counts": {},
                        "evaluation_window_start": None,
                        "evaluation_window_end": None,
                        "reason": reason,
                        "triggered_by": triggered_by,
                        "pipeline_run_id": None,
                        "algorithm_version": algo_ver,
                        "created_at": datetime.now(timezone.utc),
                    },
                )
            return "INSERT 1"

        if "UPDATE model_versions" in q:
            ver_id = args[0]
            if "status = 'rolled_back'" in q:
                if ver_id in self.model_versions:
                    self.model_versions[ver_id]["is_active"] = False
                    self.model_versions[ver_id]["status"] = "rolled_back"
                    self.model_versions[ver_id]["deactivated_at"] = datetime.now(timezone.utc)
            elif "status = 'active'" in q:
                if ver_id in self.model_versions:
                    self.model_versions[ver_id]["is_active"] = True
                    self.model_versions[ver_id]["status"] = "active"
                    self.model_versions[ver_id]["activated_at"] = datetime.now(timezone.utc)
            elif "status = 'rejected'" in q:
                if ver_id in self.model_versions:
                    self.model_versions[ver_id]["status"] = "rejected"
            return "UPDATE 1"

        return "OK"

    async def fetchrow(self, query: str, *args) -> Optional[Dict[str, Any]]:
        q = query.strip()
        if "UPDATE model_versions" in q and "RETURNING" in q:
            vid = args[0]
            if vid in self.model_versions:
                if "SET status = 'rejected'" in q:
                    self.model_versions[vid]["status"] = "rejected"
                return dict(self.model_versions[vid])
            return None

        if "FROM model_versions" in q:
            if "is_active = true" in q:
                for v in self.model_versions.values():
                    if v["is_active"]:
                        return dict(v)
                return None
            if "WHERE id = $1" in q:
                vid = args[0]
                return dict(self.model_versions[vid]) if vid in self.model_versions else None
            if "status IN ('candidate', 'evaluating', 'eligible', 'shadow', 'canary')" in q:
                for v in sorted(self.model_versions.values(), key=lambda x: x["id"], reverse=True):
                    if v["status"] in ("candidate", "evaluating", "eligible", "shadow", "canary"):
                        return dict(v)
                return None

        if "FROM model_version_evaluations" in q:
            vid = args[0]
            for ev in self.evaluations:
                if ev["version_id"] == vid:
                    return dict(ev)
            return None

        if "FROM model_switching_automation_state" in q:
            return dict(self.automation_state)

        return None

    async def fetch(self, query: str, *args) -> List[Dict[str, Any]]:
        q = query.strip()
        if "FROM model_versions" in q:
            return [dict(v) for v in sorted(self.model_versions.values(), key=lambda x: x["id"], reverse=True)]

        if "FROM model_version_evaluations" in q:
            vid = args[0]
            res = [ev for ev in self.evaluations if ev["version_id"] == vid]
            if len(args) > 1 and args[1]:
                res = [ev for ev in res if ev["window_type"] == args[1]]
            return [dict(x) for x in res]

        if "FROM model_version_decisions" in q:
            res = list(self.decisions)
            return [dict(x) for x in res]

        return []


@pytest.fixture
def mock_db():
    return MockAsyncDBConnection()


@pytest.fixture
def client(monkeypatch, mock_db):
    """Configures TestClient with mock JWT secrets and mock DB connection."""
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "ENABLE_LOCAL_DEMO_AUTH", True)

    async def override_get_db_conn() -> AsyncGenerator[Any, None]:
        yield mock_db

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Complete Role Authorization Matrix (3 roles × 9 endpoints = 27 vectors)
# ==============================================================================

ROLE_MATRIX_CASES = [
    # (method, path, body, expected_public, expected_forecaster, expected_coordinator)
    ("GET", "/api/v1/models/active", None, 200, 200, 200),
    ("GET", "/api/v1/models/versions", None, 200, 200, 200),
    ("GET", "/api/v1/models/versions/2/evaluations", None, 200, 200, 200),
    ("GET", "/api/v1/models/decisions", None, 200, 200, 200),
    ("GET", "/api/v1/models/automation/status", None, 403, 200, 200),
    ("POST", "/api/v1/models/automation/freeze", {"reason": "Routine manual freeze check"}, 403, 403, 403),
    ("POST", "/api/v1/models/automation/unfreeze", {"reason": "Routine manual unfreeze check"}, 403, 403, 403),
    ("POST", "/api/v1/models/automation/force-last-known-good", {"reason": "Testing manual rollback action"}, 403, 403, 403),
    ("POST", "/api/v1/models/candidates/3/disable", {"reason": "Manual rejection of candidate"}, 403, 403, 403),
]


@pytest.mark.parametrize(
    "method, path, body, expected_public, expected_forecaster, expected_coordinator",
    ROLE_MATRIX_CASES,
)
def test_complete_role_authorization_matrix(
    client,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]],
    expected_public: int,
    expected_forecaster: int,
    expected_coordinator: int,
):
    """Validates the exact 3x9 role authorization matrix for public, forecaster, and coordinator roles."""
    roles_and_expectations = [
        ("public", expected_public),
        ("forecaster", expected_forecaster),
        ("coordinator", expected_coordinator),
    ]

    for role, expected_status in roles_and_expectations:
        token = create_test_jwt(role=role)
        headers = {"Authorization": f"Bearer {token}"}

        if method == "GET":
            resp = client.get(path, headers=headers)
        elif method == "POST":
            resp = client.post(path, headers=headers, json=body or {})
        else:
            raise ValueError(f"Unsupported method {method}")

        assert resp.status_code == expected_status, (
            f"Failed role matrix: role={role}, endpoint={method} {path}. "
            f"Expected {expected_status}, got {resp.status_code}: {resp.text}"
        )


def test_anonymous_unauthenticated_role_matrix(client):
    """Anonymous unauthenticated requests should access public endpoints but get 403 on protected and disabled endpoints."""
    # 4 Public endpoints succeed
    assert client.get("/api/v1/models/active").status_code == 200
    assert client.get("/api/v1/models/versions").status_code == 200
    assert client.get("/api/v1/models/versions/2/evaluations").status_code == 200
    assert client.get("/api/v1/models/decisions").status_code == 200

    # 1 Forecaster+ endpoint rejected with 403 for anonymous (public tier)
    assert client.get("/api/v1/models/automation/status").status_code == 403

    # 4 Human mutation endpoints permanently hard-disabled (403 OPERATION_DISALLOWED)
    assert client.post("/api/v1/models/automation/freeze", json={"reason": "Valid reason 10+"}).status_code == 403
    assert client.post("/api/v1/models/automation/unfreeze", json={"reason": "Valid reason 10+"}).status_code == 403
    assert client.post("/api/v1/models/automation/force-last-known-good", json={"reason": "Valid reason 10+"}).status_code == 403
    assert client.post("/api/v1/models/candidates/3/disable", json={"reason": "Valid reason 10+"}).status_code == 403


def test_automation_status_rbac_matrix(client):
    """GET /models/automation/status authoritative requirement:
    - public/anonymous: 403
    - forecaster: 200
    - coordinator: 200
    """
    # 1. Anonymous (unauthenticated): 403
    resp_anon = client.get("/api/v1/models/automation/status")
    assert resp_anon.status_code == 403
    assert resp_anon.json()["error"]["code"] == "FORBIDDEN"

    # 2. Public role: 403
    pub_token = create_test_jwt(role="public")
    resp_pub = client.get("/api/v1/models/automation/status", headers={"Authorization": f"Bearer {pub_token}"})
    assert resp_pub.status_code == 403
    assert resp_pub.json()["error"]["code"] == "FORBIDDEN"

    # 3. Forecaster role: 200
    forecaster_token = create_test_jwt(role="forecaster")
    resp_forecaster = client.get("/api/v1/models/automation/status", headers={"Authorization": f"Bearer {forecaster_token}"})
    assert resp_forecaster.status_code == 200
    assert "frozen" in resp_forecaster.json()

    # 4. Coordinator role: 200
    coord_token = create_test_jwt(role="coordinator")
    resp_coord = client.get("/api/v1/models/automation/status", headers={"Authorization": f"Bearer {coord_token}"})
    assert resp_coord.status_code == 200
    assert "frozen" in resp_coord.json()


# ==============================================================================
# 2. Detailed Functional & Audit Tests
# ==============================================================================

def test_models_active_returns_active_version_and_evaluation(client):
    """GET /models/active returns the current active model and its latest evaluation summary."""
    resp = client.get("/api/v1/models/active")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 2
    assert data["status"] == "active"
    assert data["is_active"] is True
    assert data["recent_evaluation"] is not None
    assert data["recent_evaluation"]["composite_score"] == 0.885


def test_models_versions_returns_lifecycle_metadata(client):
    """GET /models/versions returns complete version list with statuses."""
    resp = client.get("/api/v1/models/versions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    ids = [v["id"] for v in data]
    assert 2 in ids
    assert 3 in ids


def test_models_evaluations_returns_records(client):
    """GET /models/versions/{id}/evaluations returns evaluation records for existing version."""
    resp = client.get("/api/v1/models/versions/2/evaluations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["version_id"] == 2
    assert data[0]["window_type"] == "recent"

    # Non-existent version returns 404
    resp_404 = client.get("/api/v1/models/versions/9999/evaluations")
    assert resp_404.status_code == 404
    assert resp_404.json()["error"]["code"] == "MODEL_VERSION_NOT_FOUND"


def test_models_decisions_returns_audit_trail(client):
    """GET /models/decisions returns paginated audit records."""
    resp = client.get("/api/v1/models/decisions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["decision"] == "PROMOTED"


def test_models_automation_status(client):
    """GET /models/automation/status returns automation state and active candidate."""
    token = create_test_jwt(role="forecaster")
    resp = client.get("/api/v1/models/automation/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["frozen"] is False
    assert data["current_candidate"] is not None
    assert data["current_candidate"]["id"] == 3


def test_coordinator_cannot_freeze_model_automation(client):
    """POST /models/automation/freeze is permanently hard-disabled (403 OPERATION_DISALLOWED)."""
    token = create_test_jwt(role="coordinator")
    resp = client.post(
        "/api/v1/models/automation/freeze",
        headers={"Authorization": f"Bearer {token}"},
        json={"reason": "Coordinator attempt to pause automated switching"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "OPERATION_DISALLOWED"


def test_coordinator_cannot_unfreeze_model_automation(client):
    """POST /models/automation/unfreeze is permanently hard-disabled (403 OPERATION_DISALLOWED)."""
    token = create_test_jwt(role="coordinator")
    resp = client.post(
        "/api/v1/models/automation/unfreeze",
        headers={"Authorization": f"Bearer {token}"},
        json={"reason": "Coordinator attempt to resume automated switching"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "OPERATION_DISALLOWED"


def test_coordinator_cannot_force_last_known_good(client):
    """POST /models/automation/force-last-known-good is permanently hard-disabled (403 OPERATION_DISALLOWED)."""
    token = create_test_jwt(role="coordinator")
    resp = client.post(
        "/api/v1/models/automation/force-last-known-good",
        headers={"Authorization": f"Bearer {token}"},
        json={"reason": "Coordinator attempt to force manual rollback"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "OPERATION_DISALLOWED"


def test_coordinator_cannot_disable_candidate(client):
    """POST /models/candidates/{id}/disable is permanently hard-disabled (403 OPERATION_DISALLOWED)."""
    token = create_test_jwt(role="coordinator")
    resp = client.post(
        "/api/v1/models/candidates/3/disable",
        headers={"Authorization": f"Bearer {token}"},
        json={"reason": "Coordinator attempt to disable candidate model"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "OPERATION_DISALLOWED"


def test_all_roles_cannot_invoke_mutation_controls(client):
    """Verifies that all roles (public, forecaster, coordinator) are rejected with 403 OPERATION_DISALLOWED on all mutation controls."""
    mutation_endpoints = [
        ("POST", "/api/v1/models/automation/freeze", {"reason": "Freeze attempt"}),
        ("POST", "/api/v1/models/automation/unfreeze", {"reason": "Unfreeze attempt"}),
        ("POST", "/api/v1/models/automation/force-last-known-good", {"reason": "Rollback attempt"}),
        ("POST", "/api/v1/models/candidates/3/disable", {"reason": "Disable attempt"}),
    ]

    for role in ("public", "forecaster", "coordinator"):
        token = create_test_jwt(role=role)
        headers = {"Authorization": f"Bearer {token}"}
        for method, path, body in mutation_endpoints:
            resp = client.post(path, headers=headers, json=body)
            assert resp.status_code == 403, (
                f"Role {role} was not rejected with 403 on {path}. Got {resp.status_code}: {resp.text}"
            )
            assert resp.json()["error"]["code"] == "OPERATION_DISALLOWED"


def test_existing_models_activate_remains_hard_disabled(client):
    """Existing POST /models/{id}/activate must remain unconditionally disabled (403 OPERATION_DISALLOWED)."""
    # Coordinator attempting to call /models/{id}/activate
    token = create_test_jwt(role="coordinator")
    resp = client.post(
        "/api/v1/models/1/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "OPERATION_DISALLOWED"
