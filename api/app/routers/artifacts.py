"""Assistant stored artifacts endpoint (PRD §12, role: owner/coordinator)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from api.app.auth.dependencies import CurrentUser, require_role
from core.config import settings
from core.schemas import ArtifactResponse

logger = logging.getLogger("aagam.api.artifacts")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Artifacts"])

# In-memory registry of stored assistant data artifacts (PRD §8.2: full results stored server-side under artifact_id)
_ARTIFACT_STORE: Dict[str, Dict[str, Any]] = {}


def register_artifact(artifact_id: str, owner_id: str, data: List[Dict[str, Any]]) -> None:
    """Stores a full data artifact server-side for paginated retrieval."""
    _ARTIFACT_STORE[artifact_id] = {
        "artifact_id": artifact_id,
        "owner_id": owner_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


@router.get("/artifacts/{id}", response_model=ArtifactResponse)
async def get_artifact(
    id: str = Path(..., description="Artifact UUID or string identifier"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    current_user: CurrentUser = Depends(require_role("any")),
) -> ArtifactResponse:
    """Retrieves paginated pages of a stored assistant result. (PRD §12, role: owner/coordinator)."""
    artifact: Optional[Dict[str, Any]] = _ARTIFACT_STORE.get(id)

    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ARTIFACT_NOT_FOUND",
                "message": f"Artifact '{id}' not found.",
                "retry_after": None,
            },
        )

    # Enforce owner or coordinator role
    is_owner = artifact.get("owner_id") == current_user.user_id
    is_coordinator = current_user.role == "coordinator"

    if not (is_owner or is_coordinator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "You do not have permission to view this artifact (owner or coordinator only).",
                "retry_after": None,
            },
        )

    all_records = artifact["data"]
    total = len(all_records)
    paged_data = all_records[offset : offset + limit]

    return ArtifactResponse(
        artifact_id=id,
        created_at=artifact["created_at"],
        total_records=total,
        offset=offset,
        limit=limit,
        data=paged_data,
    )
