"""Pydantic schemas and Tool Envelope definitions for AAGAM Assistant (PRD §9.4, §9.8)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ToolEnvelope(BaseModel):
    """Authoritative Tool Envelope shape defined in PRD §9.4."""

    ok: bool = True
    artifact_id: str
    title: str
    columns: List[str]
    n_rows: int
    preview: List[List[Any]] = Field(default_factory=list, description="At most 5 preview rows")
    stats: Dict[str, Any] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)

    def to_llm_dict(self) -> Dict[str, Any]:
        """Compact summary for the LLM prompt (target <= 700 tokens, PRD §9.4)."""
        return {
            "title": self.title,
            "columns": self.columns,
            "n_rows": self.n_rows,
            "preview": self.preview[:5],
            "stats": self.stats,
            "meta": self.meta,
        }

    def to_data_table_dict(self, full_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Browser SSE data_table payload (first <= 500 rows, PRD §9.8)."""
        # Convert full rows (dict) to matrix rows matching columns order
        matrix_rows: List[List[Any]] = []
        for r in full_rows[:500]:
            matrix_rows.append([r.get(c) for c in self.columns])

        return {
            "artifact_id": self.artifact_id,
            "title": self.title,
            "columns": self.columns,
            "rows": matrix_rows,
            "n_rows_total": len(full_rows),
            "download_links": {
                "csv": f"/api/v1/artifacts/{self.artifact_id}?format=csv",
                "json": f"/api/v1/artifacts/{self.artifact_id}?format=json",
            },
        }


# ==============================================================================
# The Six Allow-Listed Tool Argument Models (PRD §9.4)
# ==============================================================================

class GetForecastArgs(BaseModel):
    """Arguments for get_forecast tool."""

    location: str = Field(..., description="Location name or slug (e.g. Bhubaneswar, Nagpur)")
    variable: Literal["rain_mm", "tmax_c", "wind_max_kmh"] = Field(
        ..., description="Weather variable: rain_mm, tmax_c, wind_max_kmh"
    )
    lead_days_max: int = Field(
        default=7, ge=0, le=7, description="Maximum lead days forward (0 to 7, default 7)"
    )


class GetWeightsArgs(BaseModel):
    """Arguments for get_weights tool."""

    variable: str = Field(..., description="Weather variable: rain_mm, tmax_c, wind_max_kmh")
    region: Optional[str] = Field(None, description="Region code (e.g. EAST_NE, SOUTH, CENTRAL, NW, HIMALAYAN)")
    location: Optional[str] = Field(None, description="Location name or slug (resolves to region)")
    season: Optional[str] = Field(None, description="Season: monsoon, post_monsoon, winter, pre_monsoon")
    lead_days: Optional[int] = Field(None, ge=0, le=7, description="Specific lead day (0 to 7)")


class GetSkillArgs(BaseModel):
    """Arguments for get_skill tool."""

    metric: Literal["mae", "rmse", "bias", "skill_score", "pod", "far", "csi"] = Field(
        ..., description="Verification metric name"
    )
    group_by: Literal["lead", "region", "season", "model"] = Field(
        ..., description="Grouping dimension: lead, region, season, model"
    )
    variable: str = Field(..., description="Weather variable: rain_mm, tmax_c, wind_max_kmh")
    window_days: int = Field(default=60, ge=1, le=365, description="Evaluation window days (default 60)")
    region: Optional[str] = Field(None, description="Optional region filter")
    season: Optional[str] = Field(None, description="Optional season filter")


class GetAlertsArgs(BaseModel):
    """Arguments for get_alerts tool."""

    status: str = Field(default="active", description="Alert status: active, acknowledged, all")
    hazard: Optional[str] = Field(None, description="Hazard type: heavy_rain, heatwave, high_wind, heavy_rain_3day")
    region: Optional[str] = Field(None, description="Region code filter")
    min_severity: Optional[str] = Field(None, description="Minimum severity: advisory, watch, warning")
    max_lead_days: Optional[int] = Field(None, ge=0, le=7, description="Max lead days window")


class QueryHistoryArgs(BaseModel):
    """Arguments for query_history tool (cap 5,000 rows)."""

    location: str = Field(..., description="Location name or slug")
    variable: str = Field(..., description="Weather variable: rain_mm, tmax_c, wind_max_kmh")
    start: str = Field(..., description="Start date in ISO format YYYY-MM-DD")
    end: str = Field(..., description="End date in ISO format YYYY-MM-DD")
    kind: Literal["forecast", "observed", "blended"] = Field(
        ..., description="Data kind: forecast, observed, or blended"
    )
    models: Optional[List[str]] = Field(None, description="Optional model filter: gfs, ecmwf_ifs, icon, aifs")


class ExportDataArgs(BaseModel):
    """Arguments for export_data tool (generates 10-minute signed download URL)."""

    dataset: Literal["forecast", "history", "skill", "weights", "alerts"] = Field(
        ..., description="Dataset name to export"
    )
    filters: Dict[str, Any] = Field(default_factory=dict, description="Query filters for export")
    format: Literal["csv", "json"] = Field(default="csv", description="Output format: csv or json")


# ==============================================================================
# Chat Request / Response Schemas (PRD §9.8)
# ==============================================================================

class ChatContext(BaseModel):
    location: Optional[str] = None
    variable: Optional[str] = None


class ChatRequest(BaseModel):
    """SSE Chat Request Body per PRD §9.8."""

    message: str
    mode: Literal["explain", "raw", "both"] = "both"
    context: Optional[ChatContext] = None
    conversation_id: Optional[str] = None
