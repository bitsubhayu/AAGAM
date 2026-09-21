"""Map endpoint (PRD §12, role: any)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.locations import get_locations_with_coords
from api.app.db.model_versions import (
    get_active_model_version_cached,
    get_dominant_weights_cached,
)
from api.app.db.pool import get_db_conn
from core.config import settings
from core.schemas import MapPointItem, MapResponse

logger = logging.getLogger("aagam.api.map")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Map"])

VALID_VARIABLES = {
    "rain_mm": "mm/24h (08:30 IST)",
    "tmax_c": "°C (Maximum Temperature)",
    "wind_max_kmh": "km/h (Peak Gust / Maximum Wind)",
}


@router.get("/map", response_model=MapResponse)
async def get_map_data(
    variable: str = Query(..., description="Weather variable: rain_mm, tmax_c, wind_max_kmh"),
    lead_days: int = Query(1, ge=1, le=8, description="Forecast lead time in days (1-8)"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("any")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> MapResponse:
    """Returns the latest blended forecast value, spread, and dominant model across all 40 grid points for a given variable and lead day."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=60"

    if variable not in VALID_VARIABLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_VARIABLE",
                "message": f"Invalid variable '{variable}'. Must be one of: {list(VALID_VARIABLES.keys())}",
                "retry_after": None,
            },
        )

    unit_str = VALID_VARIABLES[variable]
    locations = await get_locations_with_coords(conn)

    # Determine active model version from cache
    active_version = await get_active_model_version_cached(conn)
    active_ver_id = active_version.get("id", 2)

    # 1. Fetch dominant model per region from 60s in-memory TTL cache (0 SQL round trips on warm requests)
    dominant_by_region = await get_dominant_weights_cached(conn, active_ver_id, variable, lead_days)

    # 2. Unified single SQL query combining blended_forecasts with model_forecasts fallback (1 round trip)
    query_map = """
        WITH blend_pts AS (
            SELECT location_id, valid_date, issue_time, blended, spread, degraded
            FROM blended_forecasts
            WHERE variable = $1 AND lead_days = $2
        ),
        model_pts AS (
            SELECT
                location_id,
                MAX(valid_date) AS valid_date,
                MAX(issue_time) AS issue_time,
                round(AVG(value)::numeric, 2) AS blended,
                round((MAX(value) - MIN(value))::numeric, 2) AS spread,
                false AS degraded
            FROM model_forecasts
            WHERE variable = $1 AND lead_days = $2
            GROUP BY location_id
        )
        SELECT
            COALESCE(b.location_id, m.location_id) AS location_id,
            COALESCE(b.valid_date, m.valid_date) AS valid_date,
            COALESCE(b.issue_time, m.issue_time) AS issue_time,
            COALESCE(b.blended, m.blended) AS blended,
            COALESCE(b.spread, m.spread) AS spread,
            COALESCE(b.degraded, m.degraded) AS degraded
        FROM blend_pts b
        FULL OUTER JOIN model_pts m ON b.location_id = m.location_id;
    """
    rows = await conn.fetch(query_map, variable, lead_days)

    blend_map: Dict[int, Dict[str, Any]] = {}
    valid_date_str = ""
    latest_issue: Optional[datetime] = None

    for r in rows:
        loc_id = r["location_id"]
        blend_map[loc_id] = {
            "blended": round(float(r["blended"]), 2) if r["blended"] is not None else None,
            "spread": round(float(r["spread"]), 2) if r["spread"] is not None else None,
            "degraded": bool(r["degraded"]),
        }
        if r["valid_date"] and not valid_date_str:
            valid_date_str = r["valid_date"].isoformat()
        if r["issue_time"] and (latest_issue is None or r["issue_time"] > latest_issue):
            latest_issue = r["issue_time"]

    points: List[MapPointItem] = []
    for loc in locations:
        loc_id = loc["id"]
        region = loc.get("region", "CENTRAL")
        b_info = blend_map.get(loc_id, {})
        dominant = dominant_by_region.get(region, "aifs")

        points.append(
            MapPointItem(
                location_id=loc_id,
                slug=loc["slug"],
                name=loc["name"],
                region=region,
                lat=loc["lat"],
                lon=loc["lon"],
                blended=b_info.get("blended"),
                spread=b_info.get("spread"),
                degraded=b_info.get("degraded", False),
                dominant_model=dominant,
            )
        )

    issue_time_str = (
        latest_issue.strftime("%Y-%m-%dT%H:%M:%SZ")
        if latest_issue
        else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    if not valid_date_str:
        valid_date_str = datetime.now(timezone.utc).date().isoformat()

    return MapResponse(
        variable=variable,
        lead_days=lead_days,
        valid_date=valid_date_str,
        issue_time=issue_time_str,
        unit=unit_str,
        points=points,
    )
