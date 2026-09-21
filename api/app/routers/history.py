"""Historical forecasts query endpoint (PRD §12, role: any)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.locations import get_locations_with_coords
from api.app.db.pool import get_db_conn
from core.config import settings
from core.schemas import HistoryRecord, HistoryResponse

logger = logging.getLogger("aagam.api.history")
router = APIRouter(prefix=settings.API_V1_STR, tags=["History"])

VALID_VARIABLES = {"rain_mm", "tmax_c", "wind_max_kmh"}


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    location: str = Query(..., description="Location slug or numeric location ID"),
    variable: str = Query(..., description="Weather variable: rain_mm, tmax_c, wind_max_kmh"),
    start: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    kind: str = Query("both", description="Forecast kind: blended, models, or both"),
    limit: int = Query(100, ge=1, le=1000, description="Page size (maximum 1,000)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("any")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> HistoryResponse:
    """Returns paginated historical forecast data (PRD §12: page size <= 1,000; total <= 5,000)."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=60"

    # Enforce PRD pagination constraint: total <= 5,000
    if offset + limit > 5000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "PAGINATION_LIMIT_EXCEEDED",
                "message": f"Total offset ({offset}) + limit ({limit}) = {offset + limit} exceeds PRD maximum boundary of 5,000 records.",
                "retry_after": None,
            },
        )

    if variable not in VALID_VARIABLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_VARIABLE",
                "message": f"Invalid variable '{variable}'. Must be one of: {list(VALID_VARIABLES)}",
                "retry_after": None,
            },
        )

    locations = await get_locations_with_coords(conn)
    loc_match: Optional[Dict[str, Any]] = None
    if location.isdigit():
        target_id = int(location)
        for loc in locations:
            if loc.get("id") == target_id:
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
    records: List[HistoryRecord] = []

    # Query blended forecasts if requested
    if kind.lower() in ("blended", "both"):
        b_query = """
            SELECT location_id, variable, valid_date, lead_days, blended as value, issue_time
            FROM blended_forecasts
            WHERE location_id = $1 AND variable = $2
        """
        b_params: List[Any] = [target_loc_id, variable]
        b_idx = 3
        if start:
            b_query += f" AND valid_date >= ${b_idx}"
            b_params.append(start)
            b_idx += 1
        if end:
            b_query += f" AND valid_date <= ${b_idx}"
            b_params.append(end)
            b_idx += 1
        b_query += " ORDER BY valid_date DESC, lead_days ASC LIMIT 1000"

        b_rows = await conn.fetch(b_query, *b_params)
        for r in b_rows:
            records.append(
                HistoryRecord(
                    location_id=r["location_id"],
                    variable=r["variable"],
                    valid_date=r["valid_date"].isoformat(),
                    lead_days=r["lead_days"],
                    kind="blended",
                    source="blend",
                    value=round(float(r["value"]), 2) if r["value"] is not None else None,
                    issue_time=r["issue_time"].isoformat() if r["issue_time"] else None,
                )
            )

    # Query model forecasts if requested
    if kind.lower() in ("models", "both"):
        m_query = """
            SELECT location_id, variable, valid_date, lead_days, model as source, value, issue_time
            FROM model_forecasts
            WHERE location_id = $1 AND variable = $2
        """
        m_params: List[Any] = [target_loc_id, variable]
        m_idx = 3
        if start:
            m_query += f" AND valid_date >= ${m_idx}"
            m_params.append(start)
            m_idx += 1
        if end:
            m_query += f" AND valid_date <= ${m_idx}"
            m_params.append(end)
            m_idx += 1
        m_query += " ORDER BY valid_date DESC, lead_days ASC, model ASC LIMIT 2000"

        m_rows = await conn.fetch(m_query, *m_params)
        for r in m_rows:
            records.append(
                HistoryRecord(
                    location_id=r["location_id"],
                    variable=r["variable"],
                    valid_date=r["valid_date"].isoformat(),
                    lead_days=r["lead_days"],
                    kind="model",
                    source=r["source"],
                    value=round(float(r["value"]), 2) if r["value"] is not None else None,
                    issue_time=r["issue_time"].isoformat() if r["issue_time"] else None,
                )
            )

    # Sort combined records by valid_date descending, lead_days ascending
    records.sort(key=lambda x: (x.valid_date, x.lead_days), reverse=True)
    total_available = len(records)
    paginated = records[offset : offset + limit]

    return HistoryResponse(
        location=loc_match["slug"],
        variable=variable,
        count=total_available,
        limit=limit,
        offset=offset,
        records=paginated,
    )
