"""Active model version cache helper."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import asyncpg

logger = logging.getLogger("aagam.api.model_versions")

_ACTIVE_VERSION_CACHE: Optional[Dict[str, Any]] = None
_ACTIVE_VERSION_TIME: float = 0.0


async def get_active_model_version_cached(conn: Optional[asyncpg.Connection] = None) -> Dict[str, Any]:
    """Retrieves the active model version metadata with a 60-second in-memory cache."""
    global _ACTIVE_VERSION_CACHE, _ACTIVE_VERSION_TIME
    now = time.time()

    if _ACTIVE_VERSION_CACHE is not None and (now - _ACTIVE_VERSION_TIME) < 60.0:
        return _ACTIVE_VERSION_CACHE

    if conn is not None:
        try:
            ver_row = await conn.fetchrow(
                "SELECT id, storage_path, metrics, created_at, is_active FROM model_versions WHERE is_active = true LIMIT 1"
            )
            if ver_row:
                path = ver_row["storage_path"]
                parts = [p for p in path.split("/") if p]
                version_str = f"v{parts[-1]}" if parts else f"v{ver_row['id']}"
                _ACTIVE_VERSION_CACHE = {
                    "id": ver_row["id"],
                    "version_str": version_str,
                    "storage_path": path,
                    "metrics": ver_row["metrics"],
                    "created_at": ver_row["created_at"].isoformat() if ver_row["created_at"] else None,
                    "is_active": ver_row["is_active"],
                }
                _ACTIVE_VERSION_TIME = now
                return _ACTIVE_VERSION_CACHE
        except Exception as e:
            logger.warning(f"Error reading model_versions: {e}")

    return {
        "id": 2,
        "version_str": "v2026-09-21",
        "storage_path": "models/20260921/",
        "metrics": {},
        "created_at": None,
        "is_active": True,
    }


def invalidate_model_version_cache() -> None:
    """Invalidates the active model version cache (called after activation or rollback)."""
    global _ACTIVE_VERSION_CACHE, _ACTIVE_VERSION_TIME
    _ACTIVE_VERSION_CACHE = None
    _ACTIVE_VERSION_TIME = 0.0
