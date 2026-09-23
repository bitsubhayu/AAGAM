"""Pipeline execution status and telemetry endpoint (PRD §12, role: any)."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, Response

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn
from core.config import settings
from core.schemas import PipelineJobRun, PipelineStatusResponse

logger = logging.getLogger("aagam.api.pipeline")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Pipeline"])


@router.get("/pipeline/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> PipelineStatusResponse:
    """Returns execution telemetry, API call estimates, and model version status (PRD §12, role: any)."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=30"

    active_ver: Optional[Dict[str, Any]] = None
    ver_row = await conn.fetchrow(
        "SELECT id, created_at, storage_path, metrics, is_active FROM model_versions WHERE is_active = true LIMIT 1"
    )
    if ver_row:
        m_val = ver_row["metrics"]
        if isinstance(m_val, str):
            try:
                m_val = json.loads(m_val)
            except Exception:
                pass
        active_ver = {
            "id": ver_row["id"],
            "created_at": ver_row["created_at"].isoformat() if ver_row["created_at"] else None,
            "storage_path": ver_row["storage_path"],
            "metrics": m_val,
            "is_active": ver_row["is_active"],
        }

    run_rows = await conn.fetch(
        """
        SELECT id, job, started_at, finished_at, status, rows_written, api_calls_est, message
        FROM pipeline_runs
        ORDER BY started_at DESC
        LIMIT 20
        """
    )

    runs: List[PipelineJobRun] = []
    for r in run_rows:
        runs.append(
            PipelineJobRun(
                id=r["id"],
                job=r["job"],
                started_at=r["started_at"].isoformat() if r["started_at"] else "",
                finished_at=r["finished_at"].isoformat() if r["finished_at"] else None,
                status=r["status"],
                rows_written=r["rows_written"],
                api_calls_est=float(r["api_calls_est"]) if r["api_calls_est"] is not None else None,
                message=r["message"],
            )
        )

    return PipelineStatusResponse(
        active_model_version=active_ver,
        last_runs=runs,
    )
