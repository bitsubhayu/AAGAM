import pytest

from core.config import settings


@pytest.fixture(autouse=True)
def setup_api_test_environment(monkeypatch):
    """Automatically configures test secrets for JWT and export token signing across API tests."""
    monkeypatch.setattr(settings, "EXPORT_SIGNING_SECRET", "test-export-signing-secret-32-chars-long")
    if not settings.SUPABASE_JWT_SECRET:
        monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", "test-phase-6-secret-key-very-secure-32-chars-long")
    # Enable demo auth for tests — demo tokens are required by test fixtures.
    # In production, ENABLE_LOCAL_DEMO_AUTH defaults to False (AUTH-001 fix).
    monkeypatch.setattr(settings, "ENABLE_LOCAL_DEMO_AUTH", True)
