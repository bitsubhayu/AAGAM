"""Audit logger for AAGAM Assistant (PRD §11, §14).

Records every assistant question and response telemetry into PostgreSQL `chat_audit`:
- user_id (UUID or NULL)
- question (TEXT)
- mode (TEXT: explain, raw, both)
- tools (JSONB list of tool calls)
- model (TEXT: openai/gpt-oss-120b or fallback)
- tokens_in, tokens_out (INT)
- latency_ms (INT)
- cached (BOOLEAN)
- flagged (BOOLEAN)
- feedback (SMALLINT or NULL)
Retention: 30 days (managed by maintenance retention job).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import asyncpg

from api.app.db.pool import db_pool

logger = logging.getLogger("aagam.assistant.audit")


async def record_chat_audit(
    question: str,
    mode: str,
    tools_used: List[Dict[str, Any]],
    model: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    cached: bool = False,
    flagged: bool = False,
    user_id: Optional[str] = None,
    conn: Optional[asyncpg.Connection] = None,
) -> Optional[int]:
    """Writes an audit row to the chat_audit table."""
    tools_json = json.dumps(tools_used or [])

    # Validate or clean user_id if not a valid UUID format
    clean_user_id = None
    if user_id:
        try:
            import uuid
            clean_user_id = str(uuid.UUID(user_id))
        except (ValueError, TypeError):
            clean_user_id = None

    query = """
        INSERT INTO chat_audit (
            user_id, question, mode, tools, model,
            tokens_in, tokens_out, latency_ms, cached, flagged
        )
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10)
        RETURNING id;
    """

    try:
        if conn is not None:
            row = await conn.fetchrow(
                query,
                clean_user_id,
                question,
                mode,
                tools_json,
                model,
                tokens_in,
                tokens_out,
                latency_ms,
                cached,
                flagged,
            )
            return row["id"] if row else None

        if db_pool and db_pool.pool:
            async with db_pool.pool.acquire() as c:
                row = await c.fetchrow(
                    query,
                    clean_user_id,
                    question,
                    mode,
                    tools_json,
                    model,
                    tokens_in,
                    tokens_out,
                    latency_ms,
                    cached,
                    flagged,
                )
                return row["id"] if row else None
    except Exception as e:
        logger.warning(f"Failed to record chat_audit row: {e}")
        return None
