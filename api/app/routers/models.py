"""Model version activation and rollback endpoint (PRD §12, role: admin)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.model_versions import invalidate_model_version_cache
from api.app.db.pool import get_db_conn
from core.config import settings
from core.schemas import ModelActivationResponse

logger = logging.getLogger("aagam.api.models")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Models"])


@router.post("/models/{id}/activate", response_model=ModelActivationResponse)
async def activate_model_version(
    id: int = Path(..., description="ID of the model version to activate"),
    current_user: CurrentUser = Depends(require_role("admin")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> ModelActivationResponse:
    """Activates or rolls back to a specified model version (PRD §12, role: admin only)."""
    # Check if target model version exists
    existing = await conn.fetchrow("SELECT id, storage_path, metrics FROM model_versions WHERE id = $1", id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "MODEL_VERSION_NOT_FOUND",
                "message": f"Model version {id} not found.",
                "retry_after": None,
            },
        )

    # Atomically deactivate current and activate target version
    async with conn.transaction():
        await conn.execute("UPDATE model_versions SET is_active = false WHERE is_active = true")
        updated = await conn.fetchrow(
            """
            UPDATE model_versions
            SET is_active = true
            WHERE id = $1
            RETURNING id, is_active, storage_path, metrics
            """,
            id,
        )
        invalidate_model_version_cache()

    m_dict = updated["metrics"]
    if isinstance(m_dict, str):
        try:
            m_dict = json.loads(m_dict)
        except Exception:
            m_dict = {"raw": m_dict}

    return ModelActivationResponse(
        id=updated["id"],
        is_active=updated["is_active"],
        storage_path=updated["storage_path"],
        metrics=m_dict,
        activated_at=datetime.now(timezone.utc).isoformat(),
    )
