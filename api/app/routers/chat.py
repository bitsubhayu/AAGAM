"""Assistant chat endpoint scaffolding (PRD §12, role: any).

Preserves the API contract for Phase 8 while respecting the Phase 6 project lock.
Phase 8 LLM tool loop, Groq client, token budget, and full SSE generation belong strictly to Phase 8.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.app.auth.dependencies import CurrentUser, require_role
from core.config import settings

logger = logging.getLogger("aagam.api.chat")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Chat"])


class ChatRequest(BaseModel):
    message: str


async def chat_sse_scaffold(question: str) -> AsyncGenerator[str, None]:
    """Yields minimal SSE stream preserving the Phase 8 contract."""
    yield f"event: start\ndata: {json.dumps({'status': 'connected'})}\n\n"
    await asyncio.sleep(0.01)
    yield f"event: text\ndata: {json.dumps({'content': f'AAGAM Assistant scaffold: Received question \"{question}\". Full conversational assistant engine is implemented in Phase 8.'})}\n\n"
    await asyncio.sleep(0.01)
    yield f"event: end\ndata: {json.dumps({'status': 'completed'})}\n\n"


@router.post("/chat")
async def chat_endpoint(
    body: ChatRequest,
    current_user: CurrentUser = Depends(require_role("any")),
) -> StreamingResponse:
    """Chat endpoint supporting SSE stream (Phase 6 scaffold; full LLM agent in Phase 8)."""
    return StreamingResponse(
        chat_sse_scaffold(body.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
