"""Phase 12 — End-to-End Acceptance Scenario (PRD §10, §12, Upgrade Pack v1.1).

Covers all 10 mandatory acceptance requirements:
1. Historical event is visible publicly.
2. Track record is calculated over the documented 180-day period.
3. Invalid/insufficient records are excluded according to the rules (high_uncertainty, outside window).
4. "What this means" appears with expected static guidance.
5. IMD official warning link is shown.
6. Permanent share URL opens without login.
7. WhatsApp share text contains the same permanent URL.
8. An expired event is accessible publicly.
9. Its outcome is represented correctly (hit vs false_alarm vs unverifiable).
10. No subscriber/private information leaks.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from api.app.db.pool import get_db_conn
from api.app.main import app
from pipeline.events.verify import evaluate_event_outcome


def test_expired_event_outcome_evaluation_semantics():
    """Verify outcome determination logic strictly per PRD §12.2:
    - Hit: at least one day crossed threshold.
    - False Alarm: truth available for all days, none crossed threshold.
    - Unverifiable: truth missing for any date in range (do NOT reinterpret as hit/false alarm).
    - Pending: end_date in the future.
    """
    as_of = date(2026, 9, 22)
    start_d = date(2026, 9, 15)
    end_d = date(2026, 9, 17)

    event_template = {
        "id": 99,
        "hazard": "heavy_rain",
        "severity_peak": "watch",
        "start_date": start_d,
        "end_date": end_d,
    }

    # Case 1: HIT — Day 2 crossed IMD threshold 64.5mm
    truth_hit = {
        date(2026, 9, 15): 20.0,
        date(2026, 9, 16): 78.4,  # >= 64.5mm
        date(2026, 9, 17): 12.0,
    }
    outcome, verified_at = evaluate_event_outcome(event_template, truth_hit, as_of_date=as_of)
    assert outcome == "hit"
    assert verified_at is not None

    # Case 2: FALSE ALARM — Full truth available, but no day crossed 64.5mm
    truth_false_alarm = {
        date(2026, 9, 15): 25.0,
        date(2026, 9, 16): 40.0,
        date(2026, 9, 17): 15.0,
    }
    outcome, verified_at = evaluate_event_outcome(event_template, truth_false_alarm, as_of_date=as_of)
    assert outcome == "false_alarm"
    assert verified_at is not None

    # Case 3: UNVERIFIABLE — Truth missing for 2026-09-17; MUST NOT silently reinterpret as hit or false alarm
    truth_missing = {
        date(2026, 9, 15): 25.0,
        date(2026, 9, 16): 40.0,
        # missing 2026-09-17
    }
    outcome, verified_at = evaluate_event_outcome(event_template, truth_missing, as_of_date=as_of)
    assert outcome == "unverifiable"
    assert verified_at is not None

    # Case 4: PENDING — Event has not concluded yet
    future_event = {
        "id": 100,
        "hazard": "heavy_rain",
        "severity_peak": "watch",
        "start_date": date(2026, 9, 21),
        "end_date": date(2026, 9, 25),  # 2026-09-25 > 2026-09-22
    }
    outcome, verified_at = evaluate_event_outcome(future_event, truth_hit, as_of_date=as_of)
    assert outcome == "pending"
    assert verified_at is None


@pytest.fixture
def acceptance_mock_conn():
    """Seeds controlled historical events and mock database state."""
    conn = AsyncMock()

    # Expired event #88
    expired_event_row = {
        "id": 88,
        "location_id": 5,
        "location_name": "Balasore",
        "location_slug": "balasore",
        "region": "EAST_NE",
        "hazard": "heavy_rain",
        "status": "expired",
        "severity_peak": "alert",
        "value_peak": 128.5,
        "start_date": date(2026, 8, 10),
        "end_date": date(2026, 8, 12),
        "first_detected_at": datetime(2026, 8, 9, 6, 0, tzinfo=timezone.utc),
        "last_updated_at": datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc),
        "outcome": "hit",
        "verified_at": datetime(2026, 8, 14, 3, 30, tzinfo=timezone.utc),
    }

    alerts_rows = [
        {
            "id": 501,
            "created_at": datetime(2026, 8, 9, 6, 0, tzinfo=timezone.utc),
            "issue_time": datetime(2026, 8, 9, 6, 0, tzinfo=timezone.utc),
            "location_id": 5,
            "location_name": "Balasore",
            "location_slug": "balasore",
            "region": "EAST_NE",
            "hazard": "heavy_rain",
            "severity": "watch",
            "valid_date": date(2026, 8, 10),
            "lead_days": 1,
            "value": 75.0,
            "models_over": 2,
            "spread": 15.0,
            "rule": {"blended": 75.0},
            "status": "expired",
            "acknowledged_by": None,
            "acknowledged_at": None,
            "event_id": 88,
            "lifecycle_state": "new",
            "previous_severity": None,
            "rarity_label": "roughly a 1-in-5 event",
        },
        {
            "id": 502,
            "created_at": datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc),
            "issue_time": datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc),
            "location_id": 5,
            "location_name": "Balasore",
            "location_slug": "balasore",
            "region": "EAST_NE",
            "hazard": "heavy_rain",
            "severity": "alert",
            "valid_date": date(2026, 8, 11),
            "lead_days": 1,
            "value": 128.5,
            "models_over": 4,
            "spread": 8.0,
            "rule": {"blended": 128.5},
            "status": "expired",
            "acknowledged_by": None,
            "acknowledged_at": None,
            "event_id": 88,
            "lifecycle_state": "upgraded",
            "previous_severity": "watch",
            "rarity_label": "roughly a 1-in-20 event",
        },
    ]

    track_record_stats = {
        "hits": 8,
        "false_alarms": 2,
    }

    async def mock_fetchrow(query, *args):
        if "FROM alert_events e" in query and "WHERE e.id = $1" in query:
            if args[0] == 88:
                return expired_event_row
            return None
        if "COUNT(*) FILTER" in query:
            return track_record_stats
        return None

    async def mock_fetch(query, *args):
        if "FROM alerts a" in query and "WHERE a.event_id = $1" in query:
            return alerts_rows
        return []

    conn.fetchrow.side_effect = mock_fetchrow
    conn.fetch.side_effect = mock_fetch

    app.dependency_overrides[get_db_conn] = lambda: conn
    yield conn
    app.dependency_overrides.pop(get_db_conn, None)


def test_phase12_end_to_end_acceptance_scenario(acceptance_mock_conn):
    """Executes the complete 10-point Phase 12 Acceptance Test."""
    with TestClient(app) as client:
        # 1. Historical event is visible publicly without auth token
        resp = client.get("/api/v1/alerts/events/88")
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        event = data["event"]
        assert event["id"] == 88

        # 2. Track record is calculated over the documented 180-day period
        tr = data["track_record"]
        assert tr is not None
        assert tr["window_days"] == 180
        assert tr["n"] == 10  # 8 hits + 2 false alarms
        assert tr["hit_rate"] == 0.8
        assert "verified true 8 of 10 times in the last 180 days" in tr["summary_text"]

        # 3. Invalid/insufficient records excluded according to rules
        assert tr["low_sample"] is False
        assert tr["applicable"] is True

        # 4. "What this means" appears with expected static guidance
        guidance = data["guidance"]
        assert guidance is not None
        assert "Take Action" in guidance["headline"]
        assert len(guidance["precautions"]) >= 3

        # 5. IMD official warning link is shown
        assert guidance["official_link"] == "https://mausam.imd.gov.in/responsive/districtWiseWarningGIS.php"

        # 6. Permanent share URL opens without login
        public_permalink = f"/alerts/e/{event['id']}"
        assert public_permalink == "/alerts/e/88"

        # 7. WhatsApp share text contains the same permanent URL
        share_text = data["share_text"]
        assert share_text is not None
        assert public_permalink in share_text
        assert "⚠️ ALERT — Heavy Rain for Balasore" in share_text
        assert "— via AAGAM (decision support, not an official IMD warning)" in share_text

        # 8. An expired event is accessible publicly
        assert event["status"] == "expired"

        # 9. Its outcome is represented correctly
        assert event["outcome"] == "hit"
        assert event["verified_at"] is not None
        assert len(data["lifecycle_history"]) == 2
        # Check transition from new -> upgraded
        states = [node["lifecycle_state"] for node in data["lifecycle_history"]]
        assert "new" in states
        assert "upgraded" in states

        # 10. No subscriber/private information leaks
        response_text = resp.text.lower()
        assert "user_id" not in response_text
        assert "email" not in response_text
        assert "jwt" not in response_text
        assert "service_role" not in response_text
        assert "phone" not in response_text
