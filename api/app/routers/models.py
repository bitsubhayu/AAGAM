"""Model version activation and rollback operational endpoints."""

from __future__ import annotations

import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn
from core.config import settings
from core.schemas import ModelActivationResponse

logger = logging.getLogger("aagam.api.models")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Models"])


@router.post("/models/{id}/activate", response_model=ModelActivationResponse)
async def activate_model_version(
    id: int = Path(..., description="ID of the model version to activate"),
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> ModelActivationResponse:
    """Model activation is managed out-of-band by pipeline/system owner (Part 17). Application users cannot activate models."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "OPERATION_DISALLOWED",
            "message": "Model activation and rollback are operational tasks managed out-of-band by the automated pipeline and system owner, and are not accessible to application users.",
            "retry_after": None,
        },
    )
