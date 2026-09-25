"""Forecast endpoint (PRD §12, role: any)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.locations import get_locations_with_coords
from api.app.db.model_versions import (
    get_active_model_version_cached,
    get_region_weights_cached,
)
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
    current_user: CurrentUser = Depends(require_role("public")),
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

    # Single unified query isolating exactly ONE latest operational issue cycle
    # Guarantees unique lead_days 0..7 without historical cycle leakage (PRD §12)
    query_forecast = """
        WITH latest_blend AS (
            SELECT MAX(issue_time) AS issue_time
            FROM blended_forecasts
            WHERE location_id = $1 AND variable = $2
        ),
        blend_rows AS (
            SELECT
                b.valid_date,
                b.lead_days,
                b.blended,
                b.spread,
                b.models_over_threshold,
                b.degraded,
                b.issue_time
            FROM blended_forecasts b
            JOIN latest_blend lb ON b.issue_time = lb.issue_time
            WHERE b.location_id = $1 AND b.variable = $2
              AND b.lead_days >= 0 AND b.lead_days <= 7
        ),
        model_rows AS (
            SELECT
                m.valid_date,
                m.lead_days,
                m.model,
                m.value,
                m.issue_time
            FROM model_forecasts m
            WHERE m.location_id = $1 AND m.variable = $2
              AND (
                  EXISTS (SELECT 1 FROM blend_rows br WHERE br.valid_date = m.valid_date)
                  OR (NOT EXISTS (SELECT 1 FROM blend_rows) AND m.issue_time = (
                      SELECT MAX(issue_time) FROM model_forecasts WHERE location_id = $1 AND variable = $2
                  ) AND m.lead_days >= 0 AND m.lead_days <= 7)
              )
        ),
        models_agg AS (
            SELECT
                valid_date,
                jsonb_object_agg(model, round(value::numeric, 2)) AS models_json
            FROM model_rows
            GROUP BY valid_date
        ),
        merged AS (
            SELECT
                COALESCE(b.valid_date, m.valid_date) AS valid_date,
                COALESCE(b.lead_days, m_lead.lead_days) AS lead_days,
                b.blended,
                b.spread,
                b.models_over_threshold,
                b.degraded,
                COALESCE(b.issue_time, m_lead.issue_time) AS issue_time,
                ma.models_json
            FROM blend_rows b
            FULL OUTER JOIN (
                SELECT DISTINCT valid_date FROM model_rows
            ) m ON b.valid_date = m.valid_date
            LEFT JOIN (
                SELECT valid_date, MIN(lead_days) AS lead_days, MAX(issue_time) AS issue_time
                FROM model_rows
                GROUP BY valid_date
            ) m_lead ON COALESCE(b.valid_date, m.valid_date) = m_lead.valid_date
            LEFT JOIN models_agg ma ON COALESCE(b.valid_date, m.valid_date) = ma.valid_date
        )
        SELECT DISTINCT ON (lead_days)
            valid_date,
            lead_days,
            blended,
            spread,
            models_over_threshold,
            degraded,
            issue_time,
            models_json
        FROM merged
        WHERE lead_days >= 0 AND lead_days <= 7
        ORDER BY lead_days ASC, valid_date ASC;
    """
    rows = await conn.fetch(query_forecast, target_loc_id, variable)

    series_items: List[ForecastSeriesItem] = []
    is_degraded = False
    latest_issue: Optional[datetime] = None

    # Load regional weights from TTL cache for dynamic blend fallback if needed (0 SQL round trips on warm requests)
    region = loc_match.get("region", "CENTRAL")
    weight_map = await get_region_weights_cached(conn, active_ver_id, variable, region)

    for r in rows:
        v_date = r["valid_date"].isoformat() if r["valid_date"] else ""
        lead = int(r["lead_days"]) if r["lead_days"] is not None else 0
        raw_models = r["models_json"]
        m_dict: Dict[str, Optional[float]] = {}
        if raw_models:
            if isinstance(raw_models, str):
                m_dict = json.loads(raw_models)
            else:
                m_dict = dict(raw_models)

        if r["issue_time"] and (latest_issue is None or r["issue_time"] > latest_issue):
            latest_issue = r["issue_time"]
        if r["degraded"]:
            is_degraded = True

        b_val = round(float(r["blended"]), 2) if r["blended"] is not None else None
        spread_val = round(float(r["spread"]), 2) if r["spread"] is not None else None

        if b_val is None and m_dict:
            # Dynamic blend calculation from models
            vals = [v for v in m_dict.values() if v is not None]
            w_dict = weight_map.get(lead, {})
            if vals and w_dict and all(m in w_dict for m in m_dict if m_dict[m] is not None):
                blended_calc = sum(w_dict[m] * m_dict[m] for m in m_dict if m_dict[m] is not None)
            elif vals:
                blended_calc = float(np.mean(vals))
            else:
                blended_calc = None
            b_val = round(blended_calc, 2) if blended_calc is not None else None
            spread_val = round(float(np.ptp(vals)), 2) if len(vals) > 1 else 0.0

        series_items.append(
            ForecastSeriesItem(
                valid_date=v_date,
                lead_days=lead,
                blended=b_val,
                models=m_dict,
                spread=spread_val,
                models_over_threshold=r["models_over_threshold"] or 0,
            )
        )

    issue_time_str = (
        latest_issue.strftime("%Y-%m-%dT%H:%M:%SZ")
        if latest_issue
        else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

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
