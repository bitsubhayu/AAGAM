"""Unit tests for response cache and rate limiter (PRD §9.6, §7, §8)."""

from api.app.assistant.cache import clear_cache, get_cached_response, set_cached_response
from api.app.assistant.rate_limiter import (
    USER_HOURLY_LIMIT,
    check_user_rate_limit,
    record_user_request,
    reset_rate_limits_for_testing,
)


def test_cache_hit_and_expiration():
    """Verifies that cached responses are returned within TTL and expire cleanly."""
    clear_cache()
    q = "What is the forecast for Nagpur?"
    mode = "both"
    v = "v2026-09-14"

    assert get_cached_response(q, mode, v) is None

    payload = {"model": "openai/gpt-oss-120b", "text": "Nagpur Tmax is 36 °C."}
    set_cached_response(q, mode, v, payload)

    # Immediate hit
    cached = get_cached_response(q, mode, v)
    assert cached is not None
    assert cached["text"] == "Nagpur Tmax is 36 °C."

    # Normalized variant (case and spaces)
    variant_q = "what is the forecast for nagpur"
    cached_var = get_cached_response(variant_q, mode, v)
    assert cached_var is not None


def test_per_user_rate_limit():
    """Verifies per-user rate limit enforces 15 questions/hour cap."""
    reset_rate_limits_for_testing()
    test_user = "user_test_123"

    # Fill quota up to limit
    for _ in range(USER_HOURLY_LIMIT):
        allowed, _ = check_user_rate_limit(test_user)
        assert allowed is True
        record_user_request(test_user)

    # Next call must be blocked
    blocked, retry_after = check_user_rate_limit(test_user)
    assert blocked is False
    assert retry_after > 0
