"""Climatology percentiles and local extremeness API endpoints (PRD §11.2, §12, Phase 13)."""

from __future__ import annotations

import datetime as dt
import logging
from typing import List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn
from core.config import settings
from core.schemas import ClimatologyPercentileItem, ClimatologyResponse

logger = logging.getLogger("aagam.api.climatology")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Climatology"])

VALID_VARIABLES = {"rain_mm", "tmax_c", "wind_max_kmh"}
VALID_METRICS = {"1day", "3day_sum"}


@router.get("/climatology", response_model=ClimatologyResponse)
async def get_station_climatology(
    location_id: int = Query(..., description="Station location ID (1-40)"),
    variable: Optional[str] = Query(None, description="Variable: rain_mm, tmax_c, wind_max_kmh"),
    metric: Optional[str] = Query(None, description="Metric: 1day, 3day_sum"),
    doy_window: Optional[int] = Query(None, ge=1, le=366, description="Center DOY window (1-366)"),
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD), automatically mapped to DOY window"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> ClimatologyResponse:
    """Returns station-level climatological percentiles and distributions (role: public).

    Supports querying by specific day-of-year or calendar date.
    When n_years < 15, percentiles are null and insufficient_history is true (PRD §11.2).
    """
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=3600"

    # 1. Verify location exists
    loc_row = await conn.fetchrow("SELECT id, name FROM locations WHERE id = $1;", location_id)
    if not loc_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "LOCATION_NOT_FOUND",
                "message": f"Location with ID {location_id} does not exist.",
                "retry_after": None,
            },
        )

    # 2. Parse date into doy_window if provided
    resolved_doy = doy_window
    if date and resolved_doy is None:
        try:
            parsed_date = dt.date.fromisoformat(date)
            resolved_doy = parsed_date.timetuple().tm_yday
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INVALID_DATE_FORMAT",
                    "message": f"Invalid date '{date}'. Must be ISO-8601 YYYY-MM-DD.",
                    "retry_after": None,
                },
            )

    # 3. Validate variable and metric if provided
    if variable and variable.lower() not in VALID_VARIABLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_VARIABLE",
                "message": f"Invalid variable '{variable}'. Must be one of: {sorted(list(VALID_VARIABLES))}",
                "retry_after": None,
            },
        )

    if metric and metric.lower() not in VALID_METRICS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_METRIC",
                "message": f"Invalid metric '{metric}'. Must be one of: {sorted(list(VALID_METRICS))}",
                "retry_after": None,
            },
        )

    # 4. Build query
    query = """
        SELECT location_id, variable, metric, doy_window, mean, p90, p95, p99, n_years, computed_at
        FROM climatology_percentiles
        WHERE location_id = $1
    """
    params = [location_id]
    param_idx = 2

    if variable:
        query += f" AND variable = ${param_idx}"
        params.append(variable.lower())
        param_idx += 1

    if metric:
        query += f" AND metric = ${param_idx}"
        params.append(metric.lower())
        param_idx += 1

    if resolved_doy:
        query += f" AND doy_window = ${param_idx}"
        params.append(resolved_doy)
        param_idx += 1

    query += " ORDER BY variable, metric, doy_window;"

    rows = await conn.fetch(query, *params)

    percentile_items: List[ClimatologyPercentileItem] = []
    has_insufficient = False

    for r in rows:
        n_years = int(r["n_years"])
        is_insufficient = n_years < 15
        if is_insufficient:
            has_insufficient = True

        percentile_items.append(
            ClimatologyPercentileItem(
                location_id=r["location_id"],
                variable=r["variable"],
                metric=r["metric"],
                doy_window=r["doy_window"],
                mean=round(float(r["mean"]), 2) if r["mean"] is not None else None,
                p90=round(float(r["p90"]), 2) if r["p90"] is not None else None,
                p95=round(float(r["p95"]), 2) if r["p95"] is not None else None,
                p99=round(float(r["p99"]), 2) if r["p99"] is not None else None,
                n_years=n_years,
                computed_at=r["computed_at"].isoformat() if r["computed_at"] else None,
                insufficient_history=is_insufficient,
            )
        )

    # If no rows found at all, also mark as insufficient history
    if not percentile_items:
        has_insufficient = True

    return ClimatologyResponse(
        location_id=loc_row["id"],
        location_name=loc_row["name"],
        variable=variable,
        metric=metric,
        doy_window=resolved_doy,
        date=date,
        insufficient_history=has_insufficient,
        percentiles=percentile_items,
    )
