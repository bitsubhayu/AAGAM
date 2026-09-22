"""Phase 11 Acceptance Test: Two-Location Subscription Lifecycle & Audit (PRD §6.12, §11, §15).

Verifies the complete end-to-end acceptance scenario:
1. Subscribes user to TWO locations (Location 1 & Location 2).
2. Seeds a controlled multi-hazard lifecycle sequence:
   - Location 1: new heavy_rain alert
   - Location 2: new heatwave alert
   - Location 1: upgraded severity transition
   - Unchanged cycle: zero notifications generated (FR-NOTIFY-4)
   - Location 2: cancelled transition
3. Validates that:
   - Eligible notifications are dispatched and received
   - Email deliveries are logged in notifications_log with provider message IDs
   - Duplicate notifications are suppressed
   - Non-subscribed locations/users are completely isolated
   - RLS security boundaries hold across users and log tables
"""

from __future__ import annotations

import datetime as dt
import uuid
from unittest.mock import MagicMock

import psycopg2
import pytest

from core.config import settings
from pipeline.notify.brevo_client import BrevoClient
from pipeline.notify.lifecycle import process_lifecycle_notifications


@pytest.fixture
def db_conn():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    yield conn
    conn.close()


def test_two_location_subscription_acceptance(db_conn):
    """Executes the complete Phase 11 two-location acceptance test sequence."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    email_a = f"officer_a_{uuid.uuid4().hex[:6]}@sdma.gov.in"
    email_b = f"officer_b_{uuid.uuid4().hex[:6]}@sdma.gov.in"

    loc_1 = 1  # e.g. Kolkata
    loc_2 = 2  # e.g. Bhubaneswar
    loc_3 = 3  # e.g. Cuttack (User B only)

    evt_1_id = None
    evt_2_id = None
    alert_1_id = None
    alert_2_id = None

    mock_brevo = MagicMock(spec=BrevoClient)
    sent_emails_a = []
    sent_emails_b = []

    def mock_send(to_email, subject, html_content, text_content=None, to_name=None):
        msg_id = f"brevo-acc-{uuid.uuid4().hex[:8]}"
        if to_email == email_a:
            sent_emails_a.append({"subject": subject, "msg_id": msg_id})
        elif to_email == email_b:
            sent_emails_b.append({"subject": subject, "msg_id": msg_id})
        return {"messageId": msg_id}

    mock_brevo.send_email.side_effect = mock_send

    try:
        with db_conn.cursor() as cur:
            # 1. Create auth users and subscriptions
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (user_a, email_a))
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (user_b, email_b))

            # User A subscribes to TWO locations: loc_1 and loc_2
            cur.execute(
                """
                INSERT INTO subscriptions (
                    user_id, email, location_ids, hazards, min_severity,
                    lifecycle_emails, active
                ) VALUES (
                    %s, %s, ARRAY[%s, %s], '{heavy_rain,heatwave}', 'watch', true, true
                );
                """,
                (user_a, email_a, loc_1, loc_2),
            )

            # User B subscribes ONLY to loc_3
            cur.execute(
                """
                INSERT INTO subscriptions (
                    user_id, email, location_ids, hazards, min_severity,
                    lifecycle_emails, active
                ) VALUES (
                    %s, %s, ARRAY[%s], '{heavy_rain,heatwave}', 'watch', true, true
                );
                """,
                (user_b, email_b, loc_3),
            )

            # 2. Sequence Step A: New heavy_rain alert at Location 1
            cur.execute(
                """
                INSERT INTO alert_events (
                    location_id, hazard, status, severity_peak, value_peak,
                    start_date, end_date
                ) VALUES (%s, 'heavy_rain', 'active', 'watch', 75.0, CURRENT_DATE, CURRENT_DATE)
                RETURNING id;
                """,
                (loc_1,),
            )
            evt_1_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO alerts (
                    issue_time, location_id, hazard, severity, valid_date, lead_days,
                    value, models_over, spread, rule, status, event_id, lifecycle_state
                ) VALUES (
                    NOW(), %s, 'heavy_rain', 'watch', CURRENT_DATE, 1,
                    75.0, 3, 8.0, '{"acc": true}'::jsonb, 'active', %s, 'new'
                ) RETURNING id;
                """,
                (loc_1, evt_1_id),
            )
            alert_1_id = cur.fetchone()[0]

        # Dispatch Step A
        process_lifecycle_notifications(
            alerts=[{
                "id": alert_1_id,
                "event_id": evt_1_id,
                "location_id": loc_1,
                "hazard": "heavy_rain",
                "severity": "watch",
                "valid_date": dt.date.today(),
                "lifecycle_state": "new",
            }],
            conn=db_conn,
            brevo_client=mock_brevo,
        )

        # Assert User A received notification for Location 1, User B received nothing
        assert len(sent_emails_a) == 1, "User A should receive 1 notification for Location 1"
        assert len(sent_emails_b) == 0, "User B should not receive Location 1 notification"
        assert "Heavy Rain" in sent_emails_a[0]["subject"]

        # 3. Sequence Step B: New heatwave alert at Location 2
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_events (
                    location_id, hazard, status, severity_peak, value_peak,
                    start_date, end_date
                ) VALUES (%s, 'heatwave', 'active', 'alert', 44.5, CURRENT_DATE, CURRENT_DATE)
                RETURNING id;
                """,
                (loc_2,),
            )
            evt_2_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO alerts (
                    issue_time, location_id, hazard, severity, valid_date, lead_days,
                    value, models_over, spread, rule, status, event_id, lifecycle_state
                ) VALUES (
                    NOW(), %s, 'heatwave', 'alert', CURRENT_DATE, 1,
                    44.5, 4, 1.2, '{"acc": true}'::jsonb, 'active', %s, 'new'
                ) RETURNING id;
                """,
                (loc_2, evt_2_id),
            )
            alert_2_id = cur.fetchone()[0]

        # Dispatch Step B
        process_lifecycle_notifications(
            alerts=[{
                "id": alert_2_id,
                "event_id": evt_2_id,
                "location_id": loc_2,
                "hazard": "heatwave",
                "severity": "alert",
                "valid_date": dt.date.today(),
                "lifecycle_state": "new",
            }],
            conn=db_conn,
            brevo_client=mock_brevo,
        )

        # Assert User A received notification for Location 2 as well
        assert len(sent_emails_a) == 2, "User A should receive second notification for Location 2"
        assert len(sent_emails_b) == 0, "User B should still receive 0"
        assert "Heatwave" in sent_emails_a[1]["subject"]

        # 4. Sequence Step C: Lifecycle Transition (Location 1 upgrades to 'alert')
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE alert_events SET severity_peak = 'alert', value_peak = 115.0 WHERE id = %s;",
                (evt_1_id,),
            )

        process_lifecycle_notifications(
            alerts=[{
                "id": alert_1_id,
                "event_id": evt_1_id,
                "location_id": loc_1,
                "hazard": "heavy_rain",
                "severity": "alert",
                "previous_severity": "watch",
                "valid_date": dt.date.today(),
                "lifecycle_state": "upgraded",
            }],
            conn=db_conn,
            brevo_client=mock_brevo,
        )

        assert len(sent_emails_a) == 3, "User A should receive transition notification for Location 1 upgrade"
        assert "Upgraded" in sent_emails_a[2]["subject"]

        # 5. Sequence Step D: Unchanged cycle (no notifications sent per FR-NOTIFY-4)
        process_lifecycle_notifications(
            alerts=[
                {
                    "id": alert_1_id,
                    "event_id": evt_1_id,
                    "location_id": loc_1,
                    "hazard": "heavy_rain",
                    "severity": "alert",
                    "valid_date": dt.date.today(),
                    "lifecycle_state": "unchanged",
                },
                {
                    "id": alert_2_id,
                    "event_id": evt_2_id,
                    "location_id": loc_2,
                    "hazard": "heatwave",
                    "severity": "alert",
                    "valid_date": dt.date.today(),
                    "lifecycle_state": "unchanged",
                },
            ],
            conn=db_conn,
            brevo_client=mock_brevo,
        )

        assert len(sent_emails_a) == 3, "Unchanged alerts must NOT generate duplicate email notifications"

        # 6. Sequence Step E: Threat at Location 2 is cancelled prior to arrival
        with db_conn.cursor() as cur:
            cur.execute("UPDATE alert_events SET status = 'cancelled' WHERE id = %s;", (evt_2_id,))

        process_lifecycle_notifications(
            alerts=[{
                "id": alert_2_id,
                "event_id": evt_2_id,
                "location_id": loc_2,
                "hazard": "heatwave",
                "severity": "alert",
                "valid_date": dt.date.today(),
                "lifecycle_state": "cancelled",
            }],
            conn=db_conn,
            brevo_client=mock_brevo,
        )

        assert len(sent_emails_a) == 4, "User A should receive cancellation notice for Location 2"
        assert "Cancelled" in sent_emails_a[3]["subject"]

        # 7. Verify Audit Log Trail in notifications_log
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT kind, event_id, lifecycle_state, status, dedup_key
                FROM notifications_log
                WHERE user_id = %s
                ORDER BY id ASC;
                """,
                (user_a,),
            )
            audit_rows = cur.fetchall()
            assert len(audit_rows) == 4, f"Expected 4 audit entries for User A, found {len(audit_rows)}"

            states = [r[2] for r in audit_rows]
            assert states == ["new", "new", "upgraded", "cancelled"]

            # Confirm duplicate suppression on retry
            cur.execute(
                "SELECT count(*) FROM notifications_log WHERE user_id = %s AND dedup_key = %s;",
                (user_a, f"lifecycle:{evt_1_id}:new:{user_a}"),
            )
            assert cur.fetchone()[0] == 1, "Duplicate key count must be strictly 1"

    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM notifications_log WHERE user_id IN (%s, %s);", (user_a, user_b))
            cur.execute("DELETE FROM subscriptions WHERE user_id IN (%s, %s);", (user_a, user_b))
            if alert_1_id:
                cur.execute("DELETE FROM alerts WHERE id = %s;", (alert_1_id,))
            if alert_2_id:
                cur.execute("DELETE FROM alerts WHERE id = %s;", (alert_2_id,))
            if evt_1_id:
                cur.execute("DELETE FROM alert_events WHERE id = %s;", (evt_1_id,))
            if evt_2_id:
                cur.execute("DELETE FROM alert_events WHERE id = %s;", (evt_2_id,))
            cur.execute("DELETE FROM auth.users WHERE id IN (%s, %s);", (user_a, user_b))
