"""Location retrieval helper with database and configuration fallback."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import asyncpg

from core.config import get_locations

logger = logging.getLogger("aagam.api.locations")

_LOCATIONS_CACHE: Optional[List[Dict[str, Any]]] = None


async def get_locations_with_coords(conn: Optional[asyncpg.Connection] = None) -> List[Dict[str, Any]]:
    """Retrieves all 40 authoritative locations with coordinates, region, and ID.

    Queries database `locations` table first; falls back to `config/locations.yaml`.
    """
    global _LOCATIONS_CACHE
    if _LOCATIONS_CACHE is not None:
        return _LOCATIONS_CACHE

    if conn is not None:
        try:
            rows = await conn.fetch(
                """
                SELECT id, slug, name, state, region, terrain,
                       ST_Y(geog::geometry) AS lat,
                       ST_X(geog::geometry) AS lon
                FROM locations
                ORDER BY id
                """
            )
            if rows and len(rows) == 40:
                _LOCATIONS_CACHE = [
                    {
                        "id": r["id"],
                        "slug": r["slug"],
                        "name": r["name"],
                        "state": r["state"],
                        "region": r["region"],
                        "terrain": r["terrain"],
                        "lat": round(float(r["lat"]), 5),
                        "lon": round(float(r["lon"]), 5),
                    }
                    for r in rows
                ]
                return _LOCATIONS_CACHE
        except Exception as e:
            logger.warning(f"Failed to query locations table: {e}; falling back to locations.yaml")

    # Fallback to YAML configuration
    yaml_locs = get_locations()
    fallback_list: List[Dict[str, Any]] = []
    for idx, loc in enumerate(yaml_locs):
        fallback_list.append(
            {
                "id": idx + 1,
                "slug": loc["slug"],
                "name": loc["name"],
                "state": loc.get("state", ""),
                "region": loc["region"],
                "terrain": loc.get("terrain", ""),
                "lat": 20.5937,
                "lon": 78.9629,
            }
        )
    return fallback_list
