"""Rate limiting configuration for AAGAM API using slowapi."""

from __future__ import annotations

from typing import Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


def rate_limit_key_func(request: Request) -> str:
    """Returns authenticated user identifier or client IP address for rate limiting."""
    auth_header: Optional[str] = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
        # Use first 32 chars of token or client IP
        return f"user:{token[:32]}"
    return get_remote_address(request) or "127.0.0.1"


limiter = Limiter(
    key_func=rate_limit_key_func,
    default_limits=["120/minute"],
    headers_enabled=True,
)


def custom_rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Formats rate limit exceeded errors to match PRD standard error envelope."""
    # Extract retry_after or default to 60
    retry_after = 60
    if hasattr(exc, "detail") and isinstance(exc.detail, str):
        import re
        m = re.search(r"(\d+)\s*second", exc.detail)
        if m:
            retry_after = int(m.group(1))

    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit exceeded: {exc.detail}",
                "retry_after": retry_after,
            }
        },
        headers={"Retry-After": str(retry_after)},
    )
