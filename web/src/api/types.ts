export interface LocationItem {
  slug: string;
  name: string;
  state?: string;
  region: string;
  terrain?: string;
  lat?: number;
  lon?: number;
}

export interface RegionItem {
  code: string;
  name: string;
  description?: string;
}

export interface ThresholdsConfig {
  rainfall?: Record<string, any>;
  heatwave?: Record<string, any>;
  wind?: Record<string, any>;
  [key: string]: any;
}

export interface MetaResponse {
  locations_count: number;
  locations: LocationItem[];
  regions: RegionItem[];
  models: string[];
  variables: string[];
  thresholds: ThresholdsConfig;
  active_model_version?: {
    id: number;
    created_at?: string;
    storage_path?: string;
    metrics?: Record<string, any>;
    is_active?: boolean;
    [key: string]: any;
  };
  last_run?: {
    id: number;
    job: string;
    started_at?: string;
    finished_at?: string;
    status: string;
    rows_written?: number;
    api_calls_est?: number;
    message?: string;
  };
  app_timezone: string;
}

export interface ForecastLocationInfo {
  slug: string;
  name: string;
  region: string;
}

export interface ForecastSeriesItem {
  valid_date: string;
  lead_days: number;
  blended: number;
  models: Record<string, number>;
  spread: number;
  models_over_threshold: number;
}

export interface ForecastResponse {
  location: ForecastLocationInfo;
  variable: string;
  unit: string;
  issue_time: string;
  model_version: string;
  degraded: boolean;
  series: ForecastSeriesItem[];
}

export interface MapPointItem {
  location_id: number;
  slug: string;
  name: string;
  region: string;
  lat: number;
  lon: number;
  dominant_model: string;
  blended_value?: number;
  models?: Record<string, number>;
}

export interface MapResponse {
  variable: string;
  lead_days: number;
  valid_date: string;
  issue_time: string;
  unit: string;
  points: MapPointItem[];
}

export interface LocationDominantWeight {
  location_id: number;
  slug: string;
  name: string;
  region: string;
  lat: number;
  lon: number;
  dominant_model: string;
  all_weights: Record<string, number>;
}

export interface WeightsMapResponse {
  variable: string;
  lead_days: number;
  season: string;
  version_id: number;
  locations: LocationDominantWeight[];
}

export interface WeightMatrixItem {
  variable: string;
  region: string;
  season: string;
  lead_days: number;
  model: string;
  weight: number;
  n_samples: number;
  fallback_level: string;
}

export interface WeightsResponse {
  version_id: number;
  method: string;
  variable?: string;
  region?: string;
  season?: string;
  lead_days?: number;
  weights: WeightMatrixItem[];
}

export interface WeightOverrideCreate {
  variable: string;
  region: string;
  season: string;
  lead_days: number;
  weights: Record<string, number>;
  reason: string;
  expires_hours?: number;
}

export interface WeightOverrideResponse {
  id: number;
  user_id: string;
  variable: string;
  region: string;
  season: string;
  lead_days: number;
  original_weights: Record<string, number>;
  overridden_weights: Record<string, number>;
  reason: string;
  created_at: string;
  expires_at: string;
  status: string;
}

export interface AlertItem {
  id: number;
  created_at: string;
  issue_time: string;
  location_id: number;
  location_name: string;
  location_slug: string;
  region: string;
  hazard: string;
  severity: "advisory" | "watch" | "alert" | string;
  valid_date: string;
  lead_days: number;
  value: number;
  models_over: number;
  spread: number;
  rule: string;
  status: "active" | "acknowledged" | "expired" | string;
  acknowledged_by?: string;
  acknowledged_at?: string;
  event_id?: number | null;
  lifecycle_state?: "new" | "upgraded" | "downgraded" | "unchanged" | "cancelled" | string;
  previous_severity?: "advisory" | "watch" | "alert" | string | null;
  rarity_label?: string | null;
}

export interface AlertListResponse {
  count: number;
  alerts: AlertItem[];
}

export interface AlertAckResponse {
  id: number;
  status: string;
  acknowledged_by: string;
  acknowledged_at: string;
  message?: string;
}

export interface AlertEventItem {
  id: number;
  location_id: number;
  location_name?: string;
  location_slug?: string;
  region?: string;
  hazard: string;
  status: "active" | "expired" | "cancelled" | string;
  severity_peak: "advisory" | "watch" | "alert" | string;
  value_peak?: number | null;
  start_date: string;
  end_date: string;
  first_detected_at: string;
  last_updated_at: string;
  outcome: "hit" | "false_alarm" | "pending" | "unverifiable" | string;
  verified_at?: string | null;
}

export interface LifecycleEventNode {
  issue_time: string;
  lifecycle_state: string;
  severity: string;
  previous_severity?: string | null;
  valid_date: string;
  value?: number | null;
}

export interface AlertEventDetailResponse {
  event: AlertEventItem;
  alerts: AlertItem[];
  lifecycle_history: LifecycleEventNode[];
  guidance?: any;
  track_record?: any;
  share_text?: string | null;
}

export interface AlertEventAckResponse {
  id: number;
  status: string;
  acknowledged_by: string;
  acknowledged_at: string;
}

export interface SkillScoreItem {
  computed_at: string;
  window_days: number;
  variable: string;
  region: string;
  season: string;
  lead_days: number;
  model: string;
  mae?: number | null;
  rmse?: number | null;
  bias?: number | null;
  n: number;
  pod?: number | null;
  far?: number | null;
  csi?: number | null;
  threshold_mm: number;
  is_weekly: boolean;
}

export interface SkillQueryResponse {
  group_by: string;
  variable?: string;
  scores: SkillScoreItem[];
}

export interface PipelineJobRun {
  id: number;
  job: string;
  started_at: string;
  finished_at?: string | null;
  status: string;
  rows_written?: number | null;
  api_calls_est?: number | null;
  message?: string | null;
}

export interface PipelineStatusResponse {
  active_model_version?: {
    id: number;
    created_at?: string;
    storage_path?: string;
    metrics?: Record<string, any>;
    is_active?: boolean;
    [key: string]: any;
  } | null;
  last_runs: PipelineJobRun[];
}

export interface ModelActivationResponse {
  id: number;
  is_active: boolean;
  storage_path: string;
  metrics: Record<string, any>;
  activated_at: string;
}

export interface HistoryRecord {
  valid_date: string;
  lead_days: number;
  blended?: number | null;
  gfs?: number | null;
  ecmwf_ifs?: number | null;
  icon?: number | null;
  aifs?: number | null;
}

export interface HistoryResponse {
  location: string;
  variable: string;
  count: number;
  offset: number;
  limit: number;
  records: HistoryRecord[];
}

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  timestamp: string;
  timezone_display: string;
  supabase_connected: boolean;
  details?: string;
}

export interface ArtifactResponse {
  artifact_id: string;
  created_at: string;
  total_records: number;
  offset: number;
  limit: number;
  data: Record<string, any>[];
}

export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    retry_after?: number | null;
  };
}
