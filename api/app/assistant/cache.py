"""Response cache for AAGAM Assistant (PRD §9.6, §7).

Caches assistant responses for ~10 minutes using:
SHA256(normalized_question + mode + active_model_version)

Avoids redundant LLM & DB calls for identical questions within the TTL window.
Provides `cached: bool` indicator for the SSE meta event.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Dict, Optional

# 10 minutes TTL in seconds (PRD §9.6)
CACHE_TTL_SECONDS = 600

_CACHE_STORE: Dict[str, Dict[str, Any]] = {}


def normalize_question(question: str) -> str:
    """Normalizes question text for robust caching."""
    q = question.lower().strip()
    # Replace multiple spaces with a single space
    q = re.sub(r"\s+", " ", q)
    # Strip standard ending punctuation
    q = q.rstrip("?.!")
    return q


def generate_cache_key(question: str, mode: str, model_version: str) -> str:
    """Generates deterministic cache key."""
    norm_q = normalize_question(question)
    raw_key = f"{norm_q}:{mode.lower().strip()}:{model_version.strip()}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_cached_response(
    question: str,
    mode: str,
    model_version: str,
) -> Optional[Dict[str, Any]]:
    """Retrieves cached response if fresh (TTL <= 10m)."""
    key = generate_cache_key(question, mode, model_version)
    entry = _CACHE_STORE.get(key)
    if not entry:
        return None

    now = time.time()
    if now - entry["timestamp"] > CACHE_TTL_SECONDS:
        # Expired
        _CACHE_STORE.pop(key, None)
        return None

    return entry["payload"]


def set_cached_response(
    question: str,
    mode: str,
    model_version: str,
    payload: Dict[str, Any],
) -> None:
    """Stores response in cache with current timestamp."""
    # Prune old cache entries if store grows large (> 500 entries)
    now = time.time()
    if len(_CACHE_STORE) > 500:
        keys_to_prune = [
            k for k, v in _CACHE_STORE.items() if now - v["timestamp"] > CACHE_TTL_SECONDS
        ]
        for k in keys_to_prune:
            _CACHE_STORE.pop(k, None)

    key = generate_cache_key(question, mode, model_version)
    _CACHE_STORE[key] = {
        "timestamp": now,
        "payload": payload,
    }


def clear_cache() -> None:
    """Clears the cache (used in testing and model updates)."""
    _CACHE_STORE.clear()
