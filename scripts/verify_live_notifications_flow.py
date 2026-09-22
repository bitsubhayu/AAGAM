"""AAGAM — Phase 11 Real Two-Location Notification Lifecycle Test (PRD §6.12, §11).

Controlled live test with verified recipient (subhayubit20042005@gmail.com):
1. Subscribes user to Location 1 (Kolkata) & Location 2 (Basirhat).
2. Location 1: new heavy_rain alert -> sends real Brevo email, records provider message ID.
3. Location 1: upgraded to alert -> sends real Brevo email, records provider message ID.
4. Unchanged cycle -> ZERO duplicate emails sent (FR-NOTIFY-4).
5. Location 2: new heatwave alert -> sends real Brevo email.
6. Location 2: cancelled -> sends cancellation email.
7. Verifies notifications_log has all audit rows with real provider message IDs.
8. Cleans up test alerts and events.
"""

from __future__ import annotations

import datetime as dt
import sys
import uuid
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import psycopg2

from core.config import settings
from pipeline.notify.brevo_client import BrevoClient
from pipeline.notify.lifecycle import process_lifecycle_notifications


def run_live_two_location_verification(target_email: str = "subhayubit20042005@gmail.com") -> int:
    print("=" * 70)
    print("AAGAM — PHASE 11 REAL TWO-LOCATION NOTIFICATION TEST")
    print(f"Target Verified Recipient: {target_email}")
    print("=" * 70)

    if not settings.BREVO_API_KEY or settings.BREVO_API_KEY.startswith("mock"):
        print("[FAIL] Real BREVO_API_KEY is not set.")
        return 1

    brevo = BrevoClient()
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True

    user_id = str(uuid.uuid4())
    loc_1 = 1  # Kolkata
    loc_2 = 2  # Basirhat

    evt_1_id = None
    evt_2_id = None
    alert_1_id = None
    alert_2_id = None

    try:
        with conn.cursor() as cur:
            # 1. Fetch or create user
            cur.execute("SELECT id FROM auth.users WHERE email = %s;", (target_email,))
            u_row = cur.fetchone()
            if u_row:
                user_id = str(u_row[0])
                created_user = False
            else:
                user_id = str(uuid.uuid4())
                cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (user_id, target_email))
                created_user = True

            cur.execute(
                """
                INSERT INTO subscriptions (
                    user_id, email, location_ids, hazards, min_severity,
                    lifecycle_emails, active
                ) VALUES (
                    %s, %s, ARRAY[%s, %s], '{heavy_rain,heatwave}', 'watch', true, true
                )
                ON CONFLICT (user_id) DO UPDATE
                SET location_ids = EXCLUDED.location_ids,
                    hazards = EXCLUDED.hazards,
                    min_severity = EXCLUDED.min_severity,
                    lifecycle_emails = EXCLUDED.lifecycle_emails,
                    active = EXCLUDED.active;
                """,
                (user_id, target_email, loc_1, loc_2),
            )

            # 2. Location 1: New Alert Event
            cur.execute(
                """
                INSERT INTO alert_events (
                    location_id, hazard, status, severity_peak, value_peak,
                    start_date, end_date
                ) VALUES (%s, 'heavy_rain', 'active', 'watch', 70.0, CURRENT_DATE, CURRENT_DATE)
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
                    70.0, 3, 5.0, '{"live_test": true}'::jsonb, 'active', %s, 'new'
                ) RETURNING id;
                """,
                (loc_1, evt_1_id),
            )
            alert_1_id = cur.fetchone()[0]

        # Dispatch Location 1: new
        print("\n[STEP 1] Dispatching Location 1: NEW Heavy Rain Alert...")
        res_1 = process_lifecycle_notifications(
            alerts=[{
                "id": alert_1_id,
                "event_id": evt_1_id,
                "location_id": loc_1,
                "hazard": "heavy_rain",
                "severity": "watch",
                "valid_date": dt.date.today(),
                "lifecycle_state": "new",
            }],
            conn=conn,
            brevo_client=brevo,
        )
        print(f"  Sent: {res_1['sent']}, Deduped: {res_1['deduped']}")
        assert res_1["sent"] >= 1, "Location 1 new alert must dispatch email"

        # Dispatch Location 1: upgraded
        print("\n[STEP 2] Dispatching Location 1: UPGRADED to Alert...")
        res_2 = process_lifecycle_notifications(
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
            conn=conn,
            brevo_client=brevo,
        )
        print(f"  Sent: {res_2['sent']}, Deduped: {res_2['deduped']}")
        assert res_2["sent"] >= 1, "Location 1 upgrade must dispatch email"

        # Dispatch Location 1: unchanged cycle (FR-NOTIFY-4)
        print("\n[STEP 3] Dispatching Location 1: UNCHANGED Cycle...")
        res_3 = process_lifecycle_notifications(
            alerts=[{
                "id": alert_1_id,
                "event_id": evt_1_id,
                "location_id": loc_1,
                "hazard": "heavy_rain",
                "severity": "alert",
                "valid_date": dt.date.today(),
                "lifecycle_state": "unchanged",
            }],
            conn=conn,
            brevo_client=brevo,
        )
        print(f"  Sent: {res_3['sent']} (Expected 0), Deduped: {res_3['deduped']}")
        assert res_3["sent"] == 0, "Unchanged alert must NEVER send email"

        # Location 2: New Heatwave Alert
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_events (
                    location_id, hazard, status, severity_peak, value_peak,
                    start_date, end_date
                ) VALUES (%s, 'heatwave', 'active', 'alert', 43.0, CURRENT_DATE, CURRENT_DATE)
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
                    43.0, 4, 1.0, '{"live_test": true}'::jsonb, 'active', %s, 'new'
                ) RETURNING id;
                """,
                (loc_2, evt_2_id),
            )
            alert_2_id = cur.fetchone()[0]

        print("\n[STEP 4] Dispatching Location 2: NEW Heatwave Alert...")
        res_4 = process_lifecycle_notifications(
            alerts=[{
                "id": alert_2_id,
                "event_id": evt_2_id,
                "location_id": loc_2,
                "hazard": "heatwave",
                "severity": "alert",
                "valid_date": dt.date.today(),
                "lifecycle_state": "new",
            }],
            conn=conn,
            brevo_client=brevo,
        )
        print(f"  Sent: {res_4['sent']}, Deduped: {res_4['deduped']}")
        assert res_4["sent"] >= 1, "Location 2 new alert must dispatch email"

        # Location 2: Cancelled
        print("\n[STEP 5] Dispatching Location 2: CANCELLED Notice...")
        res_5 = process_lifecycle_notifications(
            alerts=[{
                "id": alert_2_id,
                "event_id": evt_2_id,
                "location_id": loc_2,
                "hazard": "heatwave",
                "severity": "alert",
                "valid_date": dt.date.today(),
                "lifecycle_state": "cancelled",
            }],
            conn=conn,
            brevo_client=brevo,
        )
        print(f"  Sent: {res_5['sent']}, Deduped: {res_5['deduped']}")
        assert res_5["sent"] >= 1, "Location 2 cancellation must dispatch email"

        # 6. Verify audit logs in notifications_log
        print("\n[STEP 6] Verifying notifications_log entries...")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, lifecycle_state, status, provider_message_id, dedup_key
                FROM notifications_log
                WHERE user_id = %s
                ORDER BY id ASC;
                """,
                (user_id,),
            )
            logs = cur.fetchall()
            print(f"  Total audit rows logged: {len(logs)}")
            for row in logs:
                msg_id_mask = f"{row[3][:8]}... (len={len(row[3])})" if row[3] else "None"
                print(f"    - ID {row[0]}: state={row[1]}, status={row[2]}, provider_msg_id={msg_id_mask}, key={row[4]}")
                assert row[2] == "sent", "Status must be 'sent'"
                assert row[3] is not None, "provider_message_id must be populated"

        print("\n[PASS] Real Two-Location Notification Lifecycle Test: 100% SUCCESS")
        return 0

    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM notifications_log WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM subscriptions WHERE user_id = %s;", (user_id,))
            if alert_1_id:
                cur.execute("DELETE FROM alerts WHERE id = %s;", (alert_1_id,))
            if alert_2_id:
                cur.execute("DELETE FROM alerts WHERE id = %s;", (alert_2_id,))
            if evt_1_id:
                cur.execute("DELETE FROM alert_events WHERE id = %s;", (evt_1_id,))
            if evt_2_id:
                cur.execute("DELETE FROM alert_events WHERE id = %s;", (evt_2_id,))
            if created_user:
                cur.execute("DELETE FROM auth.users WHERE id = %s;", (user_id,))
        conn.close()


if __name__ == "__main__":
    sys.exit(run_live_two_location_verification())
