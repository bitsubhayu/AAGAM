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
    expires_hours: int = 24
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
    evaluation_scope: str = "live"
    hits: Optional[int] = None
    false_alarms: Optional[int] = None
    misses: Optional[int] = None
    correct_negatives: Optional[int] = None


class SkillQueryResponse(BaseModel):
    group_by: str
    variable: Optional[str] = None
    evaluation_scope: str = "live"
    effective_window_days: int = 0
    verified_days_count: int = 0
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    latest_verified_date: Optional[str] = None
    data_status: str = "NO VERIFICATION DATA"
    truth_source: Optional[str] = None
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
    cancelled_by: Optional[str] = None
    cancelled_at: Optional[str] = None
    cancelled_by_name: Optional[str] = None
    event_id: Optional[int] = None
    lifecycle_state: Optional[str] = None
    previous_severity: Optional[str] = None
    rarity_label: Optional[str] = None


class SeverityCounts(BaseModel):
    advisory: int = 0
    watch: int = 0
    alert: int = 0


class AlertListResponse(BaseModel):
    count: int
    severity_counts: SeverityCounts = Field(default_factory=SeverityCounts)
    alerts: List[AlertItem]


class AlertAckResponse(BaseModel):
    id: int
    status: str
    acknowledged_by: str
    acknowledged_at: str


class AlertCancelResponse(BaseModel):
    id: int
    status: str
    cancelled_by: str
    cancelled_at: str
    cancelled_by_name: Optional[str] = None


class AlertEventCancelResponse(BaseModel):
    id: int
    status: str
    cancelled_by: str
    cancelled_at: str
    cancelled_by_name: Optional[str] = None
    lifecycle_state: Optional[str] = "cancelled"


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
    cancelled_by: Optional[str] = None
    cancelled_at: Optional[str] = None
    cancelled_by_name: Optional[str] = None


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
    rarity_label: Optional[str] = None
    rarity_context: Optional[str] = None


# ==============================================================================
# Climatology Endpoint (PRD §11.2, §12, Phase 13)
# ==============================================================================
class ClimatologyPercentileItem(BaseModel):
    location_id: int
    variable: str
    metric: str
    doy_window: int
    mean: Optional[float] = None
    p90: Optional[float] = None
    p95: Optional[float] = None
    p99: Optional[float] = None
    n_years: int
    computed_at: Optional[str] = None
    insufficient_history: bool = False


class ClimatologyResponse(BaseModel):
    location_id: int
    location_name: Optional[str] = None
    variable: Optional[str] = None
    metric: Optional[str] = None
    doy_window: Optional[int] = None
    date: Optional[str] = None
    insufficient_history: bool = False
    percentiles: List[ClimatologyPercentileItem]



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


# ==============================================================================
# Model Versioning & Lifecycle Endpoints (Design Doc §S, §T, Phase 4)
# ==============================================================================
class ModelVersionEvaluationItem(BaseModel):
    id: int
    version_id: int
    pipeline_run_id: Optional[int] = None
    window_type: str
    window_start: str
    window_end: str
    composite_score: Optional[float] = None
    strata_included: int
    strata_excluded: int
    regions_covered: Optional[int] = 0
    locations_covered: Optional[int] = None
    lead_days_covered: int
    sample_counts: Dict[str, Any] = Field(default_factory=dict)
    metrics_detail: Dict[str, Any] = Field(default_factory=dict)
    computed_at: str


class ModelVersionSummary(BaseModel):
    id: int
    status: str
    algorithm_type: str
    evaluation_policy: str
    is_active: bool
    parent_version_id: Optional[int] = None
    created_at: str
    activated_at: Optional[str] = None
    deactivated_at: Optional[str] = None
    created_by: Optional[str] = None
    recent_evaluation: Optional[Dict[str, Any]] = None


class ModelVersionDecisionItem(BaseModel):
    id: int
    decision: str
    previous_version_id: Optional[int] = None
    candidate_version_id: Optional[int] = None
    composite_recent_prev: Optional[float] = None
    composite_recent_cand: Optional[float] = None
    composite_seasonal_prev: Optional[float] = None
    composite_seasonal_cand: Optional[float] = None
    composite_longterm_prev: Optional[float] = None
    composite_longterm_cand: Optional[float] = None
    sample_counts: Dict[str, Any] = Field(default_factory=dict)
    evaluation_window_start: Optional[str] = None
    evaluation_window_end: Optional[str] = None
    reason: str
    triggered_by: Optional[str] = None
    pipeline_run_id: Optional[int] = None
    algorithm_version: str
    created_at: str


class AutomationStateResponse(BaseModel):
    id: int = 1
    frozen: bool
    frozen_reason: Optional[str] = None
    frozen_by: Optional[str] = None
    frozen_at: Optional[str] = None
    cooldown_until: Optional[str] = None
    rollback_count_14d: int = 0
    updated_at: str
    current_candidate: Optional[Dict[str, Any]] = None


class FreezeRequest(BaseModel):
    reason: str = Field(..., min_length=10, description="Mandatory reason for freezing automation (min 10 chars)")


class UnfreezeRequest(BaseModel):
    reason: str = Field(..., min_length=10, description="Mandatory reason for unfreezing automation (min 10 chars)")


class ForceLastKnownGoodRequest(BaseModel):
    reason: str = Field(..., min_length=10, description="Mandatory reason for forcing last-known-good model (min 10 chars)")


class DisableCandidateRequest(BaseModel):
    reason: str = Field(..., min_length=10, description="Mandatory reason for disabling candidate (min 10 chars)")


# ==============================================================================
# Forecaster Access & Governance Endpoints
# ==============================================================================
class CheckAccessRequest(BaseModel):
    email: str = Field(
        ...,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="User email address to check access for",
    )


class CheckAccessResponse(BaseModel):
    status: str = "ok"
    email: str
    is_approved: bool
    role: Optional[str] = None


class ForecasterAccessRequestCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Full name of requester")
    email: str = Field(
        ...,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Requester institutional email address",
    )
    institution: Optional[str] = Field(None, max_length=150, description="Meteorological or research institution")


class ForecasterAccessRequestItem(BaseModel):
    id: int
    name: str
    email: str
    institution: Optional[str] = None
    status: str
    created_at: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    rejection_reason: Optional[str] = None


