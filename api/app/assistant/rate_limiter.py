"""Rate limiter and Groq 429 handler for AAGAM Assistant (PRD §9.6, §8).

Provides:
- Per-user rate limiting (~15 questions per hour)
- Global token consumption tracker
- Parsing of `x-ratelimit-remaining-tokens` and `retry-after`
- Structured retry-timing calculator on 429
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("aagam.assistant.rate_limiter")

# User rate limit: 15 questions per hour (PRD §9.6)
USER_HOURLY_LIMIT = 15
USER_WINDOW_SECONDS = 3600

# Groq limits tracker
_USER_CALL_TIMESTAMPS: Dict[str, List[float]] = defaultdict(list)
_GLOBAL_RATE_LIMIT_REMAINING_TOKENS: Optional[int] = None
_GLOBAL_RETRY_AFTER_UNTIL: float = 0.0


def check_user_rate_limit(user_id: str) -> Tuple[bool, int]:
    """Checks if the user is within their hourly question limit.

    Returns:
    - allowed: bool
    - retry_after_seconds: int (0 if allowed)
    """
    if not user_id:
        user_id = "anonymous"

    now = time.time()
    cutoff = now - USER_WINDOW_SECONDS

    # Filter out timestamps older than 1 hour
    recent = [t for t in _USER_CALL_TIMESTAMPS[user_id] if t > cutoff]
    _USER_CALL_TIMESTAMPS[user_id] = recent

    if len(recent) >= USER_HOURLY_LIMIT:
        oldest_in_window = recent[0]
        retry_after = max(1, int(oldest_in_window + USER_WINDOW_SECONDS - now))
        logger.warning(f"User {user_id} exceeded hourly limit ({USER_HOURLY_LIMIT}/hr). Retry after {retry_after}s.")
        return False, retry_after

    return True, 0


def record_user_request(user_id: str) -> None:
    """Records a completed request timestamp for the user."""
    if not user_id:
        user_id = "anonymous"
    _USER_CALL_TIMESTAMPS[user_id].append(time.time())


def update_groq_rate_limits(headers: Dict[str, str]) -> None:
    """Updates rate limit telemetry from Groq response headers."""
    global _GLOBAL_RATE_LIMIT_REMAINING_TOKENS, _GLOBAL_RETRY_AFTER_UNTIL

    if not headers:
        return

    # Look for remaining tokens header (case-insensitive)
    for k, v in headers.items():
        k_lower = k.lower()
        if k_lower == "x-ratelimit-remaining-tokens":
            try:
                _GLOBAL_RATE_LIMIT_REMAINING_TOKENS = int(v)
            except ValueError:
                pass
        elif k_lower == "retry-after":
            try:
                delay = float(v)
                _GLOBAL_RETRY_AFTER_UNTIL = max(_GLOBAL_RETRY_AFTER_UNTIL, time.time() + delay)
            except ValueError:
                pass


def is_groq_currently_throttled() -> Tuple[bool, int]:
    """Checks if Groq is currently throttled based on retry-after."""
    now = time.time()
    if now < _GLOBAL_RETRY_AFTER_UNTIL:
        delay = max(1, int(_GLOBAL_RETRY_AFTER_UNTIL - now))
        return True, delay
    return False, 0


def set_groq_throttle(delay_seconds: float = 300.0) -> None:
    """Explicitly sets Groq throttle cooldown period upon 429."""
    global _GLOBAL_RETRY_AFTER_UNTIL
    _GLOBAL_RETRY_AFTER_UNTIL = max(_GLOBAL_RETRY_AFTER_UNTIL, time.time() + delay_seconds)


def reset_rate_limits_for_testing() -> None:
    """Resets all limiters (used in tests)."""
    global _USER_CALL_TIMESTAMPS, _GLOBAL_RATE_LIMIT_REMAINING_TOKENS, _GLOBAL_RETRY_AFTER_UNTIL
    _USER_CALL_TIMESTAMPS.clear()
    _GLOBAL_RATE_LIMIT_REMAINING_TOKENS = None
    _GLOBAL_RETRY_AFTER_UNTIL = 0.0
