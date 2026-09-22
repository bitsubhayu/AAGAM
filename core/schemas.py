from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ==============================================================================
# Standard PRD Error Envelope
# ==============================================================================
class APIErrorDetail(BaseModel):
    code: str
    message: str
    retry_after: Optional[int] = None


class ErrorResponse(BaseModel):
    error: APIErrorDetail


# ==============================================================================
# Health & Phase 0 Verification
# ==============================================================================
class HealthResponse(BaseModel):
    status: str = "ok"
    app: str = "AAGAM Backend API"
    version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=utc_now)
    timezone_display: str = "Asia/Kolkata"
    supabase_connected: bool = False
    last_successful_ingest: Optional[str] = None
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


# ==============================================================================
# Meta Endpoint
# ==============================================================================
class MetaResponse(BaseModel):
    locations_count: int
    locations: List[Dict[str, Any]]
    regions: Dict[str, Any]
    models: Dict[str, Any]
    variables: List[str]
    thresholds: Dict[str, Any]
    active_model_version: Optional[Dict[str, Any]] = None
    last_run: Optional[Dict[str, Any]] = None
    app_timezone: str = "Asia/Kolkata"


# ==============================================================================
# Forecast Endpoint (PRD §12)
# ==============================================================================
class ForecastLocationInfo(BaseModel):
    slug: str
    name: str
    region: str


class ForecastSeriesItem(BaseModel):
    valid_date: str
    lead_days: int
    blended: Optional[float] = None
    models: Dict[str, Optional[float]]
    spread: Optional[float] = None
    models_over_threshold: Optional[int] = 0


class ForecastResponse(BaseModel):
    location: ForecastLocationInfo
    variable: str
    unit: str
    issue_time: str
    model_version: str
    degraded: bool
    series: List[ForecastSeriesItem]


# ==============================================================================
# Map Endpoint (PRD §12)
# ==============================================================================
class MapPointItem(BaseModel):
    location_id: int
    slug: str
    name: str
    region: str
    lat: float
    lon: float
    blended: Optional[float] = None
    spread: Optional[float] = None
    degraded: bool = False
    dominant_model: Optional[str] = None


class MapResponse(BaseModel):
    variable: str
    lead_days: int
    valid_date: str
    issue_time: str
    unit: str
    points: List[MapPointItem]


# ==============================================================================
# Weights Endpoints (PRD §12)
# ==============================================================================
class WeightMatrixItem(BaseModel):
    variable: str
    region: str
    season: str
    lead_days: int
    model: str
    weight: float
    method: str
    n_samples: int
    fallback_level: str


class WeightsResponse(BaseModel):
    version_id: int
    method: str
    weights: List[WeightMatrixItem]


class LocationDominantWeight(BaseModel):
    location_id: int
    slug: str
    name: str
    region: str
    lat: float
    lon: float
    dominant_model: str
    weight: float
    all_weights: Dict[str, float]


class WeightsMapResponse(BaseModel):
    variable: str
    lead_days: int
    season: str
    locations: List[LocationDominantWeight]


class WeightOverrideCreate(BaseModel):
    variable: str
    region: str
    season: str
    lead_days: int
    weights: Dict[str, float]
    reason: str
    expires_at: Optional[datetime] = None


class WeightOverrideResponse(BaseModel):
    id: int
    created_by: str
    created_at: str
    variable: str
    region: str
    season: str
    lead_days: int
    weights: Dict[str, float]
    reason: str
    expires_at: Optional[str] = None
    active: bool


# ==============================================================================
# Skill Endpoint (PRD §12)
# ==============================================================================
class SkillScoreItem(BaseModel):
    computed_at: str
    window_days: int
    variable: str
    region: str
    season: str
    lead_days: int
    model: str
    mae: Optional[float] = None
    rmse: Optional[float] = None
    bias: Optional[float] = None
    n: Optional[int] = None
    pod: Optional[float] = None
    far: Optional[float] = None
    csi: Optional[float] = None
    threshold_mm: float = 0.0
    is_weekly: bool = False


class SkillQueryResponse(BaseModel):
    group_by: str
    variable: Optional[str] = None
    scores: List[SkillScoreItem]


# ==============================================================================
# Alerts Endpoints (PRD §12)
# ==============================================================================
class AlertItem(BaseModel):
    id: int
    created_at: str
    issue_time: str
    location_id: int
    location_name: Optional[str] = None
    location_slug: Optional[str] = None
    region: Optional[str] = None
    hazard: str
    severity: str
    valid_date: str
    lead_days: int
    value: Optional[float] = None
    models_over: Optional[int] = None
    spread: Optional[float] = None
    rule: Dict[str, Any]
    status: str
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[str] = None
    event_id: Optional[int] = None
    lifecycle_state: Optional[str] = None
    previous_severity: Optional[str] = None
    rarity_label: Optional[str] = None


class AlertListResponse(BaseModel):
    count: int
    alerts: List[AlertItem]


class AlertAckResponse(BaseModel):
    id: int
    status: str
    acknowledged_by: str
    acknowledged_at: str


class AlertEventItem(BaseModel):
    id: int
    location_id: int
    location_name: Optional[str] = None
    location_slug: Optional[str] = None
    region: Optional[str] = None
    hazard: str
    status: str
    severity_peak: str
    value_peak: Optional[float] = None
    start_date: str
    end_date: str
    first_detected_at: str
    last_updated_at: str
    outcome: str = "pending"
    verified_at: Optional[str] = None


class LifecycleEventNode(BaseModel):
    issue_time: str
    lifecycle_state: str
    severity: str
    previous_severity: Optional[str] = None
    valid_date: str
    value: Optional[float] = None


class AlertEventDetailResponse(BaseModel):
    event: AlertEventItem
    alerts: List[AlertItem]
    lifecycle_history: List[LifecycleEventNode]
    guidance: Optional[Dict[str, Any]] = None
    track_record: Optional[Dict[str, Any]] = None
    share_text: Optional[str] = None


class AlertEventAckResponse(BaseModel):
    id: int
    status: str
    acknowledged_by: str
    acknowledged_at: str


# ==============================================================================
# History Endpoint (PRD §12)
# ==============================================================================
class HistoryRecord(BaseModel):
    location_id: int
    variable: str
    valid_date: str
    lead_days: int
    kind: str
    source: str
    value: Optional[float] = None
    issue_time: Optional[str] = None


class HistoryResponse(BaseModel):
    location: str
    variable: str
    count: int
    limit: int
    offset: int
    records: List[HistoryRecord]


# ==============================================================================
# Artifacts Endpoint (PRD §12)
# ==============================================================================
class ArtifactResponse(BaseModel):
    artifact_id: str
    created_at: str
    total_records: int
    offset: int
    limit: int
    data: List[Dict[str, Any]]


# ==============================================================================
# Pipeline Status Endpoint (PRD §12)
# ==============================================================================
class PipelineJobRun(BaseModel):
    id: int
    job: str
    started_at: str
    finished_at: Optional[str] = None
    status: str
    rows_written: Optional[int] = None
    api_calls_est: Optional[float] = None
    message: Optional[str] = None


class PipelineStatusResponse(BaseModel):
    active_model_version: Optional[Dict[str, Any]] = None
    last_runs: List[PipelineJobRun]


# ==============================================================================
# Model Activation Endpoint (PRD §12)
# ==============================================================================
class ModelActivationResponse(BaseModel):
    id: int
    is_active: bool
    storage_path: str
    metrics: Dict[str, Any]
    activated_at: str
