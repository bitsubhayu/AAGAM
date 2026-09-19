"""Tests for OpenMeteoClient (Rate Limiting, Retries, and 429 Defense)."""

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pipeline.clients.openmeteo import (
    OpenMeteoClient,
    OpenMeteoRateLimitHaltError,
    OpenMeteoServerError,
    RateLimiter,
)


def test_rate_limiter():
    """Verify RateLimiter enforces minimum delay between calls."""
    limiter = RateLimiter(max_per_second=10.0)  # 0.1s per call
    t0 = time.monotonic()
    for _ in range(3):
        limiter.wait()
    t1 = time.monotonic()
    assert (t1 - t0) >= 0.18, f"Expected at least 0.18s elapsed, got {t1 - t0:.3f}s"


def test_estimate_calls():
    """Verify call estimation formula."""
    client = OpenMeteoClient()
    est = client.estimate_calls(num_locations=40, num_models=4, num_batches=3)
    assert est == 120
    client.close()


def test_429_circuit_breaker():
    """Verify that receiving two 429 errors within 1 hour halts execution (FR-DATA-4)."""
    client = OpenMeteoClient()

    mock_resp_429 = MagicMock(spec=httpx.Response)
    mock_resp_429.status_code = 429
    mock_resp_429.headers = {"Retry-After": "0"}  # 0 second sleep for fast test

    with patch("time.sleep", return_value=None):
        # First 429: handled with pause
        client._handle_429(mock_resp_429)
        assert len(client._429_history) == 1

        # Second 429 within 1 hour: raises OpenMeteoRateLimitHaltError
        with pytest.raises(OpenMeteoRateLimitHaltError):
            client._handle_429(mock_resp_429)

    client.close()


def test_retry_on_5xx_server_error():
    """Verify tenacity retries on 5xx server error."""
    client = OpenMeteoClient()

    mock_resp_500 = MagicMock(spec=httpx.Response)
    mock_resp_500.status_code = 500
    mock_resp_500.text = "Internal Server Error"

    call_count = 0

    def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return mock_resp_500

    client.client.get = mock_get

    with patch("time.sleep", return_value=None):
        with pytest.raises(OpenMeteoServerError):
            client._get_with_retry("https://mock-url.com", {})

    # Tenacity should have attempted 3 times
    assert call_count == 3
    client.close()
