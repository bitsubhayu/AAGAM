"""Active model version cache helper."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

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


_DOMINANT_WEIGHTS_CACHE: Dict[str, Tuple[float, Dict[str, str]]] = {}
_REGION_WEIGHTS_CACHE: Dict[str, Tuple[float, Dict[int, Dict[str, float]]]] = {}


async def get_dominant_weights_cached(
    conn: asyncpg.Connection,
    version_id: int,
    variable: str,
    lead_days: int,
) -> Dict[str, str]:
    """Retrieves dominant model per region for (version, variable, lead_days) with 60s TTL cache."""
    global _DOMINANT_WEIGHTS_CACHE
    now = time.time()
    cache_key = f"{version_id}:{variable}:{lead_days}"
    if cache_key in _DOMINANT_WEIGHTS_CACHE:
        cache_time, cached_val = _DOMINANT_WEIGHTS_CACHE[cache_key]
        if (now - cache_time) < 60.0:
            return cached_val

    dominant_by_region: Dict[str, str] = {}
    try:
        weight_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (region) region, model, weight
            FROM weights
            WHERE version_id = $1 AND variable = $2 AND lead_days = $3
            ORDER BY region, weight DESC
            """,
            version_id,
            variable,
            lead_days,
        )
        for w in weight_rows:
            dominant_by_region[w["region"]] = w["model"]

        # Check active unexpired overrides for this variable and lead_days
        override_rows = await conn.fetch(
            """
            SELECT region, weights
            FROM weight_overrides
            WHERE active = true
              AND variable = $1
              AND lead_days = $2
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY created_at ASC
            """,
            variable,
            lead_days,
        )
        for ov in override_rows:
            ov_weights = ov["weights"]
            if isinstance(ov_weights, str):
                ov_weights = json.loads(ov_weights)
            if ov_weights:
                dom_m = max(ov_weights, key=ov_weights.get)
                dominant_by_region[ov["region"]] = dom_m

        _DOMINANT_WEIGHTS_CACHE[cache_key] = (now, dominant_by_region)
    except Exception as e:
        logger.warning(f"Error querying dominant weights: {e}")
    return dominant_by_region


async def get_region_weights_cached(
    conn: asyncpg.Connection,
    version_id: int,
    variable: str,
    region: str,
) -> Dict[int, Dict[str, float]]:
    """Retrieves regional weights by lead_days and model with 60s TTL cache."""
    global _REGION_WEIGHTS_CACHE
    now = time.time()
    cache_key = f"{version_id}:{variable}:{region}"
    if cache_key in _REGION_WEIGHTS_CACHE:
        cache_time, cached_val = _REGION_WEIGHTS_CACHE[cache_key]
        if (now - cache_time) < 60.0:
            return cached_val

    weight_map: Dict[int, Dict[str, float]] = {}
    try:
        weights_rows = await conn.fetch(
            """
            SELECT lead_days, model, weight
            FROM weights
            WHERE version_id = $1 AND variable = $2 AND region = $3
            """,
            version_id,
            variable,
            region,
        )
        for w in weights_rows:
            lead = w["lead_days"]
            if lead not in weight_map:
                weight_map[lead] = {}
            weight_map[lead][w["model"]] = float(w["weight"])

        # Overlay active forecaster weight overrides for operational blending
        override_rows = await conn.fetch(
            """
            SELECT lead_days, weights
            FROM weight_overrides
            WHERE active = true
              AND variable = $1
              AND region = $2
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY created_at ASC
            """,
            variable,
            region,
        )
        for ov in override_rows:
            lead = ov["lead_days"]
            ov_weights = ov["weights"]
            if isinstance(ov_weights, str):
                ov_weights = json.loads(ov_weights)
            if ov_weights:
                if lead not in weight_map:
                    weight_map[lead] = {}
                for m, w in ov_weights.items():
                    weight_map[lead][m] = float(w)

        _REGION_WEIGHTS_CACHE[cache_key] = (now, weight_map)
    except Exception as e:
        logger.warning(f"Error querying regional weights: {e}")
    return weight_map


_WEIGHTS_ITEMS_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}


async def get_weights_matrix_cached(
    conn: asyncpg.Connection,
    version_id: int,
    variable: Optional[str] = None,
    region: Optional[str] = None,
    season: Optional[str] = None,
    lead_days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Retrieves weights rows with a 60s in-memory TTL cache for immutable active version weights."""
    global _WEIGHTS_ITEMS_CACHE
    now = time.time()
    cache_key = f"{version_id}:{variable}:{region}:{season}:{lead_days}"
    if cache_key in _WEIGHTS_ITEMS_CACHE:
        cache_time, cached_val = _WEIGHTS_ITEMS_CACHE[cache_key]
        if (now - cache_time) < 60.0:
            return cached_val

    query = """
        SELECT variable, region, season, lead_days, model, weight, method, n_samples, fallback_level
        FROM weights
        WHERE version_id = $1
    """
    params: List[Any] = [version_id]
    idx = 2
    if variable:
        query += f" AND variable = ${idx}"
        params.append(variable)
        idx += 1
    if region:
        query += f" AND region = ${idx}"
        params.append(region)
        idx += 1
    if season:
        query += f" AND season = ${idx}"
        params.append(season)
        idx += 1
    if lead_days:
        query += f" AND lead_days = ${idx}"
        params.append(lead_days)
        idx += 1
    query += " ORDER BY variable, region, season, lead_days, weight DESC"

    rows = await conn.fetch(query, *params)
    serialized = [
        {
            "variable": r["variable"],
            "region": r["region"],
            "season": r["season"],
            "lead_days": r["lead_days"],
            "model": r["model"],
            "weight": round(float(r["weight"]), 4),
            "method": r["method"],
            "n_samples": r["n_samples"],
            "fallback_level": r["fallback_level"],
        }
        for r in rows
    ]
    _WEIGHTS_ITEMS_CACHE[cache_key] = (now, serialized)
    return serialized


def invalidate_weights_cache() -> None:
    """Invalidates the in-memory weights matrix, dominant weights, and regional weights caches."""
    global _DOMINANT_WEIGHTS_CACHE, _REGION_WEIGHTS_CACHE, _WEIGHTS_ITEMS_CACHE
    _DOMINANT_WEIGHTS_CACHE.clear()
    _REGION_WEIGHTS_CACHE.clear()
    _WEIGHTS_ITEMS_CACHE.clear()


def invalidate_model_version_cache() -> None:
    """Invalidates the active model version and weights cache (called after activation or rollback)."""
    global _ACTIVE_VERSION_CACHE, _ACTIVE_VERSION_TIME, _DOMINANT_WEIGHTS_CACHE, _REGION_WEIGHTS_CACHE, _WEIGHTS_ITEMS_CACHE
    _ACTIVE_VERSION_CACHE = None
    _ACTIVE_VERSION_TIME = 0.0
    _DOMINANT_WEIGHTS_CACHE.clear()
    _REGION_WEIGHTS_CACHE.clear()
    _WEIGHTS_ITEMS_CACHE.clear()
