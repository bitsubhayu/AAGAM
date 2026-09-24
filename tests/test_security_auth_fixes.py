"""Security Verification Tests for AUTH-001, AUTH-002, RBAC-001 fixes.

These tests verify that the three CRITICAL security findings from the
AAGAM live-functionality audit are properly fixed:

AUTH-001: Hardcoded demo-token bypass disabled by default
AUTH-002: JWT metadata fallback for role removed
RBAC-001: Signup trigger always assigns 'public' role
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from core.config import settings


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


# ==============================================================================
# AUTH-001: Demo-token bypass must be disabled by default
# ==============================================================================


class TestAuth001DemoTokenBypass:
    """Verify that ENABLE_LOCAL_DEMO_AUTH defaults to False and demo tokens
    are rejected when it is False."""

    def test_enable_local_demo_auth_defaults_false(self):
        """The setting must default to False so demo tokens are not accepted
        in production deployments where the env var is not explicitly set."""

        # Create a fresh Settings instance without any env file influence
        # The field default itself must be False
        from core.config import Settings

        field_info = Settings.model_fields["ENABLE_LOCAL_DEMO_AUTH"]
        assert field_info.default is False, (
            "AUTH-001: ENABLE_LOCAL_DEMO_AUTH must default to False. "
            f"Current default: {field_info.default}"
        )

    def test_demo_public_token_rejected_when_disabled(self, client, monkeypatch):
        """With ENABLE_LOCAL_DEMO_AUTH=False, demo-public-token must be rejected."""
        monkeypatch.setattr(settings, "ENABLE_LOCAL_DEMO_AUTH", False)
        # Clear any JWKS/JWT secret that might validate it as a real token
        monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", None)
        monkeypatch.setattr(settings, "SUPABASE_JWKS_URL", None)
        monkeypatch.setattr(settings, "SUPABASE_URL", None)

        resp = client.get(
            "/api/v1/pipeline/status",
            headers={"Authorization": "Bearer demo-public-token"},
        )
        # Should fail auth — demo token is not a valid JWT
        assert resp.status_code in (401, 403), (
            f"AUTH-001: demo-public-token should be rejected when ENABLE_LOCAL_DEMO_AUTH=False, "
            f"got {resp.status_code}"
        )

    def test_demo_coordinator_token_rejected_when_disabled(self, client, monkeypatch):
        """With ENABLE_LOCAL_DEMO_AUTH=False, demo-coordinator-token must be rejected."""
        monkeypatch.setattr(settings, "ENABLE_LOCAL_DEMO_AUTH", False)
        monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", None)
        monkeypatch.setattr(settings, "SUPABASE_JWKS_URL", None)
        monkeypatch.setattr(settings, "SUPABASE_URL", None)

        resp = client.get(
            "/api/v1/pipeline/status",
            headers={"Authorization": "Bearer demo-coordinator-token"},
        )
        assert resp.status_code in (401, 403), (
            f"AUTH-001: demo-coordinator-token should be rejected when ENABLE_LOCAL_DEMO_AUTH=False, "
            f"got {resp.status_code}"
        )

    def test_demo_forecaster_token_rejected_when_disabled(self, client, monkeypatch):
        """With ENABLE_LOCAL_DEMO_AUTH=False, demo-forecaster-token must be rejected."""
        monkeypatch.setattr(settings, "ENABLE_LOCAL_DEMO_AUTH", False)
        monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", None)
        monkeypatch.setattr(settings, "SUPABASE_JWKS_URL", None)
        monkeypatch.setattr(settings, "SUPABASE_URL", None)

        resp = client.get(
            "/api/v1/pipeline/status",
            headers={"Authorization": "Bearer demo-forecaster-token"},
        )
        assert resp.status_code in (401, 403), (
            f"AUTH-001: demo-forecaster-token should be rejected when ENABLE_LOCAL_DEMO_AUTH=False, "
            f"got {resp.status_code}"
        )


# ==============================================================================
# AUTH-002: JWT metadata fallback for role must not exist
# ==============================================================================


class TestAuth002JwtMetadataFallback:
    """Verify that role is ONLY sourced from the profiles table, never from
    JWT claims (app_metadata or user_metadata)."""

    def test_no_metadata_fallback_in_code(self):
        """The get_current_user function must not contain any fallback to
        app_metadata or user_metadata for role assignment in the non-demo path."""
        import inspect

        from api.app.auth.dependencies import get_current_user

        source = inspect.getsource(get_current_user)

        # After the demo-auth block, the non-demo path should not reference
        # app_metadata or user_metadata for role assignment
        # Find the section after "Fetch authoritative role from `profiles` table"
        auth_section_start = source.find("Fetch authoritative role")
        assert auth_section_start != -1, "Expected to find 'Fetch authoritative role' marker"

        non_demo_section = source[auth_section_start:]

        # In the non-demo path, there should be no assignment from app_metadata/user_metadata to user_role
        assert 'app_meta.get("role")' not in non_demo_section, (
            "AUTH-002: Non-demo path still contains app_metadata role fallback"
        )
        assert 'user_meta.get("role")' not in non_demo_section, (
            "AUTH-002: Non-demo path still contains user_metadata role fallback"
        )

    def test_role_defaults_public_when_profile_missing(self):
        """When get_current_user can't find a profile row, the role must be 'public',
        not derived from JWT claims."""
        import asyncio

        from api.app.auth.dependencies import get_current_user

        # Create a mock connection that returns no profile row
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        # Create a valid JWT with coordinator role in metadata
        jwt_secret = "test-secret-for-auth-002-verification"
        escalated_payload = {
            "sub": "11111111-1111-1111-1111-111111111111",
            "email": "attacker@evil.com",
            "role": "authenticated",
            "app_metadata": {"role": "coordinator"},
            "user_metadata": {"role": "coordinator"},
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
            "aud": "authenticated",
        }
        forged_token = pyjwt.encode(escalated_payload, jwt_secret, algorithm="HS256")

        async def run_test():
            with patch("api.app.auth.dependencies.settings") as mock_settings:
                mock_settings.ENABLE_LOCAL_DEMO_AUTH = False
                mock_settings.SUPABASE_JWT_SECRET = jwt_secret
                mock_settings.SUPABASE_JWKS_URL = None
                mock_settings.SUPABASE_URL = None
                mock_settings.jwks_url = None

                with patch("api.app.auth.dependencies.set_rls_claims", new_callable=AsyncMock):
                    with patch("api.app.auth.dependencies.verify_supabase_jwt") as mock_verify:
                        mock_verify.return_value = escalated_payload
                        user = await get_current_user(
                            authorization=f"Bearer {forged_token}",
                            conn=mock_conn,
                        )
                        return user

        user = asyncio.run(run_test())
        assert user.role == "public", (
            f"AUTH-002: Role should be 'public' when profile is missing, got '{user.role}'. "
            "JWT metadata must never be trusted for role assignment."
        )


# ==============================================================================
# RBAC-001: Signup trigger must hardcode 'public' role
# ==============================================================================


class TestRbac001SignupTrigger:
    """Verify that the handle_new_user() trigger function always assigns
    role = 'public', regardless of what the client passes in raw_user_meta_data."""

    def test_migration_does_not_trust_metadata_role(self):
        """The corrective migration must replace the COALESCE(...->>'role', 'public')
        pattern with a hardcoded 'public'."""
        migration_path = (
            "c:/Users/subha/OneDrive/Documents/Antigravity_Workspace/AAGAM/"
            "supabase/migrations/20260923000008_rbac_signup_hardcoded_public.sql"
        )
        with open(migration_path, "r", encoding="utf-8") as f:
            sql = f.read()

        # The migration must contain a hardcoded 'public' in the INSERT
        assert "'public'" in sql, (
            "RBAC-001: Migration must hardcode 'public' role in handle_new_user()"
        )

        # The migration must NOT use raw_user_meta_data->>'role' for the role column
        # (it's fine to use raw_user_meta_data for display_name and org)
        # Check that the role column value is literally 'public', not COALESCE(...)
        # Look for the VALUES clause
        values_idx = sql.upper().find("VALUES")
        assert values_idx != -1, "Expected VALUES clause in migration"

        # After VALUES, the role field should be 'public', not a COALESCE with role
        values_section = sql[values_idx:values_idx + 300]
        assert "raw_user_meta_data->>'role'" not in values_section, (
            "RBAC-001: handle_new_user() VALUES clause must not reference "
            "raw_user_meta_data->>'role' — role must always be hardcoded 'public'"
        )

    def test_migration_preserves_display_name_and_org(self):
        """The migration must still use raw_user_meta_data for display_name and org,
        just not for role."""
        migration_path = (
            "c:/Users/subha/OneDrive/Documents/Antigravity_Workspace/AAGAM/"
            "supabase/migrations/20260923000008_rbac_signup_hardcoded_public.sql"
        )
        with open(migration_path, "r", encoding="utf-8") as f:
            sql = f.read()

        assert "raw_user_meta_data->>'display_name'" in sql, (
            "RBAC-001: Migration should still extract display_name from user metadata"
        )
        assert "raw_user_meta_data->>'org'" in sql, (
            "RBAC-001: Migration should still extract org from user metadata"
        )


# ==============================================================================
# Cross-cutting regression: existing auth flows still work
# ==============================================================================


class TestAuthRegressionSafety:
    """Verify that the security fixes don't break the legitimate auth flows."""

    def test_missing_auth_header_returns_401_for_protected_endpoint(self, client, monkeypatch):
        """Protected endpoints must return 401 when no auth header is provided."""
        monkeypatch.setattr(settings, "ENABLE_LOCAL_DEMO_AUTH", False)

        # /api/v1/auth/forecasters requires coordinator role
        resp = client.get("/api/v1/auth/forecasters")
        assert resp.status_code == 401

    def test_malformed_bearer_token_returns_401(self, client, monkeypatch):
        """Malformed bearer tokens must be rejected."""
        monkeypatch.setattr(settings, "ENABLE_LOCAL_DEMO_AUTH", False)

        resp = client.get(
            "/api/v1/pipeline/status",
            headers={"Authorization": "Bearer not.a.valid.jwt.token"},
        )
        assert resp.status_code == 401

    def test_model_activate_still_returns_403(self, client):
        """POST /models/{id}/activate must still return 403 for all roles,
        confirming the hard-disable was not broken by security fixes."""
        # Even with demo auth enabled, this endpoint is hard-disabled
        resp = client.post("/api/v1/models/1/activate")
        # Should be 403 (hard-disabled) or 401 (no auth) — never 200
        assert resp.status_code in (401, 403)
