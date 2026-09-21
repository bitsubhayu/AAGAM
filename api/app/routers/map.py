"""Map endpoint (PRD §12, role: any)."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.locations import get_locations_with_coords
from api.app.db.model_versions import get_active_model_version_cached
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

    # Fetch dominant model per region
    dominant_by_region: Dict[str, str] = {}
    try:
        weight_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (region) region, model, weight
            FROM weights
            WHERE version_id = $1 AND variable = $2 AND lead_days = $3
            ORDER BY region, weight DESC
            """,
            active_ver_id,
            variable,
            lead_days,
        )
        for w in weight_rows:
            dominant_by_region[w["region"]] = w["model"]
    except Exception as e:
        logger.warning(f"Error querying dominant weights: {e}")

    # Query blended_forecasts for the lead
    blend_rows = await conn.fetch(
        """
        SELECT location_id, valid_date, issue_time, blended, spread, degraded
        FROM blended_forecasts
        WHERE variable = $1 AND lead_days = $2
        """,
        variable,
        lead_days,
    )
    blend_map: Dict[int, Dict[str, Any]] = {}
    valid_date_str = ""
    latest_issue: Optional[datetime] = None

    for b in blend_rows:
        blend_map[b["location_id"]] = {
            "blended": round(float(b["blended"]), 2) if b["blended"] is not None else None,
            "spread": round(float(b["spread"]), 2) if b["spread"] is not None else None,
            "degraded": bool(b["degraded"]),
        }
        if b["valid_date"]:
            valid_date_str = b["valid_date"].isoformat()
        if b["issue_time"] and (latest_issue is None or b["issue_time"] > latest_issue):
            latest_issue = b["issue_time"]

    # Fallback to model_forecasts if blended_forecasts is empty
    if not blend_map:
        model_rows = await conn.fetch(
            """
            SELECT location_id, valid_date, issue_time, model, value
            FROM model_forecasts
            WHERE variable = $1 AND lead_days = $2
            """,
            variable,
            lead_days,
        )
        models_by_loc: Dict[int, Dict[str, float]] = defaultdict(dict)
        for m in model_rows:
            models_by_loc[m["location_id"]][m["model"]] = float(m["value"])
            if m["valid_date"] and not valid_date_str:
                valid_date_str = m["valid_date"].isoformat()
            if m["issue_time"] and (latest_issue is None or m["issue_time"] > latest_issue):
                latest_issue = m["issue_time"]

        for loc_id, m_dict in models_by_loc.items():
            vals = list(m_dict.values())
            b_val = float(np.mean(vals)) if vals else None
            s_val = float(np.ptp(vals)) if len(vals) > 1 else 0.0
            blend_map[loc_id] = {
                "blended": round(b_val, 2) if b_val is not None else None,
                "spread": round(s_val, 2),
                "degraded": False,
            }

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

    issue_time_str = latest_issue.strftime("%Y-%m-%dT%H:%M:%SZ") if latest_issue else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
