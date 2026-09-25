"""Skill scoring verification endpoint (PRD §12, role: any).

Supports dynamic operational live verification (1..90 days, capped at 90)
and the formal held-out 90-day test benchmark without mixing datasets.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, Query, Response

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn
from core.config import settings
from core.schemas import SkillQueryResponse

logger = logging.getLogger("aagam.api.skill")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Skill"])

BASELINE_COMPARISONS_PARQUET = Path("data/baseline_comparisons.parquet")

CANDIDATE_MAP = {
    "GFS": "gfs",
    "ECMWF IFS": "ecmwf_ifs",
    "ICON": "icon",
    "AIFS": "aifs",
    "Equal-Weight Mean": "equal_mean",
    "Best-Single Model": "best_single",
    "Inverse-MAE Blend": "blend",
}


def _get_maturity_label(verified_days: int) -> str:
    if verified_days == 0:
        return "NO VERIFICATION DATA"
    elif 1 <= verified_days <= 3:
        return "PRELIMINARY LIVE VERIFICATION"
    elif 4 <= verified_days <= 6:
        return "EARLY LIVE VERIFICATION"
    elif 7 <= verified_days <= 29:
        return "LIVE VERIFICATION"
    elif 30 <= verified_days <= 89:
        return "LIVE VERIFICATION"
    else:
        return "LIVE VERIFICATION · 90-DAY MAX"


def _get_truth_source_label(variable: Optional[str] = None) -> str:
    if variable == "rain_mm":
        return "ERA5 Climatology Fallback (IMD Offline)"
    elif variable in ("tmax_c", "wind_max_kmh"):
        return "ERA5 Historical Reanalysis"
    return "IMD 0.25° Gridded Rainfall & ERA5 Climatology Fallback"


@router.get("/skill", response_model=SkillQueryResponse)
async def get_skill_scores(
    scope: str = Query("live", description="Evaluation scope: 'live' or 'held_out'"),
    group_by: str = Query("model", description="Grouping dimension: model, lead_days, region, season"),
    variable: Optional[str] = Query(None, description="Weather variable: rain_mm, tmax_c, wind_max_kmh"),
    window_days: Optional[int] = Query(90, description="Trailing verification evaluation window in days (max 90)"),
    region: Optional[str] = Query(None, description="Regional domain filter ('ALL' or specific region)"),
    season: Optional[str] = Query(None, description="Season filter ('ALL' or specific season)"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> SkillQueryResponse:
    """Returns skill scores (MAE, RMSE, Bias, POD, FAR, CSI) across models, lead times, and scopes."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=120"

    from api.app.services.skill_service import fetch_skill_scores

    return await fetch_skill_scores(
        conn=conn,
        scope=scope,
        group_by=group_by,
        variable=variable,
        window_days=window_days,
        region=region,
        season=season,
    )
