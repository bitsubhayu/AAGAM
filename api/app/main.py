"""FastAPI Main Application for AAGAM (Adaptive AI-Grid Assimilation Model).

SIH 2026 PS 26081 (MoES / NCMRWF).
Phase 6 Implementation:
- /api/v1 API router mount
- asyncpg connection pool with statement_cache_size=0
- Supabase JWT authentication and role-based access control
- Strict PRD §12 error envelope
- Slowapi rate limiting
- CORS locked to configured origins
- Cold-start softening headers
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from api.app.db.pool import db_pool
from api.app.db.supabase import read_setup_row
from api.app.middleware.rate_limit import custom_rate_limit_exceeded_handler, limiter
from api.app.routers import (
    alerts,
    artifacts,
    chat,
    export,
    forecast,
    health,
    history,
    meta,
    models,
    pipeline,
    skill,
    weights,
)
from api.app.routers import (
    map as map_router,
)
from core.config import settings
from core.schemas import HelloResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aagam.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager handling asyncpg connection pool."""
    logger.info("Starting up AAGAM API...")
    await db_pool.init_pool()
    yield
    logger.info("Shutting down AAGAM API...")
    await db_pool.close_pool()


app = FastAPI(
    title="AAGAM Backend API",
    description="Adaptive AI-Grid Assimilation Model — SIH 2026 PS 26081 (MoES / NCMRWF)",
    version="0.6.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Attach rate limiter state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_exceeded_handler)


# ==============================================================================
# Strict PRD §12 Error Envelope Handlers
# ==============================================================================
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Formats all HTTPExceptions to follow the PRD error envelope."""
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", "HTTP_ERROR")
        msg = exc.detail.get("message", str(exc.detail))
        retry_after = exc.detail.get("retry_after")
    else:
        code = "HTTP_ERROR"
        msg = str(exc.detail)
        retry_after = None

    headers = getattr(exc, "headers", None) or {}
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": msg, "retry_after": retry_after}},
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Formats request validation errors to follow the PRD error envelope."""
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    loc = " -> ".join([str(item) for item in first_error.get("loc", [])])
    msg = f"Validation failed at '{loc}': {first_error.get('msg', 'Invalid input')}"

    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": msg, "retry_after": None}},
    )


# CORS Middleware with environment-driven allowed origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Root endpoint
@app.get("/", tags=["General"])
async def root() -> Dict[str, Any]:
    return {
        "project": "AAGAM — Adaptive AI-Grid Assimilation Model",
        "organization": "MoES / NCMRWF",
        "phase": "Phase 0 — Setup",
        "version": "0.6.0",
        "health": "/health",
        "docs": "/docs",
        "api_base": settings.API_V1_STR,
    }


# Retain Phase 0 Hello-World for backward compatibility
@app.get("/api/v1/hello", response_model=HelloResponse, tags=["Phase 0 Verification"])
async def hello_world() -> HelloResponse:
    status, row_data, message = read_setup_row()
    if status == "PASS" and row_data:
        return HelloResponse(
            message="Hello from AAGAM! Successfully read row from Supabase.",
            project="AAGAM (Adaptive AI-Grid Assimilation Model)",
            phase="Phase 0 — Setup",
            verification_status="PASS",
            supabase_status="connected",
            data_source="supabase:_aagam_setup_check",
            read_row=row_data,
            server_time=datetime.now(timezone.utc),
        )
    elif status == "BLOCKED":
        return HelloResponse(
            message=f"Supabase read blocked: {message}",
            project="AAGAM (Adaptive AI-Grid Assimilation Model)",
            phase="Phase 0 — Setup",
            verification_status="BLOCKED",
            supabase_status="blocked",
            data_source="none",
            read_row=None,
            server_time=datetime.now(timezone.utc),
        )
    else:
        return HelloResponse(
            message=f"Supabase read failed: {message}",
            project="AAGAM (Adaptive AI-Grid Assimilation Model)",
            phase="Phase 0 — Setup",
            verification_status="FAIL",
            supabase_status="failed",
            data_source="none",
            read_row=None,
            server_time=datetime.now(timezone.utc),
        )


# Mount PRD §12 Routers
app.include_router(health.router)
app.include_router(meta.router)
app.include_router(forecast.router)
app.include_router(map_router.router)
app.include_router(weights.router)
app.include_router(skill.router)
app.include_router(alerts.router)
app.include_router(history.router)
app.include_router(artifacts.router)
app.include_router(export.router)
app.include_router(chat.router)
app.include_router(pipeline.router)
app.include_router(models.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
