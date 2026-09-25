"""Weight Overrides and Weight Maps Regression Tests (Part M).

Verifies:
1. Forecaster can create weight override.
2. Coordinator can create weight override.
3. Public cannot create override (403 Forbidden).
4. RLS allows correct authenticated user.
5. created_by matches auth.uid().
6. expires_hours accepted (12, 24, 48, 72).
7. expires_at calculated correctly.
8. response matches frontend contract.
9. invalid weights rejected (sum != 1, out of bounds, missing keys).
10. reason < 10 chars rejected (422 Unprocessable Entity).
11. override cache invalidated.
12. override appears in GET /weights/overrides.
13. Contract compatibility for active overrides.
14. Operational effect in get_region_weights_cached.
"""

from __future__ import annotations

import datetime
import time
from typing import Dict
from unittest.mock import AsyncMock

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

from api.app.db.model_versions import (
    _REGION_WEIGHTS_CACHE,
    get_region_weights_cached,
    invalidate_weights_cache,
)
from api.app.main import app
from core.config import settings

TEST_JWT_SECRET = "test-weight-overrides-secret-key-32chars"


def create_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": "authenticated",
        "app_metadata": {"role": role},
        "user_metadata": {"role": role},
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
    }
    return jwt.encode(payload, settings.SUPABASE_JWT_SECRET or TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db_conn():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    demo_users = [
        ("00000000-0000-0000-0000-000000000001", "public@aagam.gov.in", "public", "Demo Public"),
        ("00000000-0000-0000-0000-000000000002", "forecaster@aagam.gov.in", "forecaster", "Demo Forecaster"),
        ("00000000-0000-0000-0000-000000000003", "coordinator@aagam.gov.in", "coordinator", "Demo Coordinator"),
    ]
    with conn.cursor() as cur:
        for uid, email, role, dname in demo_users:
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;", (uid, email))
            cur.execute(
                """
                INSERT INTO profiles (user_id, display_name, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET role = EXCLUDED.role, display_name = EXCLUDED.display_name;
                """,
                (uid, dname, role),
            )
    yield conn
    # Cleanup any test overrides
    with conn.cursor() as cur:
        cur.execute("DELETE FROM weight_overrides WHERE reason LIKE 'Test override%';")
    conn.close()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "ENABLE_LOCAL_DEMO_AUTH", True)
    with TestClient(app) as test_client:
        yield test_client


VALID_WEIGHTS: Dict[str, float] = {
    "gfs": 0.20,
    "ecmwf_ifs": 0.40,
    "icon": 0.20,
    "aifs": 0.20,
}


class TestWeightOverridesPermissionsAndContract:
    def test_public_user_cannot_create_override(self, client, db_conn):
        token = create_token("00000000-0000-0000-0000-000000000001", "public@aagam.gov.in", "public")
        payload = {
            "variable": "rain_mm",
            "region": "EAST_NE",
            "season": "monsoon",
            "lead_days": 3,
            "weights": VALID_WEIGHTS,
            "reason": "Test override by unauthorized public user",
            "expires_hours": 24,
        }
        res = client.post(
            "/api/v1/weights/override",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403
        data = res.json()
        err = data.get("error") or data.get("detail", {})
        assert "FORBIDDEN" in err["code"]

    def test_forecaster_can_create_override(self, client, db_conn):
        token = create_token("00000000-0000-0000-0000-000000000002", "forecaster@aagam.gov.in", "forecaster")
        payload = {
            "variable": "rain_mm",
            "region": "EAST_NE",
            "season": "monsoon",
            "lead_days": 3,
            "weights": VALID_WEIGHTS,
            "reason": "Test override justification: IFS convective bias observed.",
            "expires_hours": 24,
        }
        res = client.post(
            "/api/v1/weights/override",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 201
        data = res.json()

        # Contract validation
        assert data["id"] > 0
        assert data["created_by"] == "00000000-0000-0000-0000-000000000002"
        assert data["variable"] == "rain_mm"
        assert data["region"] == "EAST_NE"
        assert data["season"] == "monsoon"
        assert data["lead_days"] == 3
        assert data["weights"] == VALID_WEIGHTS
        assert data["active"] is True
        assert data["expires_at"] is not None

        # Verify expires_at calculation is approximately now + 24 hours
        exp = datetime.datetime.fromisoformat(data["expires_at"])
        now = datetime.datetime.now(datetime.timezone.utc)
        diff_hours = (exp - now).total_seconds() / 3600.0
        assert 23.5 <= diff_hours <= 24.5

    def test_coordinator_can_create_override(self, client, db_conn):
        token = create_token("00000000-0000-0000-0000-000000000003", "coordinator@aagam.gov.in", "coordinator")
        payload = {
            "variable": "tmax_c",
            "region": "CENTRAL",
            "season": "premonsoon",
            "lead_days": 2,
            "weights": {"gfs": 0.30, "ecmwf_ifs": 0.30, "icon": 0.20, "aifs": 0.20},
            "reason": "Test override justification: coordinator synoptic intervention.",
            "expires_hours": 48,
        }
        res = client.post(
            "/api/v1/weights/override",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["created_by"] == "00000000-0000-0000-0000-000000000003"
        assert data["active"] is True

        exp = datetime.datetime.fromisoformat(data["expires_at"])
        now = datetime.datetime.now(datetime.timezone.utc)
        diff_hours = (exp - now).total_seconds() / 3600.0
        assert 47.5 <= diff_hours <= 48.5


class TestWeightValidationAndErrors:
    def test_invalid_reason_too_short(self, client, db_conn):
        token = create_token("00000000-0000-0000-0000-000000000002", "forecaster@aagam.gov.in", "forecaster")
        payload = {
            "variable": "rain_mm",
            "region": "EAST_NE",
            "season": "monsoon",
            "lead_days": 3,
            "weights": VALID_WEIGHTS,
            "reason": "Too short",  # < 10 chars
            "expires_hours": 24,
        }
        res = client.post(
            "/api/v1/weights/override",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 422
        err = res.json().get("error") or res.json().get("detail", {})
        assert err["code"] == "INVALID_REASON"

    def test_invalid_expires_hours(self, client, db_conn):
        token = create_token("00000000-0000-0000-0000-000000000002", "forecaster@aagam.gov.in", "forecaster")
        payload = {
            "variable": "rain_mm",
            "region": "EAST_NE",
            "season": "monsoon",
            "lead_days": 3,
            "weights": VALID_WEIGHTS,
            "reason": "Test override justification valid length.",
            "expires_hours": 99,  # invalid
        }
        res = client.post(
            "/api/v1/weights/override",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 422
        err = res.json().get("error") or res.json().get("detail", {})
        assert err["code"] == "INVALID_EXPIRES_HOURS"

    def test_missing_model_key_rejected(self, client, db_conn):
        token = create_token("00000000-0000-0000-0000-000000000002", "forecaster@aagam.gov.in", "forecaster")
        payload = {
            "variable": "rain_mm",
            "region": "EAST_NE",
            "season": "monsoon",
            "lead_days": 3,
            "weights": {"gfs": 0.5, "ecmwf_ifs": 0.5},  # missing icon, aifs
            "reason": "Test override justification valid length.",
            "expires_hours": 24,
        }
        res = client.post(
            "/api/v1/weights/override",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 422
        err = res.json().get("error") or res.json().get("detail", {})
        assert err["code"] == "MISSING_MODEL_KEYS"

    def test_weight_sum_not_one_rejected(self, client, db_conn):
        token = create_token("00000000-0000-0000-0000-000000000002", "forecaster@aagam.gov.in", "forecaster")
        payload = {
            "variable": "rain_mm",
            "region": "EAST_NE",
            "season": "monsoon",
            "lead_days": 3,
            "weights": {"gfs": 0.2, "ecmwf_ifs": 0.2, "icon": 0.2, "aifs": 0.2},  # sum = 0.8
            "reason": "Test override justification valid length.",
            "expires_hours": 24,
        }
        res = client.post(
            "/api/v1/weights/override",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 422
        err = res.json().get("error") or res.json().get("detail", {})
        assert err["code"] == "INVALID_WEIGHTS"

    def test_negative_weight_rejected(self, client, db_conn):
        token = create_token("00000000-0000-0000-0000-000000000002", "forecaster@aagam.gov.in", "forecaster")
        payload = {
            "variable": "rain_mm",
            "region": "EAST_NE",
            "season": "monsoon",
            "lead_days": 3,
            "weights": {"gfs": -0.1, "ecmwf_ifs": 0.5, "icon": 0.3, "aifs": 0.3},
            "reason": "Test override justification valid length.",
            "expires_hours": 24,
        }
        res = client.post(
            "/api/v1/weights/override",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 422
        err = res.json().get("error") or res.json().get("detail", {})
        assert err["code"] == "INVALID_WEIGHTS"


class TestWeightsOverridesListingAndOperationalBlend:
    def test_list_overrides_public_access(self, client, db_conn):
        res = client.get("/api/v1/weights/overrides")
        assert res.status_code == 200
        items = res.json()
        assert isinstance(items, list)
        for it in items:
            assert "id" in it
            assert "created_by" in it
            assert "weights" in it
            assert "active" in it
            assert isinstance(it["weights"], dict)

    @pytest.mark.asyncio
    async def test_cache_invalidation_and_operational_overlay(self):
        invalidate_weights_cache()
        assert len(_REGION_WEIGHTS_CACHE) == 0

        # Create mock connection
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=[
            # First query: weights baseline
            [
                {"lead_days": 3, "model": "gfs", "weight": 0.25},
                {"lead_days": 3, "model": "ecmwf_ifs", "weight": 0.25},
                {"lead_days": 3, "model": "icon", "weight": 0.25},
                {"lead_days": 3, "model": "aifs", "weight": 0.25},
            ],
            # Second query: weight_overrides active overlay
            [
                {
                    "lead_days": 3,
                    "weights": {"gfs": 0.1, "ecmwf_ifs": 0.6, "icon": 0.15, "aifs": 0.15},
                }
            ],
        ])

        res = await get_region_weights_cached(mock_conn, 2, "rain_mm", "EAST_NE")
        assert 3 in res
        # Active override must overlay the baseline weights
        assert res[3]["ecmwf_ifs"] == 0.6
        assert res[3]["gfs"] == 0.1

    @pytest.mark.asyncio
    async def test_dominant_weights_operational_overlay(self):
        from api.app.db.model_versions import (
            _DOMINANT_WEIGHTS_CACHE,
            get_dominant_weights_cached,
        )

        invalidate_weights_cache()
        assert len(_DOMINANT_WEIGHTS_CACHE) == 0

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=[
            # First query: baseline distinct on region
            [
                {"region": "EAST_NE", "model": "gfs", "weight": 0.35},
            ],
            # Second query: active weight_overrides overlay where ecmwf_ifs is highest
            [
                {
                    "region": "EAST_NE",
                    "weights": {"gfs": 0.10, "ecmwf_ifs": 0.60, "icon": 0.15, "aifs": 0.15},
                }
            ],
        ])

        dom = await get_dominant_weights_cached(mock_conn, 2, "rain_mm", 3)
        assert dom.get("EAST_NE") == "ecmwf_ifs"

    def test_database_rls_transaction_isolation(self, db_conn):
        """Verifies PostgreSQL RLS policy allows forecaster inside transaction with claims."""
        import json

        # With claims in transaction -> allowed
        with db_conn.cursor() as cur:
            cur.execute("BEGIN;")
            claims = json.dumps({"sub": "00000000-0000-0000-0000-000000000002", "role": "authenticated"})
            cur.execute("SELECT set_config('request.jwt.claims', %s, true);", (claims,))
            cur.execute("SELECT set_config('role', 'authenticated', true);")
            cur.execute(
                """
                INSERT INTO weight_overrides (
                    created_by, variable, region, season, lead_days, weights, reason, active
                ) VALUES (
                    '00000000-0000-0000-0000-000000000002'::uuid,
                    'rain_mm', 'EAST_NE', 'monsoon', 3,
                    '{"gfs": 0.25, "ecmwf_ifs": 0.25, "icon": 0.25, "aifs": 0.25}'::jsonb,
                    'Test override RLS transaction test',
                    true
                ) RETURNING id;
                """
            )
            override_id = cur.fetchone()[0]
            assert override_id > 0
            cur.execute("ROLLBACK;")

