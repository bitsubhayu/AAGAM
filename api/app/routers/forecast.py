"""Forecast endpoint (PRD §12, role: any)."""

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
from core.schemas import ForecastLocationInfo, ForecastResponse, ForecastSeriesItem

logger = logging.getLogger("aagam.api.forecast")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Forecast"])

VALID_VARIABLES = {
    "rain_mm": "mm/24h (08:30 IST)",
    "tmax_c": "°C (Maximum Temperature)",
    "wind_max_kmh": "km/h (Peak Gust / Maximum Wind)",
}


@router.get("/forecast", response_model=ForecastResponse)
async def get_forecast(
    location: str = Query(..., description="Location slug (e.g. bhubaneswar) or numeric location ID"),
    variable: str = Query(..., description="Weather variable: rain_mm, tmax_c, wind_max_kmh"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("any")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> ForecastResponse:
    """Returns per-model, blended, and spread forecasts by valid date for the specified location and variable."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=60"

    # Validate variable
    if variable not in VALID_VARIABLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_VARIABLE",
                "message": f"Invalid variable '{variable}'. Must be one of: {list(VALID_VARIABLES.keys())}",
                "retry_after": None,
            },
        )

    # Resolve location
    locations = await get_locations_with_coords(conn)
    loc_match: Optional[Dict[str, Any]] = None

    if location.isdigit():
        loc_id = int(location)
        for loc in locations:
            if loc.get("id") == loc_id:
                loc_match = loc
                break
    else:
        norm_slug = location.strip().lower()
        for loc in locations:
            if loc.get("slug", "").lower() == norm_slug:
                loc_match = loc
                break

    if not loc_match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "LOCATION_NOT_FOUND",
                "message": f"Location '{location}' not found in the 40 authoritative points.",
                "retry_after": None,
            },
        )

    target_loc_id = loc_match["id"]
    unit_str = VALID_VARIABLES[variable]

    # Fetch active model version identifier from cache
    active_version = await get_active_model_version_cached(conn)
    model_version_str = active_version.get("version_str", "v2026-09-21")
    active_ver_id = active_version.get("id", 2)

    # 1. Query blended_forecasts
    blend_rows = await conn.fetch(
        """
        SELECT valid_date, lead_days, blended, ridge, lgbm, equal_mean, spread,
               models_over_threshold, degraded, issue_time
        FROM blended_forecasts
        WHERE location_id = $1 AND variable = $2
        ORDER BY valid_date ASC
        """,
        target_loc_id,
        variable,
    )

    # 2. Query model_forecasts
    model_rows = await conn.fetch(
        """
        SELECT valid_date, lead_days, model, value, issue_time
        FROM model_forecasts
        WHERE location_id = $1 AND variable = $2
        ORDER BY valid_date ASC, model ASC
        """,
        target_loc_id,
        variable,
    )

    # Group model predictions by valid_date
    models_by_date: Dict[str, Dict[str, Optional[float]]] = defaultdict(dict)
    model_lead_map: Dict[str, int] = {}
    latest_issue: Optional[datetime] = None

    for m in model_rows:
        v_date = m["valid_date"].isoformat()
        m_name = m["model"]
        models_by_date[v_date][m_name] = round(float(m["value"]), 2) if m["value"] is not None else None
        model_lead_map[v_date] = m["lead_days"]
        if m["issue_time"]:
            if latest_issue is None or m["issue_time"] > latest_issue:
                latest_issue = m["issue_time"]

    series_items: List[ForecastSeriesItem] = []
    is_degraded = False

    if blend_rows:
        for b in blend_rows:
            v_date = b["valid_date"].isoformat()
            lead = b["lead_days"]
            b_val = round(float(b["blended"]), 2) if b["blended"] is not None else None
            spread_val = round(float(b["spread"]), 2) if b["spread"] is not None else None
            m_dict = models_by_date.get(v_date, {})
            if b["degraded"]:
                is_degraded = True
            if b["issue_time"]:
                if latest_issue is None or b["issue_time"] > latest_issue:
                    latest_issue = b["issue_time"]

            series_items.append(
                ForecastSeriesItem(
                    valid_date=v_date,
                    lead_days=lead,
                    blended=b_val,
                    models=m_dict,
                    spread=spread_val,
                    models_over_threshold=b["models_over_threshold"] or 0,
                )
            )
    elif model_rows:
        # If blended_forecasts is empty, compute blend dynamically using active weights
        region = loc_match.get("region", "CENTRAL")
        weights_rows = await conn.fetch(
            """
            SELECT lead_days, model, weight
            FROM weights
            WHERE version_id = $1 AND variable = $2 AND region = $3
            """,
            active_ver_id,
            variable,
            region,
        )
        weight_map: Dict[int, Dict[str, float]] = defaultdict(dict)
        for w in weights_rows:
            weight_map[w["lead_days"]][w["model"]] = float(w["weight"])

        for v_date in sorted(models_by_date.keys()):
            m_dict = models_by_date[v_date]
            lead = model_lead_map.get(v_date, 1)

            # Compute blend from weights or equal mean
            vals = [v for v in m_dict.values() if v is not None]
            w_dict = weight_map.get(lead, {})

            if vals and w_dict and all(m in w_dict for m in m_dict if m_dict[m] is not None):
                blended_calc = sum(w_dict[m] * m_dict[m] for m in m_dict if m_dict[m] is not None)
            elif vals:
                blended_calc = float(np.mean(vals))
            else:
                blended_calc = None

            spread_calc = float(np.ptp(vals)) if len(vals) > 1 else 0.0

            series_items.append(
                ForecastSeriesItem(
                    valid_date=v_date,
                    lead_days=lead,
                    blended=round(blended_calc, 2) if blended_calc is not None else None,
                    models=m_dict,
                    spread=round(spread_calc, 2),
                    models_over_threshold=0,
                )
            )

    issue_time_str = latest_issue.strftime("%Y-%m-%dT%H:%M:%SZ") if latest_issue else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return ForecastResponse(
        location=ForecastLocationInfo(
            slug=loc_match["slug"],
            name=loc_match["name"],
            region=loc_match["region"],
        ),
        variable=variable,
        unit=unit_str,
        issue_time=issue_time_str,
        model_version=model_version_str,
        degraded=is_degraded,
        series=series_items,
    )
