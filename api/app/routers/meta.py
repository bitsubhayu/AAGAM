"""Metadata endpoint (PRD §12, role: any)."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, Response

from api.app.db.pool import db_pool
from core.config import get_locations, get_models, get_regions, get_thresholds, settings
from core.schemas import MetaResponse

router = APIRouter(prefix=settings.API_V1_STR, tags=["Metadata"])


@router.get("/meta", response_model=MetaResponse)
async def get_metadata(
    response: Response,
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> MetaResponse:
    """Returns static and dynamic configurations: locations, regions, models, thresholds, active model version, and last run."""
    response.headers["Cache-Control"] = "public, max-age=300"

    locations = get_locations()
    regions = get_regions()
    models = get_models()
    thresholds = get_thresholds()

    active_version: Optional[Dict[str, Any]] = None
    last_run: Optional[Dict[str, Any]] = None

    try:
        conn = await db_pool.get_connection()
        try:
            ver_row = await conn.fetchrow(
                "SELECT id, created_at, storage_path, metrics, is_active FROM model_versions WHERE is_active = true LIMIT 1"
            )
            if ver_row:
                metrics_val = ver_row["metrics"]
                if isinstance(metrics_val, str):
                    try:
                        metrics_val = json.loads(metrics_val)
                    except Exception:
                        pass
                active_version = {
                    "id": ver_row["id"],
                    "created_at": ver_row["created_at"].isoformat() if ver_row["created_at"] else None,
                    "storage_path": ver_row["storage_path"],
                    "metrics": metrics_val,
                    "is_active": ver_row["is_active"],
                }

            run_row = await conn.fetchrow(
                "SELECT id, job, started_at, finished_at, status, rows_written, api_calls_est, message FROM pipeline_runs ORDER BY started_at DESC LIMIT 1"
            )
            if run_row:
                last_run = {
                    "id": run_row["id"],
                    "job": run_row["job"],
                    "started_at": run_row["started_at"].isoformat() if run_row["started_at"] else None,
                    "finished_at": run_row["finished_at"].isoformat() if run_row["finished_at"] else None,
                    "status": run_row["status"],
                    "rows_written": run_row["rows_written"],
                    "api_calls_est": float(run_row["api_calls_est"]) if run_row["api_calls_est"] is not None else None,
                    "message": run_row["message"],
                }
        finally:
            await db_pool.release_connection(conn)
    except Exception as e:
        active_version = {"status": f"Query error: {e}"}

    return MetaResponse(
        locations_count=len(locations),
        locations=locations,
        regions=regions,
        models=models,
        variables=["rain_mm", "tmax_c", "wind_max_kmh"],
        thresholds=thresholds,
        active_model_version=active_version,
        last_run=last_run,
        app_timezone=settings.APP_TZ_DISPLAY,
    )
