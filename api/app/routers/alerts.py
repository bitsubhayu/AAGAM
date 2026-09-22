"""Alerts and Alert Events management and acknowledgement endpoints (PRD §12, Phase 10)."""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn, set_rls_claims
from core.config import settings
from core.schemas import (
    AlertAckResponse,
    AlertEventAckResponse,
    AlertEventDetailResponse,
    AlertEventItem,
    AlertItem,
    AlertListResponse,
    LifecycleEventNode,
)

logger = logging.getLogger("aagam.api.alerts")
router = APIRouter(prefix=settings.API_V1_STR, tags=["Alerts"])

SEVERITY_LEVELS = {
    "advisory": ["advisory", "watch", "alert"],
    "watch": ["watch", "alert"],
    "alert": ["alert"],
}

VALID_WINDOWS = {
    "upcoming_2d",
    "upcoming_3d",
    "upcoming_7d",
    "past_24h",
    "past_7d",
}


@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    window: Optional[str] = Query("upcoming_7d", description="Alert window: upcoming_2d, upcoming_3d, upcoming_7d, past_24h, past_7d"),
    status_filter: Optional[str] = Query(None, alias="status", description="Alert status: active, acknowledged, expired, all"),
    hazard: Optional[str] = Query(None, description="Hazard type: heavy_rain, heatwave, high_wind, high_uncertainty, heavy_rain_3day"),
    region: Optional[str] = Query(None, description="Region filter"),
    min_severity: Optional[str] = Query(None, description="Minimum severity filter: advisory, watch, alert"),
    max_lead_days: Optional[int] = Query(None, ge=1, le=8, description="Maximum lead days filter (1-8)"),
    limit: int = Query(50, ge=1, le=200, description="Max alerts to return (1-200)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> AlertListResponse:
    """Lists extreme weather hazard alerts with filtering, lifecycle, and rule explanations (PRD §12, role: public)."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=30"

    # Validate window if provided
    selected_window = (window or "upcoming_7d").lower()
    if selected_window not in VALID_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_WINDOW",
                "message": f"Invalid window '{window}'. Must be one of: {sorted(list(VALID_WINDOWS))}",
                "retry_after": None,
            },
        )

    query = """
        SELECT a.id, a.created_at, a.issue_time, a.location_id, l.name as location_name,
               l.slug as location_slug, l.region, a.hazard, a.severity, a.valid_date,
               a.lead_days, a.value, a.models_over, a.spread, a.rule, a.status,
               a.acknowledged_by, a.acknowledged_at, a.event_id, a.lifecycle_state,
               a.previous_severity, a.rarity_label
        FROM alerts a
        JOIN locations l ON a.location_id = l.id
        WHERE true
    """
    params: List[Any] = []
    idx = 1

    # Apply window filtering
    if selected_window == "upcoming_2d":
        query += " AND a.valid_date >= CURRENT_DATE AND a.valid_date <= CURRENT_DATE + INTERVAL '2 days'"
    elif selected_window == "upcoming_3d":
        query += " AND a.valid_date >= CURRENT_DATE AND a.valid_date <= CURRENT_DATE + INTERVAL '3 days'"
    elif selected_window == "upcoming_7d":
        query += " AND a.valid_date >= CURRENT_DATE AND a.valid_date <= CURRENT_DATE + INTERVAL '7 days'"
    elif selected_window == "past_24h":
        query += " AND a.valid_date < CURRENT_DATE AND a.valid_date >= CURRENT_DATE - INTERVAL '1 day'"
    elif selected_window == "past_7d":
        query += " AND a.valid_date < CURRENT_DATE AND a.valid_date >= CURRENT_DATE - INTERVAL '7 days'"

    # Status filter
    if status_filter and status_filter.lower() != "all":
        query += f" AND a.status = ${idx}"
        params.append(status_filter.lower())
        idx += 1
    elif not status_filter and selected_window.startswith("upcoming"):
        query += f" AND a.status = ${idx}"
        params.append("active")
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

        # For past windows, ensure past active rows display as expired
        alert_status = r["status"]
        if selected_window.startswith("past") and alert_status == "active":
            alert_status = "expired"

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
                status=alert_status,
                acknowledged_by=str(r["acknowledged_by"]) if r["acknowledged_by"] else None,
                acknowledged_at=r["acknowledged_at"].isoformat() if r["acknowledged_at"] else None,
                event_id=r["event_id"],
                lifecycle_state=r["lifecycle_state"],
                previous_severity=r["previous_severity"],
                rarity_label=r["rarity_label"],
            )
        )

    return AlertListResponse(
        count=len(items),
        alerts=items,
    )


@router.get("/alerts/events/{id}", response_model=AlertEventDetailResponse)
async def get_alert_event(
    id: int = Path(..., description="Numeric ID of the alert event"),
    response: Response = None,
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> AlertEventDetailResponse:
    """Public detail page data for one alert event (PRD §12, role: public)."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=30"

    event_row = await conn.fetchrow(
        """
        SELECT e.id, e.location_id, l.name as location_name, l.slug as location_slug, l.region,
               e.hazard, e.status, e.severity_peak, e.value_peak, e.start_date, e.end_date,
               e.first_detected_at, e.last_updated_at, e.outcome, e.verified_at
        FROM alert_events e
        JOIN locations l ON e.location_id = l.id
        WHERE e.id = $1;
        """,
        id,
    )

    if not event_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "EVENT_NOT_FOUND",
                "message": f"Alert event with id {id} not found.",
                "retry_after": None,
            },
        )

    event_item = AlertEventItem(
        id=event_row["id"],
        location_id=event_row["location_id"],
        location_name=event_row["location_name"],
        location_slug=event_row["location_slug"],
        region=event_row["region"],
        hazard=event_row["hazard"],
        status=event_row["status"],
        severity_peak=event_row["severity_peak"],
        value_peak=round(float(event_row["value_peak"]), 2) if event_row["value_peak"] is not None else None,
        start_date=event_row["start_date"].isoformat() if event_row["start_date"] else "",
        end_date=event_row["end_date"].isoformat() if event_row["end_date"] else "",
        first_detected_at=event_row["first_detected_at"].isoformat() if event_row["first_detected_at"] else "",
        last_updated_at=event_row["last_updated_at"].isoformat() if event_row["last_updated_at"] else "",
        outcome=event_row["outcome"],
        verified_at=event_row["verified_at"].isoformat() if event_row["verified_at"] else None,
    )

    # Fetch child alerts
    alert_rows = await conn.fetch(
        """
        SELECT a.id, a.created_at, a.issue_time, a.location_id, l.name as location_name,
               l.slug as location_slug, l.region, a.hazard, a.severity, a.valid_date,
               a.lead_days, a.value, a.models_over, a.spread, a.rule, a.status,
               a.acknowledged_by, a.acknowledged_at, a.event_id, a.lifecycle_state,
               a.previous_severity, a.rarity_label
        FROM alerts a
        JOIN locations l ON a.location_id = l.id
        WHERE a.event_id = $1
        ORDER BY a.valid_date ASC, a.issue_time DESC;
        """,
        id,
    )

    alerts: List[AlertItem] = []
    lifecycle_history: List[LifecycleEventNode] = []

    for r in alert_rows:
        rule_dict = r["rule"]
        if isinstance(rule_dict, str):
            try:
                rule_dict = json.loads(rule_dict)
            except Exception:
                rule_dict = {"raw": rule_dict}

        alert_obj = AlertItem(
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
            event_id=r["event_id"],
            lifecycle_state=r["lifecycle_state"],
            previous_severity=r["previous_severity"],
            rarity_label=r["rarity_label"],
        )
        alerts.append(alert_obj)

        if r["lifecycle_state"]:
            lifecycle_history.append(
                LifecycleEventNode(
                    issue_time=alert_obj.issue_time,
                    lifecycle_state=r["lifecycle_state"],
                    severity=r["severity"],
                    previous_severity=r["previous_severity"],
                    valid_date=alert_obj.valid_date,
                    value=alert_obj.value,
                )
            )

    return AlertEventDetailResponse(
        event=event_item,
        alerts=alerts,
        lifecycle_history=lifecycle_history,
        guidance=None,
        track_record=None,
        share_text=None,
    )


@router.post("/alerts/events/{id}/ack", response_model=AlertEventAckResponse)
async def acknowledge_alert_event(
    id: int = Path(..., description="Numeric ID of the alert event to acknowledge"),
    current_user: CurrentUser = Depends(require_role("forecaster+")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> AlertEventAckResponse:
    """Acknowledges an active alert event. (PRD §12, role: forecaster+)."""
    event_row = await conn.fetchrow("SELECT id, status FROM alert_events WHERE id = $1", id)
    if not event_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "EVENT_NOT_FOUND",
                "message": f"Alert event with id {id} not found.",
                "retry_after": None,
            },
        )

    await set_rls_claims(conn, current_user.user_id, role="authenticated")
    updated_evt = await conn.fetchrow(
        """
        UPDATE alert_events
        SET status = 'acknowledged',
            last_updated_at = NOW()
        WHERE id = $1
        RETURNING id, status, last_updated_at;
        """,
        id,
    )

    # Acknowledge all active child alerts associated with this event
    await conn.execute(
        """
        UPDATE alerts
        SET status = 'acknowledged',
            acknowledged_by = $1::uuid,
            acknowledged_at = NOW()
        WHERE event_id = $2 AND status = 'active';
        """,
        current_user.user_id,
        id,
    )

    return AlertEventAckResponse(
        id=updated_evt["id"],
        status=updated_evt["status"],
        acknowledged_by=str(current_user.user_id),
        acknowledged_at=updated_evt["last_updated_at"].isoformat(),
    )


@router.post("/alerts/{id}/ack", response_model=AlertAckResponse)
async def acknowledge_alert(
    id: int = Path(..., description="Numeric ID of the alert to acknowledge"),
    current_user: CurrentUser = Depends(require_role("forecaster+")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> AlertAckResponse:
    """Acknowledges an active alert. (PRD §12, role: forecaster+)."""
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
        RETURNING id, status, acknowledged_by, acknowledged_at;
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
