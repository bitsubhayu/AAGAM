"""Phase 10 Mandatory Acceptance Test.

Authoritative specification: Phase 10 Scope Item 9.

Acceptance Scenario:
- Run TWO CONSECUTIVE manual pipeline cycles against a seeded scenario.
- Expected result:
  - exactly ONE alert_event
  - first cycle lifecycle_state = 'new'
  - second cycle lifecycle_state = 'upgraded'
  - both alert rows reference the same event_id
  - event is visible through public API: GET /api/v1/alerts/events/{id}
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Optional

import psycopg2
import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from core.config import settings
from pipeline.events.group import AlertEventRecord, group_alerts_into_events
from pipeline.events.lifecycle_state import (
    compute_lifecycle_states,
)


@dataclass
class AlertStub:
    location_id: int
    hazard: str
    severity: str
    valid_date: dt.date
    lead_days: int
    value: float
    agreement: int
    spread: float
    rule: dict
    status: str = "active"
    event_id: Optional[int] = None
    lifecycle_state: str = "new"
    previous_severity: Optional[str] = None


def get_db_conn():
    return psycopg2.connect(settings.DATABASE_URL)


@pytest.fixture
def api_client():
    with TestClient(app) as client:
        yield client


def test_two_consecutive_pipeline_cycles_acceptance(api_client):
    """Executes the mandatory two-cycle seeded acceptance test."""
    conn = get_db_conn()
    conn.autocommit = False

    test_location_id = 40
    test_hazard = "heavy_rain"
    today = dt.date.today()
    target_valid_date = today + dt.timedelta(days=2)

    created_event_ids = []
    created_alert_ids = []

    try:
        # Pre-cleanup in case of prior aborted tests
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM alerts
                WHERE location_id = %s AND hazard = %s AND valid_date = %s;
                """,
                (test_location_id, test_hazard, target_valid_date),
            )
            cur.execute(
                """
                DELETE FROM alert_events
                WHERE location_id = %s AND hazard = %s AND start_date = %s;
                """,
                (test_location_id, test_hazard, target_valid_date),
            )
            conn.commit()

        # ======================================================================
        # CYCLE 1: Newly Flagged Watch
        # ======================================================================
        cycle1_time = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=6)
        cycle1_alert = AlertStub(
            location_id=test_location_id,
            hazard=test_hazard,
            severity="watch",
            valid_date=target_valid_date,
            lead_days=2,
            value=75.0,
            agreement=0.75,
            spread=12.0,
            rule={"trigger": "acceptance_cycle_1_watch", "threshold": 64.5},
            status="active",
        )

        with conn.cursor() as cur:
            # 1. Fetch active events
            cur.execute(
                """
                SELECT id, location_id, hazard, status, severity_peak, value_peak,
                       start_date, end_date, first_detected_at, last_updated_at, outcome
                FROM alert_events
                WHERE status = 'active' AND location_id = %s AND hazard = %s;
                """,
                (test_location_id, test_hazard),
            )
            active_events = [
                AlertEventRecord(
                    id=r[0], location_id=r[1], hazard=r[2], status=r[3],
                    severity_peak=r[4], value_peak=r[5], start_date=r[6], end_date=r[7],
                    first_detected_at=r[8], last_updated_at=r[9], outcome=r[10],
                )
                for r in cur.fetchall()
            ]

            # 2. Fetch previous cycle alerts
            cur.execute(
                """
                SELECT id, location_id, hazard, severity, valid_date, lead_days, value, event_id
                FROM alerts
                WHERE location_id = %s AND hazard = %s
                ORDER BY issue_time DESC LIMIT 10;
                """,
                (test_location_id, test_hazard),
            )
            previous_alerts = [
                {
                    "id": r[0], "location_id": r[1], "hazard": r[2],
                    "severity": r[3], "valid_date": r[4], "lead_days": r[5],
                    "value": r[6], "event_id": r[7],
                }
                for r in cur.fetchall()
            ]

            # 3. Compute lifecycle states
            compute_lifecycle_states([cycle1_alert], previous_alerts)

            # 4. Group into events
            grouped_alerts_1, updated_events_1 = group_alerts_into_events(
                [cycle1_alert], active_events, now=cycle1_time
            )

            # 5. Persist event
            for evt in updated_events_1:
                if evt.id is None or evt.id < 0:
                    cur.execute(
                        """
                        INSERT INTO alert_events (
                            location_id, hazard, status, severity_peak, value_peak,
                            start_date, end_date, first_detected_at, last_updated_at, outcome
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                        """,
                        (
                            evt.location_id, evt.hazard, evt.status, evt.severity_peak, evt.value_peak,
                            evt.start_date, evt.end_date, evt.first_detected_at, evt.last_updated_at, evt.outcome,
                        ),
                    )
                    evt_id = cur.fetchone()[0]
                    evt.id = evt_id
                    created_event_ids.append(evt_id)
                    for a in grouped_alerts_1:
                        a.event_id = evt_id

            # 6. Persist alert
            cur.execute(
                """
                INSERT INTO alerts (
                    issue_time, location_id, hazard, severity, valid_date, lead_days,
                    value, models_over, spread, rule, status, event_id, lifecycle_state, previous_severity
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    cycle1_time,
                    cycle1_alert.location_id,
                    cycle1_alert.hazard,
                    cycle1_alert.severity,
                    cycle1_alert.valid_date,
                    cycle1_alert.lead_days,
                    cycle1_alert.value,
                    cycle1_alert.agreement,
                    cycle1_alert.spread,
                    json.dumps(cycle1_alert.rule),
                    cycle1_alert.status,
                    cycle1_alert.event_id,
                    cycle1_alert.lifecycle_state,
                    cycle1_alert.previous_severity,
                ),
            )
            created_alert_ids.append(cur.fetchone()[0])
            conn.commit()

        # Verify Cycle 1
        assert cycle1_alert.lifecycle_state == "new", f"Expected lifecycle_state='new', got {cycle1_alert.lifecycle_state}"
        assert cycle1_alert.previous_severity is None
        assert cycle1_alert.event_id is not None
        first_event_id = cycle1_alert.event_id

        # Check DB for Cycle 1
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, status, severity_peak, value_peak
                FROM alert_events
                WHERE location_id = %s AND hazard = %s AND status = 'active';
                """,
                (test_location_id, test_hazard),
            )
            rows = cur.fetchall()
            assert len(rows) == 1, f"Expected exactly 1 alert_event in Cycle 1, found {len(rows)}"
            assert rows[0][0] == first_event_id
            assert rows[0][1] == "active"
            assert rows[0][2] == "watch"
            assert rows[0][3] == 75.0

        # ======================================================================
        # CYCLE 2: Upgraded to Alert (Same Location, Hazard, Valid Date)
        # ======================================================================
        cycle2_time = dt.datetime.now(dt.timezone.utc)
        cycle2_alert = AlertStub(
            location_id=test_location_id,
            hazard=test_hazard,
            severity="alert",  # Upgraded
            valid_date=target_valid_date,
            lead_days=2,
            value=125.0,  # Peak value increased
            agreement=0.90,
            spread=15.0,
            rule={"trigger": "acceptance_cycle_2_alert", "threshold": 115.5},
            status="active",
        )

        with conn.cursor() as cur:
            # 1. Fetch active events
            cur.execute(
                """
                SELECT id, location_id, hazard, status, severity_peak, value_peak,
                       start_date, end_date, first_detected_at, last_updated_at, outcome
                FROM alert_events
                WHERE status = 'active' AND location_id = %s AND hazard = %s;
                """,
                (test_location_id, test_hazard),
            )
            active_events = [
                AlertEventRecord(
                    id=r[0], location_id=r[1], hazard=r[2], status=r[3],
                    severity_peak=r[4], value_peak=r[5], start_date=r[6], end_date=r[7],
                    first_detected_at=r[8], last_updated_at=r[9], outcome=r[10],
                )
                for r in cur.fetchall()
            ]

            # 2. Fetch immediately previous cycle alerts (Cycle 1)
            cur.execute(
                """
                SELECT id, location_id, hazard, severity, valid_date, lead_days, value, event_id
                FROM alerts
                WHERE location_id = %s AND hazard = %s AND issue_time = %s;
                """,
                (test_location_id, test_hazard, cycle1_time),
            )
            previous_alerts = [
                {
                    "id": r[0], "location_id": r[1], "hazard": r[2],
                    "severity": r[3], "valid_date": r[4], "lead_days": r[5],
                    "value": r[6], "event_id": r[7],
                }
                for r in cur.fetchall()
            ]

            # 3. Compute lifecycle states
            compute_lifecycle_states([cycle2_alert], previous_alerts)

            # 4. Group into events
            grouped_alerts_2, updated_events_2 = group_alerts_into_events(
                [cycle2_alert], active_events, now=cycle2_time
            )

            # 5. Persist event updates
            for evt in updated_events_2:
                if evt.id is not None and evt.id > 0:
                    cur.execute(
                        """
                        UPDATE alert_events
                        SET start_date = %s, end_date = %s, severity_peak = %s, value_peak = %s,
                            status = %s, last_updated_at = %s
                        WHERE id = %s;
                        """,
                        (
                            evt.start_date, evt.end_date, evt.severity_peak, evt.value_peak,
                            evt.status, evt.last_updated_at, evt.id,
                        ),
                    )

            # 6. Persist alert
            cur.execute(
                """
                INSERT INTO alerts (
                    issue_time, location_id, hazard, severity, valid_date, lead_days,
                    value, models_over, spread, rule, status, event_id, lifecycle_state, previous_severity
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    cycle2_time,
                    cycle2_alert.location_id,
                    cycle2_alert.hazard,
                    cycle2_alert.severity,
                    cycle2_alert.valid_date,
                    cycle2_alert.lead_days,
                    cycle2_alert.value,
                    cycle2_alert.agreement,
                    cycle2_alert.spread,
                    json.dumps(cycle2_alert.rule),
                    cycle2_alert.status,
                    cycle2_alert.event_id,
                    cycle2_alert.lifecycle_state,
                    cycle2_alert.previous_severity,
                ),
            )
            created_alert_ids.append(cur.fetchone()[0])
            conn.commit()

        # ======================================================================
        # MANDATORY ACCEPTANCE CRITERIA VERIFICATION
        # ======================================================================
        # 1. Exactly ONE alert_event exists
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, status, severity_peak, value_peak
                FROM alert_events
                WHERE location_id = %s AND hazard = %s AND status = 'active';
                """,
                (test_location_id, test_hazard),
            )
            events = cur.fetchall()
            assert len(events) == 1, f"Expected exactly 1 alert_event, found {len(events)}"
            assert events[0][0] == first_event_id, "Event ID changed between cycles"
            assert events[0][2] == "alert", f"Expected updated peak 'alert', got {events[0][2]}"
            assert events[0][3] == 125.0, f"Expected updated peak value 125.0, got {events[0][3]}"

        # 2. First cycle lifecycle_state = 'new'
        # 3. Second cycle lifecycle_state = 'upgraded'
        # 4. Both alert rows reference the same event_id
        assert cycle1_alert.lifecycle_state == "new"
        assert cycle2_alert.lifecycle_state == "upgraded"
        assert cycle2_alert.previous_severity == "watch"
        assert cycle1_alert.event_id == first_event_id
        assert cycle2_alert.event_id == first_event_id

        # 5. Event is visible through public API: GET /api/v1/alerts/events/{id}
        resp = api_client.get(f"/api/v1/alerts/events/{first_event_id}")
        assert resp.status_code == 200, f"API endpoint returned {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "event" in data
        assert data["event"]["id"] == first_event_id
        assert data["event"]["location_id"] == test_location_id
        assert data["event"]["hazard"] == test_hazard
        assert data["event"]["severity_peak"] == "alert"
        assert data["event"]["value_peak"] == 125.0
        assert data["event"]["status"] == "active"
        assert "lifecycle_history" in data
        assert len(data["lifecycle_history"]) >= 2
        assert "alerts" in data
        assert len(data["alerts"]) >= 2
        assert data["alerts"][0]["rule"] is not None

    finally:
        # Cleanup seeded records
        with conn.cursor() as cur:
            if created_alert_ids:
                cur.execute("DELETE FROM alerts WHERE id = ANY(%s::bigint[]);", (created_alert_ids,))
            if created_event_ids:
                cur.execute("DELETE FROM alert_events WHERE id = ANY(%s::bigint[]);", (created_event_ids,))
            conn.commit()
        conn.close()
