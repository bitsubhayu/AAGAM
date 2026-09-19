import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.db.supabase import get_supabase_client, read_setup_row
from core.config import get_locations, get_models, get_regions, get_thresholds, settings
from core.schemas import HealthResponse, HelloResponse

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aagam.api")

app = FastAPI(
    title="AAGAM Backend API",
    description="Adaptive AI-Grid Assimilation Model — SIH 2026 PS 26081 (MoES / NCMRWF)",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware with environment-driven allowed origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["General"])
async def root() -> Dict[str, Any]:
    return {
        "project": "AAGAM — Adaptive AI-Grid Assimilation Model",
        "organization": "MoES / NCMRWF",
        "phase": "Phase 0 — Setup",
        "health": "/health",
        "hello": "/api/v1/hello",
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse, tags=["Observability"])
async def health_check() -> HealthResponse:
    """Liveness probe returning server status and Supabase connectivity."""
    client = get_supabase_client()
    connected = False
    details = "Supabase client not initialized (credentials pending)"

    if client:
        try:
            status, _, msg = read_setup_row()
            connected = (status == "PASS")
            details = msg
        except Exception as e:
            details = f"Connection error: {e}"

    return HealthResponse(
        status="ok",
        app="AAGAM Backend API",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
        timezone_display=settings.APP_TZ_DISPLAY,
        supabase_connected=connected,
        details=details,
    )


@app.get("/api/v1/hello", response_model=HelloResponse, tags=["Phase 0 Verification"])
async def hello_world() -> HelloResponse:
    """
    Phase 0 Hello-World Endpoint.
    Directly fulfills the PRD Phase 0 acceptance condition:
    'hello-world API on Render reads a row from Supabase'

    Distinguishes:
    - PASS: actual remote Supabase read
    - BLOCKED: credentials or database migration not yet populated
    - FAIL: implementation or connection error
    """
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


@app.get("/api/v1/meta", tags=["Metadata"])
async def get_meta() -> Dict[str, Any]:
    """Returns static configurations for locations, regions, models, and thresholds."""
    return {
        "locations_count": len(get_locations()),
        "locations": get_locations(),
        "regions": get_regions(),
        "models": get_models(),
        "thresholds": get_thresholds(),
        "app_timezone": settings.APP_TZ_DISPLAY,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
