"""Assistant chat endpoint with real Groq tool-use agent and SSE streaming (PRD §9, §12, role: any)."""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.app.assistant.runner import run_assistant_stream
from api.app.assistant.schemas import ChatRequest
from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn
from core.config import settings

logger = logging.getLogger("aagam.api.chat")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Chat"])


@router.post("/chat")
async def chat_endpoint(
    body: ChatRequest,
    current_user: CurrentUser = Depends(require_role("any")),
    conn: Optional[asyncpg.Connection] = Depends(get_db_conn),
) -> StreamingResponse:
    """Assistant chat endpoint executing Groq tool-use loop and streaming SSE events (PRD §9.8)."""
    return StreamingResponse(
        run_assistant_stream(body, current_user, conn=conn),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
