"""Controlled rate-limit (HTTP 429) and model fallback test suite for AAGAM Assistant.

Validates PRD §9.3 & §9.8 requirements:
1. Primary model (openai/gpt-oss-120b) returning 429 fails over to fallback model (openai/gpt-oss-20b).
2. Rate limit throttle is activated to protect primary quota.
3. Fallback execution returns a valid response without hanging or infinite retrying.
4. When both primary and fallback models return 429, a structured RATE_LIMITED error is emitted
   with retry_after and user-friendly assistant-busy text.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from groq import RateLimitError

from api.app.assistant.client import call_groq_completion
from api.app.assistant.rate_limiter import (
    is_groq_currently_throttled,
    reset_rate_limits_for_testing,
    set_groq_throttle,
)
from api.app.assistant.runner import run_assistant_stream
from api.app.assistant.schemas import ChatRequest
from api.app.auth.dependencies import CurrentUser


def _make_mock_429_error(model: str = "openai/gpt-oss-120b", retry_after: float = 2.0) -> RateLimitError:
    """Builds a realistic groq.RateLimitError."""
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(429, request=req, headers={"retry-after": str(retry_after)})
    body = {
        "error": {
            "message": f"Rate limit reached for model `{model}` on tokens per minute (TPM). Please try again in {retry_after}s.",
            "type": "tokens",
            "code": "rate_limit_exceeded",
        }
    }
    return RateLimitError("Rate limit reached", response=resp, body=body)


class MockChunk:
    def __init__(self, content: str = "", tool_calls=None):
        delta = AsyncMock()
        delta.content = content
        delta.tool_calls = tool_calls
        self.choices = [AsyncMock(delta=delta)]
        self.usage = None


async def _mock_stream_generator(chunks):
    for c in chunks:
        yield c


@pytest.mark.asyncio
async def test_primary_429_invokes_fallback_model():
    """Verifies that primary model HTTP 429 automatically fails over to openai/gpt-oss-20b."""
    reset_rate_limits_for_testing()

    call_history = []

    async def mock_create(**kwargs):
        model = kwargs.get("model")
        call_history.append(model)
        if "gpt-oss-120b" in model:
            raise _make_mock_429_error(model="openai/gpt-oss-120b", retry_after=1.5)
        elif "gpt-oss-20b" in model:
            return _mock_stream_generator([
                MockChunk(content="Nagpur "),
                MockChunk(content="forecast retrieved successfully."),
            ])
        raise ValueError(f"Unexpected model {model}")

    with patch("api.app.assistant.client.get_groq_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)
        mock_get_client.return_value = mock_client

        req = ChatRequest(message="What is the forecast for Nagpur?", mode="explain")
        user = CurrentUser(user_id="test-fallback-user", role="authenticated")

        events = []
        async for event_str in run_assistant_stream(req, user):
            events.append(event_str)

    # 1. Primary was called first, then fallback was called
    assert len(call_history) >= 2, f"Expected at least 2 calls, got: {call_history}"
    assert "openai/gpt-oss-120b" in call_history[0]
    assert "openai/gpt-oss-20b" in call_history[1]

    # 2. Rate limiter throttle was activated
    throttled, delay = is_groq_currently_throttled()
    assert throttled is True
    assert delay > 0

    # 3. Response completed with done event and content
    event_names = [e.split("\n")[0].replace("event: ", "").strip() for e in events if e.startswith("event:")]
    assert "meta" in event_names
    assert "token" in event_names
    assert "done" in event_names

    token_text = "".join(
        json.loads(e.split("data: ")[1].strip()).get("content", "")
        for e in events
        if e.startswith("event: token")
    )
    assert "Nagpur" in token_text

    reset_rate_limits_for_testing()


@pytest.mark.asyncio
async def test_both_models_429_returns_assistant_busy():
    """Verifies that when both primary and fallback models return 429, structured error is returned."""
    reset_rate_limits_for_testing()

    call_count = 0

    async def mock_create_all_429(**kwargs):
        nonlocal call_count
        call_count += 1
        model = kwargs.get("model", "")
        raise _make_mock_429_error(model=model, retry_after=15.0)

    with patch("api.app.assistant.client.get_groq_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_create_all_429)
        mock_get_client.return_value = mock_client

        req = ChatRequest(message="Rainfall forecast for Mumbai", mode="explain")
        user = CurrentUser(user_id="test-all-429-user", role="authenticated")

        events = []
        async for event_str in run_assistant_stream(req, user):
            events.append(event_str)

    # Must terminate without infinite retry (bounded calls)
    assert call_count <= 4, f"Too many retry calls made: {call_count}"

    # Verify structured RATE_LIMITED error
    error_events = [e for e in events if "event: error" in e]
    assert len(error_events) >= 1, f"Expected error event, got: {events}"

    error_data = json.loads(error_events[0].split("data: ")[1].strip())
    assert error_data.get("code") == "RATE_LIMITED"
    assert "Assistant busy — try again in 15 seconds." in error_data.get("message", "")
    assert error_data.get("retry_after") == 15

    reset_rate_limits_for_testing()


@pytest.mark.asyncio
async def test_groq_throttle_bypasses_primary_directly():
    """Verifies that while throttled, calls bypass 120b and directly invoke 20b."""
    reset_rate_limits_for_testing()
    set_groq_throttle(120.0)

    models_called = []

    async def mock_create(**kwargs):
        model = kwargs.get("model")
        models_called.append(model)
        return _mock_stream_generator([
            MockChunk(content="Direct fallback response"),
        ])

    with patch("api.app.assistant.client.get_groq_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)
        mock_get_client.return_value = mock_client

        resp, used_model, metrics = await call_groq_completion(
            messages=[{"role": "user", "content": "Hello"}],
            model="openai/gpt-oss-120b",
        )

    # Primary 120b was NEVER called because throttle was active
    assert "openai/gpt-oss-120b" not in models_called
    assert "openai/gpt-oss-20b" in models_called
    assert used_model == "openai/gpt-oss-20b"

    reset_rate_limits_for_testing()
