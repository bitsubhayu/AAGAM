"""Weights and weight-overrides endpoints (PRD §12)."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.locations import get_locations_with_coords
from api.app.db.model_versions import (
    get_active_model_version_cached,
    get_weights_matrix_cached,
)
from api.app.db.pool import get_db_conn, set_rls_claims
from core.config import settings
from core.schemas import (
    LocationDominantWeight,
    WeightMatrixItem,
    WeightOverrideCreate,
    WeightOverrideResponse,
    WeightsMapResponse,
    WeightsResponse,
)

logger = logging.getLogger("aagam.api.weights")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Weights"])

VALID_REGIONS = {"NW", "CENTRAL", "EAST_NE", "SOUTH", "HIMALAYAN"}
VALID_SEASONS = {"winter", "premonsoon", "pre_monsoon", "monsoon", "postmonsoon", "post_monsoon", "all"}
VALID_VARIABLES = {"rain_mm", "tmax_c", "wind_max_kmh"}
EXPECTED_MODELS = {"gfs", "ecmwf_ifs", "icon", "aifs"}


@router.get("/weights", response_model=WeightsResponse)
async def get_weights(
    variable: Optional[str] = Query(None, description="Weather variable filter"),
    region: Optional[str] = Query(None, description="Regional domain filter"),
    season: Optional[str] = Query(None, description="Season filter"),
    lead_days: Optional[int] = Query(None, ge=0, le=7, description="Lead day filter (0-7)"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> WeightsResponse:
    """Returns the adaptive weight matrix with n_samples and fallback level for the active model version."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=120"

    # Get active version from cache (eliminates un-cached SQL round trip)
    active_version = await get_active_model_version_cached(conn)
    active_ver_id = active_version.get("id", 2)

    # Fetch weights matrix with 60s TTL cache for active version
    rows = await get_weights_matrix_cached(
        conn,
        active_ver_id,
        variable=variable,
        region=region,
        season=season,
        lead_days=lead_days,
    )
    items = [WeightMatrixItem(**r) for r in rows]

    return WeightsResponse(
        version_id=active_ver_id,
        method="ridge",
        weights=items,
    )


@router.get("/weights/map", response_model=WeightsMapResponse)
async def get_weights_map(
    variable: str = Query("rain_mm", description="Weather variable"),
    lead_days: int = Query(0, ge=0, le=7, description="Lead day (0-7)"),
    season: str = Query("monsoon", description="Season identifier"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> WeightsMapResponse:
    """Returns the dominant model and all model weights for each of the 40 locations."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=120"

    # Get active version from cache (eliminates un-cached SQL round trip)
    active_version = await get_active_model_version_cached(conn)
    active_ver_id = active_version.get("id", 2)

    # Fetch weights for this variable, lead, and season
    rows = await conn.fetch(
        """
        SELECT region, model, weight
        FROM weights
        WHERE version_id = $1 AND variable = $2 AND lead_days = $3 AND season = $4
        ORDER BY region, weight DESC
        """,
        active_ver_id,
        variable,
        lead_days,
        season,
    )

    region_weights: Dict[str, Dict[str, float]] = defaultdict(dict)
    for r in rows:
        region_weights[r["region"]][r["model"]] = round(float(r["weight"]), 4)

    locations = await get_locations_with_coords(conn)
    loc_items: List[LocationDominantWeight] = []

    for loc in locations:
        loc_region = loc.get("region", "CENTRAL")
        weights_dict = region_weights.get(loc_region, {"gfs": 0.25, "ecmwf_ifs": 0.25, "icon": 0.25, "aifs": 0.25})

        dominant_m = "aifs"
        max_w = -1.0
        for m, w in weights_dict.items():
            if w > max_w:
                max_w = w
                dominant_m = m

        loc_items.append(
            LocationDominantWeight(
                location_id=loc["id"],
                slug=loc["slug"],
                name=loc["name"],
                region=loc_region,
                lat=loc["lat"],
                lon=loc["lon"],
                dominant_model=dominant_m,
                weight=max_w if max_w >= 0 else 0.25,
                all_weights=weights_dict,
            )
        )

    return WeightsMapResponse(
        variable=variable,
        lead_days=lead_days,
        season=season,
        locations=loc_items,
    )


@router.post("/weights/override", response_model=WeightOverrideResponse, status_code=status.HTTP_201_CREATED)
async def create_weight_override(
    override: WeightOverrideCreate,
    current_user: CurrentUser = Depends(require_role("forecaster+")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> WeightOverrideResponse:
    """Creates an audited forecaster weight override. (Role: forecaster+)."""
    # 1. Validate inputs
    if override.variable not in VALID_VARIABLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_VARIABLE",
                "message": f"Variable must be one of {list(VALID_VARIABLES)}",
                "retry_after": None,
            },
        )
    if override.region not in VALID_REGIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_REGION",
                "message": f"Region must be one of {list(VALID_REGIONS)}",
                "retry_after": None,
            },
        )
    if len(override.reason.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_REASON", "message": "Reason must be at least 10 characters.", "retry_after": None},
        )

    # 2. Validate weights dictionary
    weight_vals = list(override.weights.values())
    if any(w < 0 or w > 1 for w in weight_vals):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_WEIGHTS", "message": "Each weight must be between 0 and 1.", "retry_after": None},
        )
    total_weight = sum(weight_vals)
    if abs(total_weight - 1.0) > 0.01:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_WEIGHTS",
                "message": f"Weights must sum to 1.0 (received sum: {total_weight:.3f}).",
                "retry_after": None,
            },
        )

    # 3. Insert with RLS claims set
    await set_rls_claims(conn, current_user.user_id, role="authenticated")
    row = await conn.fetchrow(
        """
        INSERT INTO weight_overrides (
            created_by, variable, region, season, lead_days, weights, reason, expires_at, active
        ) VALUES (
            $1::uuid, $2, $3, $4, $5, $6::jsonb, $7, $8, true
        )
        RETURNING id, created_by, created_at, variable, region, season, lead_days, weights, reason, expires_at, active
        """,
        current_user.user_id,
        override.variable,
        override.region,
        override.season,
        override.lead_days,
        json.dumps(override.weights),
        override.reason,
        override.expires_at,
    )

    weights_res = row["weights"]
    if isinstance(weights_res, str):
        weights_res = json.loads(weights_res)

    return WeightOverrideResponse(
        id=row["id"],
        created_by=str(row["created_by"]),
        created_at=row["created_at"].isoformat(),
        variable=row["variable"],
        region=row["region"],
        season=row["season"],
        lead_days=row["lead_days"],
        weights=weights_res,
        reason=row["reason"],
        expires_at=row["expires_at"].isoformat() if row["expires_at"] else None,
        active=row["active"],
    )


@router.get("/weights/overrides", response_model=List[WeightOverrideResponse])
async def list_weight_overrides(
    active_only: bool = Query(True, description="Filter for active overrides only"),
    variable: Optional[str] = Query(None, description="Variable filter"),
    region: Optional[str] = Query(None, description="Region filter"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> List[WeightOverrideResponse]:
    """Lists active and historical weight overrides (PRD §12, role: any)."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=30"

    query = "SELECT id, created_by, created_at, variable, region, season, lead_days, weights, reason, expires_at, active FROM weight_overrides WHERE true"
    params: List[Any] = []
    idx = 1

    if active_only:
        query += f" AND active = ${idx}"
        params.append(True)
        idx += 1
    if variable:
        query += f" AND variable = ${idx}"
        params.append(variable)
        idx += 1
    if region:
        query += f" AND region = ${idx}"
        params.append(region)
        idx += 1

    query += " ORDER BY created_at DESC"
    rows = await conn.fetch(query, *params)

    results: List[WeightOverrideResponse] = []
    for r in rows:
        w_dict = r["weights"]
        if isinstance(w_dict, str):
            w_dict = json.loads(w_dict)
        results.append(
            WeightOverrideResponse(
                id=r["id"],
                created_by=str(r["created_by"]),
                created_at=r["created_at"].isoformat(),
                variable=r["variable"],
                region=r["region"],
                season=r["season"],
                lead_days=r["lead_days"],
                weights=w_dict,
                reason=r["reason"],
                expires_at=r["expires_at"].isoformat() if r["expires_at"] else None,
                active=r["active"],
            )
        )

    return results
