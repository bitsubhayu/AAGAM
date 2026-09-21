"""Alerts management and acknowledgement endpoints (PRD §12)."""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn, set_rls_claims
from core.config import settings
from core.schemas import AlertAckResponse, AlertItem, AlertListResponse

logger = logging.getLogger("aagam.api.alerts")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Alerts"])

SEVERITY_LEVELS = {
    "advisory": ["advisory", "watch", "alert"],
    "watch": ["watch", "alert"],
    "alert": ["alert"],
}


@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    status_filter: str = Query("active", alias="status", description="Alert status: active, acknowledged, expired, all"),
    hazard: Optional[str] = Query(None, description="Hazard type: heavy_rain, heatwave, high_wind, high_uncertainty"),
    region: Optional[str] = Query(None, description="Region filter"),
    min_severity: Optional[str] = Query(None, description="Minimum severity filter: advisory, watch, alert"),
    max_lead_days: Optional[int] = Query(None, ge=1, le=8, description="Maximum lead days filter (1-8)"),
    limit: int = Query(50, ge=1, le=200, description="Max alerts to return (1-200)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("any")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> AlertListResponse:
    """Lists extreme weather hazard alerts with filtering and rule explanations (PRD §12, role: any)."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=30"

    query = """
        SELECT a.id, a.created_at, a.issue_time, a.location_id, l.name as location_name,
               l.slug as location_slug, l.region, a.hazard, a.severity, a.valid_date,
               a.lead_days, a.value, a.models_over, a.spread, a.rule, a.status,
               a.acknowledged_by, a.acknowledged_at
        FROM alerts a
        JOIN locations l ON a.location_id = l.id
        WHERE true
    """
    params: List[Any] = []
    idx = 1

    if status_filter and status_filter.lower() != "all":
        query += f" AND a.status = ${idx}"
        params.append(status_filter.lower())
        idx += 1

    if hazard:
        query += f" AND a.hazard = ${idx}"
        params.append(hazard.lower())
        idx += 1

    if region:
        query += f" AND l.region = ${idx}"
        params.append(region.upper())
        idx += 1

    if min_severity and min_severity.lower() in SEVERITY_LEVELS:
        allowed_severities = SEVERITY_LEVELS[min_severity.lower()]
        query += f" AND a.severity = ANY(${idx}::text[])"
        params.append(allowed_severities)
        idx += 1

    if max_lead_days:
        query += f" AND a.lead_days <= ${idx}"
        params.append(max_lead_days)
        idx += 1

    query += f" ORDER BY a.issue_time DESC, a.valid_date ASC, a.severity DESC LIMIT ${idx} OFFSET ${idx + 1}"
    params.extend([limit, offset])

    rows = await conn.fetch(query, *params)

    items: List[AlertItem] = []
    for r in rows:
        rule_dict = r["rule"]
        if isinstance(rule_dict, str):
            try:
                rule_dict = json.loads(rule_dict)
            except Exception:
                rule_dict = {"raw": rule_dict}

        items.append(
            AlertItem(
                id=r["id"],
                created_at=r["created_at"].isoformat() if r["created_at"] else "",
                issue_time=r["issue_time"].isoformat() if r["issue_time"] else "",
                location_id=r["location_id"],
                location_name=r["location_name"],
                location_slug=r["location_slug"],
                region=r["region"],
                hazard=r["hazard"],
                severity=r["severity"],
                valid_date=r["valid_date"].isoformat() if r["valid_date"] else "",
                lead_days=r["lead_days"],
                value=round(float(r["value"]), 2) if r["value"] is not None else None,
                models_over=r["models_over"],
                spread=round(float(r["spread"]), 2) if r["spread"] is not None else None,
                rule=rule_dict,
                status=r["status"],
                acknowledged_by=str(r["acknowledged_by"]) if r["acknowledged_by"] else None,
                acknowledged_at=r["acknowledged_at"].isoformat() if r["acknowledged_at"] else None,
            )
        )

    return AlertListResponse(
        count=len(items),
        alerts=items,
    )


@router.post("/alerts/{id}/ack", response_model=AlertAckResponse)
async def acknowledge_alert(
    id: int = Path(..., description="Numeric ID of the alert to acknowledge"),
    current_user: CurrentUser = Depends(require_role("forecaster+")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> AlertAckResponse:
    """Acknowledges an active alert. (PRD §12, role: forecaster+)."""
    # Check alert existence
    alert_row = await conn.fetchrow("SELECT id, status FROM alerts WHERE id = $1", id)
    if not alert_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ALERT_NOT_FOUND",
                "message": f"Alert with id {id} not found.",
                "retry_after": None,
            },
        )

    await set_rls_claims(conn, current_user.user_id, role="authenticated")
    updated = await conn.fetchrow(
        """
        UPDATE alerts
        SET status = 'acknowledged',
            acknowledged_by = $1::uuid,
            acknowledged_at = NOW()
        WHERE id = $2
        RETURNING id, status, acknowledged_by, acknowledged_at
        """,
        current_user.user_id,
        id,
    )

    return AlertAckResponse(
        id=updated["id"],
        status=updated["status"],
        acknowledged_by=str(updated["acknowledged_by"]),
        acknowledged_at=updated["acknowledged_at"].isoformat(),
    )
