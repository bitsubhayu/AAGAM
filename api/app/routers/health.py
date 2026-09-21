"""Health and liveness probe endpoint (PRD §12, public, unauthenticated)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Response

from api.app.db.pool import db_pool
from core.config import settings
from core.schemas import HealthResponse

router = APIRouter(tags=["Observability"])


@router.get("/health", response_model=HealthResponse)
async def health_check(response: Response) -> HealthResponse:
    """Liveness probe returning server status, Supabase connectivity, and last ingest time."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

    connected = False
    details = "Supabase connection unavailable"
    last_ingest: Optional[str] = None

    try:
        conn = await db_pool.get_connection()
        try:
            val = await conn.fetchval("SELECT 1")
            connected = (val == 1)
            details = "Supabase pooler connected"

            row = await conn.fetchrow(
                "SELECT started_at FROM pipeline_runs WHERE status = 'SUCCESS' ORDER BY started_at DESC LIMIT 1"
            )
            if row and row["started_at"]:
                last_ingest = row["started_at"].isoformat()
        finally:
            await db_pool.release_connection(conn)
    except Exception as e:
        details = f"Connection check error: {e}"

    return HealthResponse(
        status="ok",
        app="AAGAM Backend API",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
        timezone_display=settings.APP_TZ_DISPLAY,
        supabase_connected=connected,
        last_successful_ingest=last_ingest,
        details=details,
    )
