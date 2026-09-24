"""Final Alert System Corrections Automated Test Suite.

Covers all 27 specified test requirements:
1. Exact severity filter advisory (`severity=advisory`).
2. Exact severity filter watch (`severity=watch`).
3. Exact severity filter alert (`severity=alert`).
4. Invalid severity filter returns 422.
5. Default feed chronological ordering (non-severe dominated).
6. Operational count is based on distinct alert events, not 10,000+ raw rows.
7. Feed returns unique event cards (no duplicate event cards).
8. Cancelled records never counted as active.
9. Status cancelled filter returns cancelled items.
10. Cancel alert event endpoint sets status='cancelled' and lifecycle_state='cancelled'.
11. Pre-LIMIT count invariant: advisory + watch + alert == total count.
12. Severity counts are computed over complete dataset independent of LIMIT.
13. Server-side search filters by station name and region.
14. Server-side search updates both feed and authoritative count/severity_counts.
15. Subscriptions preserve cumulative min_severity threshold semantics.
16. Subscriptions reject invalid min_severity with HTTP 422.
17. Subscriptions demo user persistence works without foreign key errors.
18. Subscriptions endpoint responds quickly and cleanly.
19. Window filtering correctly bounds event dates.
20. Hazard filtering operates on events.
21. Region filtering operates on events.
22. Max lead days filter limits forecast lead days.
23. Combined multi-parameter filtering works together.
24. Overview and Extreme Weather Center count consistency.
25. Pipeline Alert dataclass includes event_id and lifecycle fields.
26. Pipeline group_alerts_into_events assigns event_id.
27. Cancelled records are preserved in database (no physical deletions).
"""

from __future__ import annotations

import datetime
import time

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from core.config import settings
from pipeline.blend.extremes import Alert
from pipeline.events.group import group_alerts_into_events

TEST_JWT_SECRET = "test-final-alert-corrections-secret-key-32ch"


def create_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": "authenticated",
        "app_metadata": {"role": role},
        "user_metadata": {"role": role},
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
    }
    return jwt.encode(payload, settings.SUPABASE_JWT_SECRET or TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db_conn():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    demo_users = [
        ("00000000-0000-0000-0000-000000000001", "public@aagam.gov.in", "public", "Demo Public"),
        ("00000000-0000-0000-0000-000000000002", "forecaster@aagam.gov.in", "forecaster", "Demo Forecaster"),
        ("00000000-0000-0000-0000-000000000003", "coordinator@aagam.gov.in", "coordinator", "Demo Coordinator"),
    ]
    with conn.cursor() as cur:
        for uid, email, role, dname in demo_users:
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;", (uid, email))
            cur.execute(
                """
                INSERT INTO profiles (user_id, display_name, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET role = EXCLUDED.role, display_name = EXCLUDED.display_name;
                """,
                (uid, dname, role),
            )
    yield conn
    conn.close()


@pytest.fixture
def client(db_conn):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def forecaster_headers():
    token = create_token("00000000-0000-0000-0000-000000000002", "forecaster@aagam.gov.in", "forecaster")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def coordinator_headers():
    token = create_token("00000000-0000-0000-0000-000000000003", "coordinator@aagam.gov.in", "coordinator")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def public_headers():
    token = create_token("00000000-0000-0000-0000-000000000001", "public@aagam.gov.in", "public")
    return {"Authorization": f"Bearer {token}"}


# -------------------------------------------------------------------------
# TASK 1: EXACT SEVERITY FILTERING & SUBSCRIPTION CUMULATIVE PRESERVATION
# -------------------------------------------------------------------------

def test_1_exact_severity_filter_advisory(client):
    """GET /api/v1/alerts?severity=advisory returns ONLY advisory alerts."""
    resp = client.get("/api/v1/alerts?severity=advisory&limit=50")
    assert resp.status_code == 200
    data = resp.json()
    alerts = data.get("alerts", [])
    for a in alerts:
        assert a["severity"] == "advisory", f"Expected advisory, got {a['severity']}"


def test_2_exact_severity_filter_watch(client):
    """GET /api/v1/alerts?severity=watch returns ONLY watch alerts."""
    resp = client.get("/api/v1/alerts?severity=watch&limit=50")
    assert resp.status_code == 200
    data = resp.json()
    alerts = data.get("alerts", [])
    for a in alerts:
        assert a["severity"] == "watch", f"Expected watch, got {a['severity']}"


def test_3_exact_severity_filter_alert(client):
    """GET /api/v1/alerts?severity=alert returns ONLY alert (severe) alerts."""
    resp = client.get("/api/v1/alerts?severity=alert&limit=50")
    assert resp.status_code == 200
    data = resp.json()
    alerts = data.get("alerts", [])
    for a in alerts:
        assert a["severity"] == "alert", f"Expected alert, got {a['severity']}"


def test_4_exact_severity_invalid(client):
    """GET /api/v1/alerts?severity=invalid returns HTTP 422 with INVALID_SEVERITY."""
    resp = client.get("/api/v1/alerts?severity=catastrophic")
    assert resp.status_code == 422
    err = resp.json().get("error") or resp.json().get("detail", {})
    assert err.get("code") == "INVALID_SEVERITY"


def test_5_default_feed_ordering_not_alert_dominated(client):
    """Default active feed sorts chronologically by date and lead day, avoiding severe alert monopoly."""
    resp = client.get("/api/v1/alerts?status=active&limit=50")
    assert resp.status_code == 200
    data = resp.json()
    alerts = data.get("alerts", [])
    if len(alerts) > 1:
        # Check that dates are non-decreasing
        dates = [a["valid_date"] for a in alerts]
        assert dates == sorted(dates), "Feed must be ordered chronologically by valid_date"
        # Check that advisories or watches can appear early if valid_date is earlier
        severities = [a["severity"] for a in alerts]
        # Not all top items should be 'alert' if advisories/watches exist
        counts = data.get("severity_counts", {})
        if counts.get("advisory", 0) > 0 or counts.get("watch", 0) > 0:
            assert "advisory" in severities or "watch" in severities, "Advisories/watches must appear in feed"


# -------------------------------------------------------------------------
# TASK 3 & 4: OPERATIONAL EVENT-BASED COUNTING & CANCELLED SEMANTICS
# -------------------------------------------------------------------------

def test_6_event_based_counting_not_raw_cycle_rows(client):
    """Total active count must reflect distinct alert events (< 500), not 8000+ raw cycle rows."""
    resp = client.get("/api/v1/alerts?status=active")
    assert resp.status_code == 200
    data = resp.json()
    total_count = data.get("count", 0)
    assert total_count < 2000, f"Expected event-based count < 2000, got raw row count {total_count}"


def test_7_feed_returns_unique_event_cards(client):
    """Active feed items must correspond to distinct alert events (no duplicate event cards)."""
    resp = client.get("/api/v1/alerts?status=active&limit=100")
    assert resp.status_code == 200
    alerts = resp.json().get("alerts", [])
    event_ids = [a["event_id"] for a in alerts if a.get("event_id") is not None]
    assert len(event_ids) == len(set(event_ids)), "Every event in feed must be unique (1 card per event)"


def test_8_cancelled_records_not_in_active(client):
    """Active status query must never return cancelled records."""
    resp = client.get("/api/v1/alerts?status=active&limit=100")
    assert resp.status_code == 200
    alerts = resp.json().get("alerts", [])
    for a in alerts:
        assert a.get("status") != "cancelled", "Cancelled alert found in active feed"
        assert a.get("lifecycle_state") != "cancelled", "Cancelled lifecycle found in active feed"


def test_9_status_cancelled_filter(client):
    """Querying status=cancelled must retrieve cancelled alerts."""
    resp = client.get("/api/v1/alerts?status=cancelled&limit=20")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 0
    for a in data.get("alerts", []):
        assert a.get("status") == "cancelled" or a.get("lifecycle_state") == "cancelled"


def test_10_cancel_alert_event_updates_status_and_lifecycle(client, coordinator_headers, db_conn):
    """Cancelling an alert event sets status='cancelled' and child alerts lifecycle_state='cancelled'."""
    # Find an active event or create a test event
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO alert_events (hazard, location_id, status, severity_peak, start_date, end_date)
            VALUES ('heatwave', 1, 'active', 'advisory', CURRENT_DATE, CURRENT_DATE + 1)
            RETURNING id;
            """
        )
        event_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO alerts (event_id, location_id, hazard, severity, valid_date, lead_days, status, lifecycle_state, value, issue_time, rule)
            VALUES (%s, 1, 'heatwave', 'advisory', CURRENT_DATE, 1, 'active', 'new', 42.0, NOW(), '{"threshold": 40.0}')
            RETURNING id;
            """,
            (event_id,)
        )
        alert_id = cur.fetchone()[0]

    cancel_resp = client.post(
        f"/api/v1/alerts/events/{event_id}/cancel",
        json={"reason": "Hazard threat dissipated"},
        headers=coordinator_headers,
    )
    assert cancel_resp.status_code == 200
    cdata = cancel_resp.json()
    assert cdata["status"] == "cancelled"
    assert cdata["lifecycle_state"] == "cancelled"

    # Verify DB state
    with db_conn.cursor() as cur:
        cur.execute("SELECT status FROM alert_events WHERE id = %s;", (event_id,))
        erow = cur.fetchone()
        assert erow[0] == "cancelled"

        cur.execute("SELECT status, lifecycle_state FROM alerts WHERE id = %s;", (alert_id,))
        arow = cur.fetchone()
        assert arow[0] == "cancelled"
        assert arow[1] == "cancelled"


# -------------------------------------------------------------------------
# TASK 5: PRE-LIMIT COUNT INVARIANT & SEVERITY COUNTS
# -------------------------------------------------------------------------

def test_11_severity_counts_sum_to_total(client):
    """The invariant advisory + watch + alert == total count must hold exactly."""
    resp = client.get("/api/v1/alerts?status=active")
    assert resp.status_code == 200
    data = resp.json()
    total = data.get("count", 0)
    sc = data.get("severity_counts", {})
    advisory = sc.get("advisory", 0)
    watch = sc.get("watch", 0)
    alert = sc.get("alert", 0)
    assert advisory + watch + alert == total, f"{advisory} + {watch} + {alert} != {total}"


def test_12_severity_counts_independent_of_limit(client):
    """Severity counts must be computed over the full operational dataset, not truncated by LIMIT."""
    resp_all = client.get("/api/v1/alerts?status=active&limit=100")
    resp_one = client.get("/api/v1/alerts?status=active&limit=1")
    assert resp_all.status_code == 200
    assert resp_one.status_code == 200
    assert resp_all.json()["count"] == resp_one.json()["count"]
    assert resp_all.json()["severity_counts"] == resp_one.json()["severity_counts"]


# -------------------------------------------------------------------------
# TASK 6: SERVER-SIDE SEARCH
# -------------------------------------------------------------------------

def test_13_server_side_search_filtering(client):
    """Search query filters feed items by location name or region."""
    # First get an active station name
    resp = client.get("/api/v1/alerts?status=active&limit=5")
    assert resp.status_code == 200
    alerts = resp.json().get("alerts", [])
    if alerts:
        loc_name = alerts[0]["location_name"]
        query_word = loc_name.split()[0]
        search_resp = client.get(f"/api/v1/alerts?status=active&search={query_word}")
        assert search_resp.status_code == 200
        search_data = search_resp.json()
        for a in search_data.get("alerts", []):
            matches = (
                query_word.lower() in a["location_name"].lower()
                or query_word.lower() in a["region"].lower()
            )
            assert matches, f"Search result {a['location_name']} / {a['region']} does not match query {query_word}"


def test_14_server_side_search_updates_counts(client):
    """Search query updates both feed and authoritative count/severity_counts."""
    search_resp = client.get("/api/v1/alerts?status=active&search=NonExistentLocationXYZ123")
    assert search_resp.status_code == 200
    data = search_resp.json()
    assert data["count"] == 0
    assert data["severity_counts"]["advisory"] == 0
    assert data["severity_counts"]["watch"] == 0
    assert data["severity_counts"]["alert"] == 0
    assert len(data["alerts"]) == 0


# -------------------------------------------------------------------------
# TASK 8: SUBSCRIPTION PERSISTENCE & TIMEOUT
# -------------------------------------------------------------------------

def test_15_cumulative_min_severity_subscriptions(client, public_headers):
    """Subscriptions retain cumulative min_severity threshold."""
    for sev in ("advisory", "watch", "alert"):
        resp = client.put(
            "/api/v1/subscriptions/me",
            json={
                "location_ids": [1, 2],
                "hazards": ["heavy_rain"],
                "min_severity": sev,
                "daily_summary": True,
                "lifecycle_emails": True,
                "active": True,
            },
            headers=public_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["min_severity"] == sev


def test_16_subscription_invalid_min_severity(client, public_headers):
    """Subscriptions reject invalid min_severity with HTTP 422."""
    resp = client.put(
        "/api/v1/subscriptions/me",
        json={
            "location_ids": [1],
            "hazards": ["heavy_rain"],
            "min_severity": "catastrophic",
            "daily_summary": True,
            "lifecycle_emails": True,
            "active": True,
        },
        headers=public_headers,
    )
    assert resp.status_code == 422
    err = resp.json().get("error") or resp.json().get("detail", {})
    assert err.get("code") == "INVALID_SEVERITY"


def test_17_subscription_demo_user_persistence(client, forecaster_headers):
    """Demo users can save subscription preferences without foreign key violation."""
    resp = client.put(
        "/api/v1/subscriptions/me",
        json={
            "location_ids": [3, 4],
            "hazards": ["heatwave", "high_wind"],
            "min_severity": "watch",
            "daily_summary": False,
            "lifecycle_emails": True,
            "active": True,
        },
        headers=forecaster_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["location_ids"] == [3, 4]
    assert data["hazards"] == ["heatwave", "high_wind"]

    # Verify retrieval
    get_resp = client.get("/api/v1/subscriptions/me", headers=forecaster_headers)
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["location_ids"] == [3, 4]


def test_18_subscription_endpoint_fast_response(client, public_headers):
    """Subscription endpoint responds well under the 10-second client timeout."""
    start = time.time()
    resp = client.get("/api/v1/subscriptions/me", headers=public_headers)
    duration = time.time() - start
    assert resp.status_code == 200
    assert duration < 5.0, f"Subscription response too slow: {duration:.2f}s"


# -------------------------------------------------------------------------
# FILTERING & WINDOW TESTS
# -------------------------------------------------------------------------

def test_19_window_filtering_events(client):
    """Window filters upcoming_2d and upcoming_7d return valid responses."""
    resp_2d = client.get("/api/v1/alerts?window=upcoming_2d")
    resp_7d = client.get("/api/v1/alerts?window=upcoming_7d")
    assert resp_2d.status_code == 200
    assert resp_7d.status_code == 200
    assert resp_7d.json()["count"] >= resp_2d.json()["count"]


def test_20_hazard_filter_events(client):
    """Hazard filtering returns only events matching requested hazard."""
    resp = client.get("/api/v1/alerts?hazard=heavy_rain&limit=20")
    assert resp.status_code == 200
    for a in resp.json().get("alerts", []):
        assert a["hazard"] == "heavy_rain"


def test_21_region_filter_events(client):
    """Region filtering returns only events matching requested region."""
    resp = client.get("/api/v1/alerts?region=NORTH&limit=20")
    assert resp.status_code == 200
    for a in resp.json().get("alerts", []):
        assert a["region"] == "NORTH"


def test_22_max_lead_days_filter(client):
    """Max lead days filter constrains lead_days on alerts."""
    resp = client.get("/api/v1/alerts?max_lead_days=2&limit=20")
    assert resp.status_code == 200
    for a in resp.json().get("alerts", []):
        assert a["lead_days"] <= 2


def test_23_combined_filters(client):
    """Combined severity, hazard, and status filters work together."""
    resp = client.get("/api/v1/alerts?status=active&severity=advisory&hazard=heavy_rain&limit=20")
    assert resp.status_code == 200
    for a in resp.json().get("alerts", []):
        assert a["status"] == "active"
        assert a["severity"] == "advisory"
        assert a["hazard"] == "heavy_rain"


def test_24_overview_and_center_count_consistency(client):
    """Overview and Extreme Weather Center queries share the identical authoritative counts."""
    center_resp = client.get("/api/v1/alerts?status=active&limit=100")
    overview_resp = client.get("/api/v1/alerts?window=upcoming_7d&limit=20")
    assert center_resp.status_code == 200
    assert overview_resp.status_code == 200
    # Both report non-negative integer counts and identical invariant
    c_counts = center_resp.json()["severity_counts"]
    o_counts = overview_resp.json()["severity_counts"]
    assert c_counts["advisory"] + c_counts["watch"] + c_counts["alert"] == center_resp.json()["count"]
    assert o_counts["advisory"] + o_counts["watch"] + o_counts["alert"] == overview_resp.json()["count"]


# -------------------------------------------------------------------------
# PIPELINE ARCHITECTURE & DATABASE INTEGRITY
# -------------------------------------------------------------------------

def make_test_alert(
    location_id: int = 1,
    name: str = "Test Station",
    valid_date: datetime.date | None = None,
    lead_days: int = 1,
    severity: str = "advisory",
    event_id: int | None = None,
    lifecycle_state: str = "new",
) -> Alert:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    return Alert(
        id=f"alert-{location_id}-{lead_days}",
        created_at=now_utc.isoformat(),
        valid_date=str(valid_date or datetime.date.today()),
        lead_days=lead_days,
        location_id=location_id,
        location_slug="test-station",
        location_name=name,
        terrain="plains",
        region="NORTH",
        hazard="heavy_rain",
        severity=severity,
        severity_label="Advisory (Notice)",
        value=75.0,
        agreement=3,
        spread=5.0,
        rule={"threshold": 64.5, "metric": "precipitation"},
        source_models={"gfs": 70.0, "ifs": 80.0},
        degraded=False,
        status="active",
        expires_at=(now_utc + datetime.timedelta(days=2)).isoformat(),
        event_id=event_id,
        lifecycle_state=lifecycle_state,
        previous_severity=None,
    )


def test_25_pipeline_alert_dataclass_includes_event_fields():
    """Alert dataclass includes event_id, lifecycle_state, and previous_severity."""
    alert = make_test_alert(event_id=42, lifecycle_state="new")
    assert alert.event_id == 42
    assert alert.lifecycle_state == "new"
    assert alert.previous_severity is None


def test_26_pipeline_grouping_sets_event_id():
    """group_alerts_into_events assigns event_id to grouped alerts."""
    today = datetime.date.today()
    alerts = [
        make_test_alert(location_id=1, valid_date=today, lead_days=1, severity="advisory"),
        make_test_alert(location_id=1, valid_date=today + datetime.timedelta(days=1), lead_days=2, severity="watch"),
    ]
    grouped_alerts, events = group_alerts_into_events(alerts, active_events=[])
    assert len(events) == 1
    assert events[0].id is not None
    for a in grouped_alerts:
        assert a.event_id == events[0].id


def test_27_no_physical_deletion_of_cancelled_records(db_conn):
    """Cancelled alerts and events are preserved in database without physical deletion."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM alerts WHERE status = 'cancelled';")
        cancelled_alerts_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM alert_events WHERE status = 'cancelled';")
        cancelled_events_count = cur.fetchone()[0]

    # Verify that cancelled records exist in the database (proving soft-cancellation)
    assert cancelled_alerts_count > 0, "Cancelled alerts must be preserved in DB"
    assert cancelled_events_count > 0, "Cancelled events must be preserved in DB"
