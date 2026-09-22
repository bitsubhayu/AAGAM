"""Tests for Phase 11: Brevo Notification Engine & Deduplication Logic (PRD §6.12, Tech Stack §8a)."""

from __future__ import annotations

import datetime as dt
import uuid
from unittest.mock import MagicMock

import psycopg2
import pytest

from core.config import settings
from pipeline.notify.brevo_client import BrevoClient
from pipeline.notify.daily_summary import run_daily_summary_job
from pipeline.notify.lifecycle import process_lifecycle_notifications


@pytest.fixture
def db_conn():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    yield conn
    conn.close()


def test_brevo_client_mock_dry_run():
    """Verify that BrevoClient cleanly generates mock IDs when run without an API key."""
    client = BrevoClient(api_key=None)
    res = client.send_email(
        to_email="test@example.com",
        subject="Test Subject",
        html_content="<p>Test</p>",
    )
    assert res["status"] == "mocked"
    assert res["messageId"].startswith("mock-")


def test_lifecycle_notification_new_and_upgraded(db_conn):
    """Verify that 'new' and 'upgraded' alerts dispatch emails and audit to notifications_log."""
    user_id = str(uuid.uuid4())
    email = f"officer_{uuid.uuid4().hex[:6]}@sdma.gov.in"
    event_id = None
    alert_id = None

    mock_brevo = MagicMock(spec=BrevoClient)
    mock_brevo.send_email.return_value = {"messageId": "msg-test-12345"}

    try:
        with db_conn.cursor() as cur:
            # 1. Seed user and subscription for location 1
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (user_id, email))
            cur.execute(
                """
                INSERT INTO subscriptions (
                    user_id, email, location_ids, hazards, min_severity,
                    lifecycle_emails, active
                ) VALUES (
                    %s, %s, ARRAY[1], '{heavy_rain}', 'watch', true, true
                );
                """,
                (user_id, email),
            )

            # 2. Seed alert_event
            cur.execute(
                """
                INSERT INTO alert_events (
                    location_id, hazard, status, severity_peak, value_peak,
                    start_date, end_date
                ) VALUES (1, 'heavy_rain', 'active', 'alert', 110.0, CURRENT_DATE, CURRENT_DATE)
                RETURNING id;
                """
            )
            event_id = cur.fetchone()[0]

            # 3. Seed alert with lifecycle_state = 'new'
            cur.execute(
                """
                INSERT INTO alerts (
                    issue_time, location_id, hazard, severity, valid_date, lead_days,
                    value, models_over, spread, rule, status, event_id, lifecycle_state
                ) VALUES (
                    NOW(), 1, 'heavy_rain', 'alert', CURRENT_DATE, 1,
                    110.0, 4, 10.0, '{"test": true}'::jsonb, 'active', %s, 'new'
                ) RETURNING id;
                """,
                (event_id,),
            )
            alert_id = cur.fetchone()[0]

        # Process lifecycle notification for the new alert
        res = process_lifecycle_notifications(
            alerts=[{
                "id": alert_id,
                "event_id": event_id,
                "location_id": 1,
                "hazard": "heavy_rain",
                "severity": "alert",
                "valid_date": dt.date.today(),
                "lifecycle_state": "new",
            }],
            conn=db_conn,
            brevo_client=mock_brevo,
        )

        assert res["sent"] >= 1
        assert res["deduped"] == 0
        assert mock_brevo.send_email.called

        # Check notifications_log entry for our specific test user
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT kind, event_id, lifecycle_state, status, dedup_key FROM notifications_log WHERE user_id = %s;",
                (user_id,),
            )
            log_row = cur.fetchone()
            assert log_row is not None
            assert log_row[0] == "lifecycle"
            assert log_row[1] == event_id
            assert log_row[2] == "new"
            assert log_row[3] == "sent"
            assert log_row[4] == f"lifecycle:{event_id}:new:{user_id}"

        # 4. Immediate duplicate attempt must be suppressed for our user
        mock_brevo.reset_mock()
        res_dup = process_lifecycle_notifications(
            alerts=[{
                "id": alert_id,
                "event_id": event_id,
                "location_id": 1,
                "hazard": "heavy_rain",
                "severity": "alert",
                "valid_date": dt.date.today(),
                "lifecycle_state": "new",
            }],
            conn=db_conn,
            brevo_client=mock_brevo,
        )
        assert res_dup["deduped"] >= 1

        # 5. Upgraded alert DOES send a notification
        mock_brevo.reset_mock()
        res_upgrade = process_lifecycle_notifications(
            alerts=[{
                "id": alert_id,
                "event_id": event_id,
                "location_id": 1,
                "hazard": "heavy_rain",
                "severity": "alert",
                "valid_date": dt.date.today(),
                "lifecycle_state": "upgraded",
                "previous_severity": "watch",
            }],
            conn=db_conn,
            brevo_client=mock_brevo,
        )
        assert res_upgrade["sent"] >= 1
        assert mock_brevo.send_email.called

    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM notifications_log WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM subscriptions WHERE user_id = %s;", (user_id,))
            if alert_id:
                cur.execute("DELETE FROM alerts WHERE id = %s;", (alert_id,))
            if event_id:
                cur.execute("DELETE FROM alert_events WHERE id = %s;", (event_id,))
            cur.execute("DELETE FROM auth.users WHERE id = %s;", (user_id,))


def test_unchanged_alert_never_notifies(db_conn):
    """Verify FR-NOTIFY-4: Unchanged alerts NEVER generate an email notification."""
    user_id = str(uuid.uuid4())
    email = f"officer_{uuid.uuid4().hex[:6]}@sdma.gov.in"
    mock_brevo = MagicMock(spec=BrevoClient)

    try:
        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (user_id, email))
            cur.execute(
                """
                INSERT INTO subscriptions (
                    user_id, email, location_ids, hazards, min_severity,
                    lifecycle_emails, active
                ) VALUES (
                    %s, %s, ARRAY[1], '{heavy_rain}', 'watch', true, true
                );
                """,
                (user_id, email),
            )

        res = process_lifecycle_notifications(
            alerts=[{
                "id": 999999,
                "event_id": 888888,
                "location_id": 1,
                "hazard": "heavy_rain",
                "severity": "alert",
                "valid_date": dt.date.today(),
                "lifecycle_state": "unchanged",
            }],
            conn=db_conn,
            brevo_client=mock_brevo,
        )
        assert res["sent"] == 0
        assert res["eligible_alerts"] == 0
        mock_brevo.send_email.assert_not_called()

    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM subscriptions WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM auth.users WHERE id = %s;", (user_id,))


def test_daily_summary_deduplication(db_conn):
    """Verify daily summary job compiles active alerts and suppresses same-day duplicates."""
    user_id = str(uuid.uuid4())
    email = f"officer_{uuid.uuid4().hex[:6]}@sdma.gov.in"
    test_date = "2026-09-22"
    mock_brevo = MagicMock(spec=BrevoClient)
    mock_brevo.send_email.return_value = {"messageId": "msg-daily-123"}

    try:
        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (user_id, email))
            cur.execute(
                """
                INSERT INTO subscriptions (
                    user_id, email, location_ids, hazards, min_severity,
                    daily_summary, active
                ) VALUES (
                    %s, %s, ARRAY[1, 2], '{heavy_rain}', 'watch', true, true
                );
                """,
                (user_id, email),
            )

        # First run of the day
        res_1 = run_daily_summary_job(
            conn=db_conn,
            brevo_client=mock_brevo,
            today_date_str=test_date,
        )
        assert res_1["sent"] >= 1
        mock_brevo.send_email.assert_called()

        # Second run on the same date for the same user must be deduped
        mock_brevo.reset_mock()
        res_2 = run_daily_summary_job(
            conn=db_conn,
            brevo_client=mock_brevo,
            today_date_str=test_date,
        )
        assert res_2["deduped"] >= 1
        mock_brevo.send_email.assert_not_called()

    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM notifications_log WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM subscriptions WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM auth.users WHERE id = %s;", (user_id,))
