"""Skill scoring verification endpoint (PRD §12, role: any)."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, Query, Response

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn
from core.config import settings
from core.schemas import SkillQueryResponse, SkillScoreItem

logger = logging.getLogger("aagam.api.skill")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Skill"])


@router.get("/skill", response_model=SkillQueryResponse)
async def get_skill_scores(
    group_by: str = Query("model", description="Grouping dimension: model, lead_days, region, season"),
    variable: Optional[str] = Query(None, description="Weather variable: rain_mm, tmax_c, wind_max_kmh"),
    window_days: Optional[int] = Query(None, description="Trailing verification evaluation window in days"),
    region: Optional[str] = Query(None, description="Regional domain filter"),
    season: Optional[str] = Query(None, description="Season filter"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> SkillQueryResponse:
    """Returns historical skill scores (MAE, RMSE, Bias, POD, FAR, CSI) across models and lead times."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=300"

    query = """
        SELECT computed_at, window_days, variable, region, season, lead_days,
               model, mae, rmse, bias, n, pod, far, csi, threshold_mm, is_weekly
        FROM skill_scores
        WHERE true
    """
    params: List[Any] = []
    idx = 1

    if variable:
        query += f" AND variable = ${idx}"
        params.append(variable)
        idx += 1
    if window_days:
        query += f" AND window_days = ${idx}"
        params.append(window_days)
        idx += 1
    if region:
        query += f" AND region = ${idx}"
        params.append(region)
        idx += 1
    if season:
        query += f" AND season = ${idx}"
        params.append(season)
        idx += 1

    query += " ORDER BY computed_at DESC, lead_days ASC, model ASC LIMIT 500"

    rows = await conn.fetch(query, *params)
    items = [
        SkillScoreItem(
            computed_at=r["computed_at"].isoformat() if r["computed_at"] else "",
            window_days=r["window_days"],
            variable=r["variable"],
            region=r["region"],
            season=r["season"],
            lead_days=r["lead_days"],
            model=r["model"],
            mae=round(float(r["mae"]), 3) if r["mae"] is not None else None,
            rmse=round(float(r["rmse"]), 3) if r["rmse"] is not None else None,
            bias=round(float(r["bias"]), 3) if r["bias"] is not None else None,
            n=r["n"],
            pod=round(float(r["pod"]), 3) if r["pod"] is not None else None,
            far=round(float(r["far"]), 3) if r["far"] is not None else None,
            csi=round(float(r["csi"]), 3) if r["csi"] is not None else None,
            threshold_mm=float(r["threshold_mm"]),
            is_weekly=r["is_weekly"],
        )
        for r in rows
    ]

    return SkillQueryResponse(
        group_by=group_by,
        variable=variable,
        scores=items,
    )
