"""Phase 12 — Public Sharing & Authorization Boundary Tests (PRD §10.4, §12, Feature F).

Tests public sharing for alert events:
- Permanent event URL resolution.
- Unauthenticated / logged-out access succeeds without token.
- Pre-filled WhatsApp share text contains permanent URL and official disclaimer.
- Security boundary: no private subscriber data, emails, or operator tokens exposed.
- Operator actions remain role-gated.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from api.app.db.pool import get_db_conn
from api.app.main import app


@pytest.fixture
def mock_db_conn(monkeypatch):
    """Mock database connection for alert event detail and track record."""
    conn = AsyncMock()

    event_row = {
        "id": 42,
        "location_id": 1,
        "location_name": "Bhubaneswar",
        "location_slug": "bhubaneswar",
        "region": "EAST_NE",
        "hazard": "heavy_rain",
        "status": "active",
        "severity_peak": "watch",
        "value_peak": 95.0,
        "start_date": date(2026, 9, 23),
        "end_date": date(2026, 9, 24),
        "first_detected_at": datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc),
        "last_updated_at": datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc),
        "outcome": "pending",
        "verified_at": None,
    }

    alert_rows = [
        {
            "id": 101,
            "created_at": datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc),
            "issue_time": datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc),
            "location_id": 1,
            "location_name": "Bhubaneswar",
            "location_slug": "bhubaneswar",
            "region": "EAST_NE",
            "hazard": "heavy_rain",
            "severity": "watch",
            "valid_date": date(2026, 9, 23),
            "lead_days": 1,
            "value": 95.0,
            "models_over": 3,
            "spread": 12.5,
            "rule": {"blended": 95.0, "threshold": 64.5},
            "status": "active",
            "acknowledged_by": None,
            "acknowledged_at": None,
            "event_id": 42,
            "lifecycle_state": "new",
            "previous_severity": None,
            "rarity_label": "roughly a 1-in-10 event",
        }
    ]

    track_record_row = {
        "hits": 7,
        "false_alarms": 2,
    }

    async def mock_fetchrow(query, *args):
        if "FROM alert_events e" in query and "WHERE e.id = $1" in query:
            if args[0] == 42:
                return event_row
            return None
        if "COUNT(*) FILTER" in query:
            return track_record_row
        return None

    async def mock_fetch(query, *args):
        if "FROM alerts a" in query and "WHERE a.event_id = $1" in query:
            return alert_rows
        return []

    conn.fetchrow.side_effect = mock_fetchrow
    conn.fetch.side_effect = mock_fetch

    app.dependency_overrides[get_db_conn] = lambda: conn
    yield conn
    app.dependency_overrides.pop(get_db_conn, None)


def test_public_event_access_unauthenticated(mock_db_conn):
    """Verify that an anonymous/logged-out client can view alert event details without auth token."""
    with TestClient(app) as client:
        # No Authorization header provided (anonymous / incognito)
        resp = client.get("/api/v1/alerts/events/42")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Core event item
        event = data["event"]
        assert event["id"] == 42
        assert event["location_name"] == "Bhubaneswar"
        assert event["hazard"] == "heavy_rain"
        assert event["severity_peak"] == "watch"

        # Feature C: guidance block present
        guidance = data["guidance"]
        assert guidance is not None
        assert "Heavy Rainfall Watch" in guidance["headline"]
        assert "https://mausam.imd.gov.in" in guidance["official_link"]

        # Feature A: track record present
        tr = data["track_record"]
        assert tr is not None
        assert tr["applicable"] is True
        assert tr["n"] == 9
        assert tr["hits"] == 7
        assert tr["false_alarms"] == 2
        assert tr["low_sample"] is False

        # Feature F: share text present
        share_text = data["share_text"]
        assert share_text is not None
        assert "/alerts/e/42" in share_text
        assert "⚠️ WATCH — Heavy Rain for Bhubaneswar" in share_text
        assert "decision support, not an official IMD warning" in share_text


def test_share_text_template_adheres_to_prd(mock_db_conn):
    """Verify the share_text conforms exactly to the PRD §10.4 template."""
    with TestClient(app) as client:
        resp = client.get("/api/v1/alerts/events/42")
        assert resp.status_code == 200
        share_text = resp.json()["share_text"]

        lines = [line.strip() for line in share_text.split("\n") if line.strip()]
        assert len(lines) == 4
        # Line 1: ⚠️ {severity_label} — {hazard_label} for {location_name}
        assert lines[0] == "⚠️ WATCH — Heavy Rain for Bhubaneswar"
        # Line 2: {valid_date_range}: {headline value} ({agreement})
        assert "2026-09-23 to 2026-09-24" in lines[1]
        assert "3 of 4 models agree" in lines[1]
        # Line 3: Details: {public_url}
        assert lines[2] == "Details: /alerts/e/42"
        # Line 4: — via AAGAM (decision support, not an official IMD warning)
        assert lines[3] == "— via AAGAM (decision support, not an official IMD warning)"


def test_public_event_endpoint_does_not_leak_private_data(mock_db_conn):
    """Verify response does not leak emails, user_ids, subscription info, or secrets."""
    with TestClient(app) as client:
        resp = client.get("/api/v1/alerts/events/42")
        assert resp.status_code == 200
        text = resp.text.lower()

        # No user private emails or tokens
        assert "email" not in text
        assert "subscriber" not in text
        assert "service_role" not in text
        assert "access_token" not in text
        assert "secret" not in text


def test_security_boundary_auth_gating(mock_db_conn):
    """Verify that private and operator endpoints remain strictly gated while event detail is public."""
    with TestClient(app) as client:
        # Public event endpoint: 200 OK without token
        resp_public = client.get("/api/v1/alerts/events/42")
        assert resp_public.status_code == 200

        # Subscriptions endpoint: 401 Unauthorized without token
        resp_sub = client.get("/api/v1/subscriptions/me")
        assert resp_sub.status_code == 401

        # Operator acknowledgement endpoint: 401 Unauthorized without forecaster token
        resp_ack = client.post("/api/v1/alerts/events/42/ack")
        assert resp_ack.status_code == 401
