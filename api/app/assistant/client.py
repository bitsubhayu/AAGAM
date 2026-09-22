"""Groq SDK client integration with model fallback and telemetry (PRD §8, §9.1, §9.6).

Primary model: openai/gpt-oss-120b
Fallback model: openai/gpt-oss-20b
Configuration: reasoning_effort="low", temperature=0.2
Telemetry: parses x-ratelimit-remaining-tokens and retry-after headers
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from groq import AsyncGroq, RateLimitError

from api.app.assistant.rate_limiter import is_groq_currently_throttled
from core.config import settings

logger = logging.getLogger("aagam.assistant.client")

_groq_client: Optional[AsyncGroq] = None


def get_groq_client() -> AsyncGroq:
    """Returns or initializes the singleton AsyncGroq client."""
    global _groq_client
    if _groq_client is None:
        api_key = settings.GROQ_API_KEY
        if not api_key:
            logger.warning("GROQ_API_KEY is not set. Groq client will operate with mock or raise on execution.")
        _groq_client = AsyncGroq(api_key=api_key or "gsk_missing_key_for_testing")
    return _groq_client


async def call_groq_completion(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = "auto",
    model: Optional[str] = None,
    max_tokens: int = 400,
    temperature: float = 0.2,
) -> Tuple[Any, str, Dict[str, Any]]:
    """Calls Groq chat completion with automatic fallback on 429.

    Returns:
    - response: Groq chat completion object
    - model_used: str
    - metrics: Dict with tokens_in, tokens_out, latency
    """
    client = get_groq_client()
    target_model = model or settings.GROQ_MODEL
    fallback_model = settings.GROQ_FALLBACK_MODEL

    # Check if currently throttled
    throttled, delay = is_groq_currently_throttled()
    if throttled and target_model != fallback_model:
        logger.info(f"Primary model currently throttled (delay {delay}s); attempting fallback {fallback_model}")
        target_model = fallback_model

    kwargs: Dict[str, Any] = {
        "model": target_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # reasoning_effort="low" if model is openai/gpt-oss-120b
    if "gpt-oss-120b" in target_model:
        kwargs["reasoning_effort"] = "low"

    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

    async def _stream_and_build(model_to_use: str, call_kwargs: Dict[str, Any]) -> Tuple[Any, str, Dict[str, Any]]:
        call_kwargs_stream = dict(call_kwargs)
        call_kwargs_stream["stream"] = True
        response_stream = await client.chat.completions.create(**call_kwargs_stream)

        content_chunks: List[str] = []
        tool_calls_dict: Dict[int, Dict[str, str]] = {}
        tokens_in = 0
        tokens_out = 0

        async for chunk in response_stream:
            if hasattr(chunk, "usage") and chunk.usage:
                tokens_in = chunk.usage.prompt_tokens or tokens_in
                tokens_out = chunk.usage.completion_tokens or tokens_out
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_chunks.append(delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_dict:
                        tool_calls_dict[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_dict[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_dict[idx]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls_dict[idx]["arguments"] += tc.function.arguments

        tool_calls = [
            SimpleNamespace(
                id=tc["id"],
                type="function",
                function=SimpleNamespace(
                    name=tc["name"],
                    arguments=tc["arguments"],
                ),
            )
            for tc in tool_calls_dict.values()
        ] if tool_calls_dict else None

        message = SimpleNamespace(
            role="assistant",
            content="".join(content_chunks) if content_chunks else None,
            tool_calls=tool_calls,
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(
                prompt_tokens=tokens_in,
                completion_tokens=tokens_out,
                total_tokens=tokens_in + tokens_out,
            ),
        )
        metrics = {"tokens_in": tokens_in, "tokens_out": tokens_out}
        return response, model_to_use, metrics

    try:
        return await _stream_and_build(target_model, kwargs)

    except RateLimitError as e:
        logger.warning(f"Groq RateLimitError on {target_model}: {e}")
        # Try fallback model if we haven't already
        if target_model != fallback_model:
            logger.info(f"Falling back to {fallback_model} due to 429...")
            kwargs["model"] = fallback_model
            kwargs.pop("reasoning_effort", None)
            try:
                return await _stream_and_build(fallback_model, kwargs)
            except RateLimitError as fb_err:
                logger.error(f"Fallback model also rate limited: {fb_err}")
                raise fb_err
        raise e


async def stream_groq_completion(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    max_tokens: int = 400,
    temperature: float = 0.2,
) -> AsyncGenerator[str, None]:
    """Streams text completion tokens from Groq."""
    client = get_groq_client()
    target_model = model or settings.GROQ_MODEL
    fallback_model = settings.GROQ_FALLBACK_MODEL

    kwargs: Dict[str, Any] = {
        "model": target_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if "gpt-oss-120b" in target_model:
        kwargs["reasoning_effort"] = "low"

    try:
        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            content = chunk.choices[0].delta.content if chunk.choices else None
            if content:
                yield content
    except RateLimitError as e:
        logger.warning(f"Groq RateLimitError while streaming on {target_model}: {e}; trying fallback...")
        if target_model != fallback_model:
            kwargs["model"] = fallback_model
            kwargs.pop("reasoning_effort", None)
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                content = chunk.choices[0].delta.content if chunk.choices else None
                if content:
                    yield content
        else:
            raise e
