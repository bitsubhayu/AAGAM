from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str = "AAGAM Backend API"
    version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=utc_now)
    timezone_display: str = "Asia/Kolkata"
    supabase_connected: bool = False
    details: Optional[str] = None


class SetupCheckRow(BaseModel):
    id: int
    component: str
    status: str
    verified_at: datetime
    metadata: Optional[Dict[str, Any]] = None


class HelloResponse(BaseModel):
    message: str
    project: str = "AAGAM (Adaptive AI-Grid Assimilation Model)"
    phase: str = "Phase 0 — Setup"
    verification_status: str = Field(default="BLOCKED", description="Explicit status: PASS, BLOCKED, or FAIL")
    supabase_status: str = Field(description="Database connectivity: connected, blocked, or failed")
    data_source: str = Field(description="Remote table or none")
    read_row: Optional[Dict[str, Any]] = None
    server_time: datetime = Field(default_factory=utc_now)
