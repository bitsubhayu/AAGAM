"""Database connection pool for AAGAM API using asyncpg.

Configured specifically for Supabase Transaction Pooler:
- statement_cache_size=0 (required for transaction-mode PgBouncer)
- safe lifecycle management across test/production event loops
- RLS claims injection for authenticated user queries
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

import asyncpg

from core.config import settings

logger = logging.getLogger("aagam.api.db.pool")


class DatabasePool:
    """Manages the asyncpg connection pool with Supabase pooler compatibility."""

    def __init__(self) -> None:
        self.pool: Optional[asyncpg.Pool] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def init_pool(self) -> None:
        """Initializes or re-initializes the asyncpg connection pool for the active event loop."""
        current_loop = asyncio.get_running_loop()
        if self.pool is not None:
            if self._loop is current_loop and not current_loop.is_closed():
                return
            # Clean up stale pool from a previous or closed event loop
            try:
                if self._loop and not self._loop.is_closed():
                    await self.pool.close()
            except Exception:
                pass
            self.pool = None
            self._loop = None

        db_url = settings.DATABASE_URL
        if not db_url:
            logger.warning("DATABASE_URL is not configured. DatabasePool will remain uninitialized.")
            return

        try:
            logger.info("Initializing asyncpg connection pool with statement_cache_size=0...")
            self.pool = await asyncpg.create_pool(
                dsn=db_url,
                statement_cache_size=0,  # CRITICAL: required for Supabase transaction pooler
                min_size=settings.DB_POOL_MIN_SIZE,
                max_size=settings.DB_POOL_MAX_SIZE,
                command_timeout=30.0,
            )
            self._loop = current_loop
            logger.info("asyncpg connection pool initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize asyncpg connection pool: {e}")
            self.pool = None
            self._loop = None

    async def close_pool(self) -> None:
        """Closes the asyncpg connection pool cleanly on shutdown."""
        if self.pool is not None:
            logger.info("Closing asyncpg connection pool...")
            try:
                await self.pool.close()
            except Exception as e:
                logger.debug(f"Exception during pool close: {e}")
            self.pool = None
            self._loop = None
            logger.info("asyncpg connection pool closed.")

    async def get_connection(self) -> asyncpg.Connection:
        """Acquires a single connection from the pool."""
        current_loop = asyncio.get_running_loop()
        if self.pool is None or self._loop is not current_loop:
            await self.init_pool()
        if self.pool is None:
            raise RuntimeError("Database connection pool is not available.")
        return await self.pool.acquire()

    async def release_connection(self, conn: asyncpg.Connection) -> None:
        """Releases connection back to the pool."""
        if self.pool is not None:
            await self.pool.release(conn)


db_pool = DatabasePool()


async def get_db_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    """FastAPI dependency that yields an asyncpg connection from the pool."""
    current_loop = asyncio.get_running_loop()
    if db_pool.pool is None or db_pool._loop is not current_loop or current_loop.is_closed():
        await db_pool.init_pool()

    if db_pool.pool is None:
        raise RuntimeError("Database connection pool is not initialized.")

    async with db_pool.pool.acquire() as conn:
        yield conn


async def set_rls_claims(conn: asyncpg.Connection, user_id: str, role: str = "authenticated") -> None:
    """Configures PostgreSQL session variables so auth.uid() and role evaluate correctly under RLS.

    Supabase PostgREST uses `request.jwt.claims` JSON and `role` config.
    """
    claims = json.dumps({"sub": user_id, "role": role})
    await conn.execute("SELECT set_config('request.jwt.claims', $1, true);", claims)
    await conn.execute("SELECT set_config('role', 'authenticated', true);")
