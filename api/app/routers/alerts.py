"""Alerts and Alert Events management and acknowledgement endpoints (PRD §12, Phase 10)."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from api.app.auth.dependencies import CurrentUser, require_role
from api.app.db.pool import get_db_conn, set_rls_claims
from api.app.services.hazard_guidance import get_hazard_guidance
from api.app.services.track_record import fetch_track_record
from core.config import settings
from core.schemas import (
    AlertAckResponse,
    AlertCancelResponse,
    AlertEventAckResponse,
    AlertEventCancelResponse,
    AlertEventDetailResponse,
    AlertEventItem,
    AlertItem,
    AlertListResponse,
    LifecycleEventNode,
    SeverityCounts,
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
    status_filter: Optional[str] = Query(None, alias="status", description="Alert status: active, acknowledged, cancelled, expired, all"),
    hazard: Optional[str] = Query(None, description="Hazard type: heavy_rain, heatwave, high_wind, high_uncertainty, heavy_rain_3day"),
    region: Optional[str] = Query(None, description="Region filter"),
    severity: Optional[str] = Query(None, description="Exact severity filter: advisory, watch, alert"),
    min_severity: Optional[str] = Query(None, description="Minimum severity filter: advisory, watch, alert"),
    search: Optional[str] = Query(None, description="Search term for station name, region, or slug"),
    max_lead_days: Optional[int] = Query(None, ge=0, le=7, description="Maximum lead days filter (0-7)"),
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

    # Validate exact severity if provided (Task 1)
    if severity and severity.lower() not in {"advisory", "watch", "alert"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_SEVERITY",
                "message": f"Invalid severity '{severity}'. Must be one of: ['advisory', 'watch', 'alert']",
                "retry_after": None,
            },
        )

    # Validate min_severity if provided
    if min_severity and min_severity.lower() not in SEVERITY_LEVELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_SEVERITY",
                "message": f"Invalid min_severity '{min_severity}'. Must be one of: {sorted(list(SEVERITY_LEVELS.keys()))}",
                "retry_after": None,
            },
        )

    where_clauses = ["true"]
    params: List[Any] = []
    idx = 1

    # Apply window filtering on event date range
    if selected_window == "upcoming_2d":
        where_clauses.append("cand.end_date >= CURRENT_DATE AND cand.start_date <= CURRENT_DATE + INTERVAL '2 days'")
    elif selected_window == "upcoming_3d":
        where_clauses.append("cand.end_date >= CURRENT_DATE AND cand.start_date <= CURRENT_DATE + INTERVAL '3 days'")
    elif selected_window == "upcoming_7d":
        where_clauses.append("cand.end_date >= CURRENT_DATE AND cand.start_date <= CURRENT_DATE + INTERVAL '7 days'")
    elif selected_window == "past_24h":
        where_clauses.append("cand.start_date < CURRENT_DATE AND cand.end_date >= CURRENT_DATE - INTERVAL '1 day'")
    elif selected_window == "past_7d":
        where_clauses.append("cand.start_date < CURRENT_DATE AND cand.end_date >= CURRENT_DATE - INTERVAL '7 days'")

    # Status filter (Task 5: Operational active excludes cancelled records)
    st = status_filter.lower().strip() if status_filter else None
    if st == "active" or (not st and selected_window.startswith("upcoming")):
        where_clauses.append("cand.status = 'active' AND (cand.lifecycle_state IS DISTINCT FROM 'cancelled' AND cand.status != 'cancelled')")
    elif st == "acknowledged":
        where_clauses.append("cand.status = 'acknowledged'")
    elif st == "cancelled":
        where_clauses.append("(cand.status = 'cancelled' OR cand.lifecycle_state = 'cancelled')")
    elif st == "expired":
        where_clauses.append("(cand.status = 'expired' OR (cand.valid_date < CURRENT_DATE AND cand.status = 'active'))")
    elif st == "all":
        pass  # All retained lifecycle states
    elif st:
        where_clauses.append(f"cand.status = ${idx}")
        params.append(st)
        idx += 1

    if hazard:
        where_clauses.append(f"cand.hazard = ${idx}")
        params.append(hazard.lower())
        idx += 1

    if region:
        where_clauses.append(f"cand.region = ${idx}")
        params.append(region.upper())
        idx += 1

    # Severity filtering: exact severity takes precedence over min_severity (Task 1)
    if severity and severity.lower() in ("advisory", "watch", "alert"):
        where_clauses.append(f"cand.severity = ${idx}")
        params.append(severity.lower())
        idx += 1
    elif min_severity and min_severity.lower() in SEVERITY_LEVELS:
        allowed_severities = SEVERITY_LEVELS[min_severity.lower()]
        where_clauses.append(f"cand.severity = ANY(${idx}::text[])")
        params.append(allowed_severities)
        idx += 1

    # Search filtering (Task 7): location name, region, slug
    if search and search.strip():
        where_clauses.append(f"(cand.location_name ILIKE ${idx} OR cand.region ILIKE ${idx} OR cand.location_slug ILIKE ${idx})")
        params.append(f"%{search.strip()}%")
        idx += 1

    # Edge case: max_lead_days can be 0, do not use truthiness
    if max_lead_days is not None:
        where_clauses.append(f"cand.lead_days <= ${idx}")
        params.append(max_lead_days)
        idx += 1

    where_sql = " AND ".join(where_clauses)

    query = f"""
        WITH event_candidates AS (
            -- Stream 1: Distinct alert_events with representative child alert
            SELECT
                e.id as event_id,
                COALESCE(a.id, e.id) as id,
                COALESCE(a.created_at, e.first_detected_at) as created_at,
                COALESCE(a.issue_time, e.last_updated_at) as issue_time,
                e.location_id,
                l.name as location_name,
                l.slug as location_slug,
                l.region,
                e.hazard,
                e.severity_peak as severity,
                COALESCE(a.valid_date, e.start_date) as valid_date,
                COALESCE(a.lead_days, GREATEST(0, (e.start_date - CURRENT_DATE))) as lead_days,
                COALESCE(e.value_peak, a.value) as value,
                COALESCE(a.models_over, 4) as models_over,
                COALESCE(a.spread, 0.0) as spread,
                COALESCE(a.rule, json_build_object('name', e.hazard, 'severity', e.severity_peak)::jsonb) as rule,
                CASE
                    WHEN e.status = 'cancelled' OR a.lifecycle_state = 'cancelled' OR a.status = 'cancelled' THEN 'cancelled'
                    WHEN a.status = 'acknowledged' THEN 'acknowledged'
                    WHEN e.status = 'expired' OR a.status = 'expired' THEN 'expired'
                    ELSE e.status
                END as status,
                a.acknowledged_by,
                a.acknowledged_at,
                COALESCE(a.cancelled_by, e.cancelled_by) as cancelled_by,
                COALESCE(a.cancelled_at, e.cancelled_at) as cancelled_at,
                COALESCE(cp_a.display_name, cp_e.display_name) as cancelled_by_name,
                COALESCE(a.lifecycle_state, CASE WHEN e.status = 'cancelled' THEN 'cancelled' ELSE 'new' END) as lifecycle_state,
                a.previous_severity,
                a.rarity_label,
                e.start_date as start_date,
                e.end_date as end_date
            FROM alert_events e
            JOIN locations l ON e.location_id = l.id
            LEFT JOIN profiles cp_e ON e.cancelled_by = cp_e.user_id
            LEFT JOIN LATERAL (
                SELECT a_sub.*
                FROM alerts a_sub
                WHERE a_sub.event_id = e.id
                ORDER BY
                    a_sub.issue_time DESC,
                    CASE a_sub.severity WHEN 'alert' THEN 3 WHEN 'watch' THEN 2 WHEN 'advisory' THEN 1 ELSE 0 END DESC,
                    a_sub.valid_date ASC,
                    a_sub.lead_days ASC
                LIMIT 1
            ) a ON true
            LEFT JOIN profiles cp_a ON a.cancelled_by = cp_a.user_id

            UNION ALL

            -- Stream 2: Standalone alerts where event_id IS NULL (e.g. ad-hoc test alerts)
            SELECT
                NULL as event_id,
                a_stand.id,
                a_stand.created_at,
                a_stand.issue_time,
                a_stand.location_id,
                l.name as location_name,
                l.slug as location_slug,
                l.region,
                a_stand.hazard,
                a_stand.severity,
                a_stand.valid_date,
                a_stand.lead_days,
                a_stand.value,
                COALESCE(a_stand.models_over, 4) as models_over,
                COALESCE(a_stand.spread, 0.0) as spread,
                COALESCE(a_stand.rule, json_build_object('name', a_stand.hazard, 'severity', a_stand.severity)::jsonb) as rule,
                CASE
                    WHEN a_stand.lifecycle_state = 'cancelled' OR a_stand.status = 'cancelled' THEN 'cancelled'
                    WHEN a_stand.status = 'acknowledged' THEN 'acknowledged'
                    WHEN a_stand.status = 'expired' THEN 'expired'
                    ELSE a_stand.status
                END as status,
                a_stand.acknowledged_by,
                a_stand.acknowledged_at,
                a_stand.cancelled_by,
                a_stand.cancelled_at,
                cp.display_name as cancelled_by_name,
                COALESCE(a_stand.lifecycle_state, 'new') as lifecycle_state,
                a_stand.previous_severity,
                a_stand.rarity_label,
                a_stand.valid_date as start_date,
                a_stand.valid_date as end_date
            FROM (
                SELECT DISTINCT ON (location_id, hazard, valid_date) a.*
                FROM alerts a
                WHERE a.event_id IS NULL
                ORDER BY location_id, hazard, valid_date, issue_time DESC, id DESC
            ) a_stand
            JOIN locations l ON a_stand.location_id = l.id
            LEFT JOIN profiles cp ON a_stand.cancelled_by = cp.user_id
        ),
        filtered AS (
            SELECT *
            FROM event_candidates cand
            WHERE {where_sql}
        ),
        counts AS (
            SELECT
                COUNT(*)::int as total_count,
                COUNT(*) FILTER (WHERE severity = 'advisory')::int as advisory_count,
                COUNT(*) FILTER (WHERE severity = 'watch')::int as watch_count,
                COUNT(*) FILTER (WHERE severity = 'alert')::int as alert_count
            FROM filtered
        )
        SELECT f.*, c.total_count, c.advisory_count, c.watch_count, c.alert_count
        FROM counts c
        LEFT JOIN LATERAL (
            SELECT *
            FROM filtered
            ORDER BY
                valid_date ASC,
                lead_days ASC,
                issue_time DESC,
                CASE severity WHEN 'alert' THEN 3 WHEN 'watch' THEN 2 WHEN 'advisory' THEN 1 ELSE 0 END DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        ) f ON true;
    """
    params.extend([limit, offset])

    rows = await conn.fetch(query, *params)

    items: List[AlertItem] = []
    total_count = 0
    advisory_count = 0
    watch_count = 0
    alert_count = 0

    if rows:
        first = rows[0]
        total_count = first["total_count"] or 0
        advisory_count = first["advisory_count"] or 0
        watch_count = first["watch_count"] or 0
        alert_count = first["alert_count"] or 0

        for r in rows:
            # If 0 matching items, LEFT JOIN LATERAL produced a null row
            if r["id"] is None:
                continue

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
                    cancelled_by=str(r.get("cancelled_by")) if r.get("cancelled_by") else None,
                    cancelled_at=r.get("cancelled_at").isoformat() if r.get("cancelled_at") else None,
                    cancelled_by_name=r.get("cancelled_by_name"),
                    event_id=r["event_id"],
                    lifecycle_state=r["lifecycle_state"],
                    previous_severity=r["previous_severity"],
                    rarity_label=r["rarity_label"],
                )
            )

    return AlertListResponse(
        count=total_count,
        severity_counts=SeverityCounts(
            advisory=advisory_count,
            watch=watch_count,
            alert=alert_count,
        ),
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
               e.first_detected_at, e.last_updated_at, e.outcome, e.verified_at,
               e.cancelled_by, e.cancelled_at, cp.display_name as cancelled_by_name
        FROM alert_events e
        JOIN locations l ON e.location_id = l.id
        LEFT JOIN profiles cp ON e.cancelled_by = cp.user_id
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
        cancelled_by=str(event_row.get("cancelled_by")) if event_row.get("cancelled_by") else None,
        cancelled_at=event_row.get("cancelled_at").isoformat() if event_row.get("cancelled_at") else None,
        cancelled_by_name=event_row.get("cancelled_by_name"),
    )

    # Fetch child alerts
    alert_rows = await conn.fetch(
        """
        SELECT a.id, a.created_at, a.issue_time, a.location_id, l.name as location_name,
               l.slug as location_slug, l.region, a.hazard, a.severity, a.valid_date,
               a.lead_days, a.value, a.models_over, a.spread, a.rule, a.status,
               a.acknowledged_by, a.acknowledged_at, a.cancelled_by, a.cancelled_at,
               cp.display_name as cancelled_by_name,
               a.event_id, a.lifecycle_state,
               a.previous_severity, a.rarity_label
        FROM alerts a
        JOIN locations l ON a.location_id = l.id
        LEFT JOIN profiles cp ON a.cancelled_by = cp.user_id
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
            cancelled_by=str(r.get("cancelled_by")) if r.get("cancelled_by") else None,
            cancelled_at=r.get("cancelled_at").isoformat() if r.get("cancelled_at") else None,
            cancelled_by_name=r.get("cancelled_by_name"),
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

    # 1. Feature C: Static team-authored "What this means" hazard guidance
    guidance = get_hazard_guidance(event_item.hazard, event_item.severity_peak)

    # 2. Feature A: Trailing 180-day verification track record
    track_record = await fetch_track_record(
        conn=conn,
        hazard=event_item.hazard,
        region=event_item.region or "ALL",
        severity=event_item.severity_peak,
        window_days=180,
    )

    # 3. Feature F: Public Share Text formatted strictly per PRD §10.4 FR-UI-5
    headline_val = ""
    if event_item.value_peak is not None:
        if event_item.hazard in ("heavy_rain", "heavy_rain_3day"):
            headline_val = f"up to {event_item.value_peak}mm rain expected"
        elif event_item.hazard == "heatwave":
            headline_val = f"up to {event_item.value_peak}°C expected"
        elif event_item.hazard == "high_wind":
            headline_val = f"gusts up to {event_item.value_peak} km/h expected"
        else:
            headline_val = f"peak value {event_item.value_peak} expected"
    else:
        headline_val = "extreme weather conditions expected"

    max_models = max([a.models_over for a in alerts if a.models_over is not None] or [0])
    agreement_str = f"{max_models} of 4 models agree" if max_models > 0 else "multi-model consensus"

    date_range_str = (
        event_item.start_date
        if event_item.start_date == event_item.end_date
        else f"{event_item.start_date} to {event_item.end_date}"
    )

    hazard_label = event_item.hazard.replace("_", " ").title()
    severity_label = event_item.severity_peak.upper()
    public_url = f"/alerts/e/{event_item.id}"

    share_text = (
        f"⚠️ {severity_label} — {hazard_label} for {event_item.location_name}\n"
        f"{date_range_str}: {headline_val} ({agreement_str})\n"
        f"Details: {public_url}\n"
        f"— via AAGAM (decision support, not an official IMD warning)"
    )

    # 4. Feature G: Climatology rarity context (PRD §10.4 FR-UI-5)
    rarity_candidates = [a.rarity_label for a in alerts if a.rarity_label]
    peak_rarity = None
    if "roughly a 1-in-100 event" in rarity_candidates:
        peak_rarity = "roughly a 1-in-100 event"
    elif "roughly a 1-in-20 event" in rarity_candidates:
        peak_rarity = "roughly a 1-in-20 event"
    elif "roughly a 1-in-10 event" in rarity_candidates:
        peak_rarity = "roughly a 1-in-10 event"

    rarity_context = None
    if peak_rarity and event_item.start_date:
        try:
            import datetime as _dt

            start_dt = _dt.date.fromisoformat(event_item.start_date.split("T")[0])
            month_name = start_dt.strftime("%B")
            rarity_context = f"Also unusual for {event_item.location_name} in {month_name} — {peak_rarity}"
        except Exception:
            rarity_context = f"Also unusual for {event_item.location_name} — {peak_rarity}"

    return AlertEventDetailResponse(
        event=event_item,
        alerts=alerts,
        lifecycle_history=lifecycle_history,
        guidance=guidance,
        track_record=track_record,
        share_text=share_text,
        rarity_label=peak_rarity,
        rarity_context=rarity_context,
    )


@router.get("/alerts/track-record")
async def get_track_record_endpoint(
    hazard: str = Query(..., description="Hazard type"),
    region: str = Query(..., description="Geographic region"),
    severity: str = Query(..., description="Severity peak"),
    window_days: int = Query(180, description="Trailing window in days (default 180)"),
    current_user: CurrentUser = Depends(require_role("public")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> Dict[str, Any]:
    """Evaluates trailing 180-day track record for given criteria (PRD §12.1)."""
    return await fetch_track_record(
        conn=conn,
        hazard=hazard,
        region=region,
        severity=severity,
        window_days=window_days,
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
        SET last_updated_at = NOW()
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


@router.post("/alerts/{id}/cancel", response_model=AlertCancelResponse)
@router.post("/alerts/{id}/disable", response_model=AlertCancelResponse)
async def cancel_alert(
    id: int = Path(..., description="Numeric ID of the alert to cancel"),
    current_user: CurrentUser = Depends(require_role("forecaster+")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> AlertCancelResponse:
    """Cancels an alert without physical deletion (role: forecaster+)."""
    alert_row = await conn.fetchrow("SELECT id, status, event_id FROM alerts WHERE id = $1", id)
    if not alert_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ALERT_NOT_FOUND", "message": f"Alert with id {id} not found."},
        )

    await set_rls_claims(conn, current_user.user_id, role="authenticated")
    updated = await conn.fetchrow(
        """
        UPDATE alerts
        SET status = 'cancelled',
            lifecycle_state = 'cancelled',
            cancelled_by = $1::uuid,
            cancelled_at = NOW()
        WHERE id = $2
        RETURNING id, status, cancelled_by, cancelled_at;
        """,
        current_user.user_id,
        id,
    )

    p_row = await conn.fetchrow("SELECT display_name FROM profiles WHERE user_id = $1::uuid", current_user.user_id)
    disp_name = p_row["display_name"] if p_row and p_row["display_name"] else "Forecaster"

    logger.info(f"Forecaster {current_user.user_id} cancelled alert #{id}")
    return AlertCancelResponse(
        id=updated["id"],
        status=updated["status"],
        cancelled_by=str(updated["cancelled_by"]),
        cancelled_at=updated["cancelled_at"].isoformat(),
        cancelled_by_name=disp_name,
    )


@router.post("/alerts/events/{id}/cancel", response_model=AlertEventCancelResponse)
@router.post("/alerts/events/{id}/disable", response_model=AlertEventCancelResponse)
async def cancel_alert_event(
    id: int = Path(..., description="Numeric ID of the alert event to cancel"),
    current_user: CurrentUser = Depends(require_role("forecaster+")),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> AlertEventCancelResponse:
    """Cancels an alert event and all child alerts without physical deletion (role: forecaster+)."""
    event_row = await conn.fetchrow("SELECT id, status FROM alert_events WHERE id = $1", id)
    if not event_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "EVENT_NOT_FOUND", "message": f"Alert event with id {id} not found."},
        )

    await set_rls_claims(conn, current_user.user_id, role="authenticated")
    async with conn.transaction():
        updated_evt = await conn.fetchrow(
            """
            UPDATE alert_events
            SET status = 'cancelled',
                cancelled_by = $1::uuid,
                cancelled_at = NOW(),
                last_updated_at = NOW()
            WHERE id = $2
            RETURNING id, status, cancelled_by, cancelled_at;
            """,
            current_user.user_id,
            id,
        )

        await conn.execute(
            """
            UPDATE alerts
            SET status = 'cancelled',
                lifecycle_state = 'cancelled',
                cancelled_by = $1::uuid,
                cancelled_at = NOW()
            WHERE event_id = $2;
            """,
            current_user.user_id,
            id,
        )

    p_row = await conn.fetchrow("SELECT display_name FROM profiles WHERE user_id = $1::uuid", current_user.user_id)
    disp_name = p_row["display_name"] if p_row and p_row["display_name"] else "Forecaster"

    logger.info(f"Forecaster {current_user.user_id} cancelled alert event #{id}")
    return AlertEventCancelResponse(
        id=updated_evt["id"],
        status=updated_evt["status"],
        lifecycle_state="cancelled",
        cancelled_by=str(updated_evt["cancelled_by"]),
        cancelled_at=updated_evt["cancelled_at"].isoformat(),
        cancelled_by_name=disp_name,
    )

