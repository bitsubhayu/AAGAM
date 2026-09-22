"""Lifecycle Alert Notifications Engine (PRD §6.12, §11, Tech Stack §8a).

Dispatches transactional email notifications to subscribers upon alert lifecycle changes:
  - 'new': newly created qualifying alert/event
  - 'upgraded': severity upgrade
  - 'downgraded': severity downgrade
  - 'cancelled': event cancelled prior to arrival

Enforces strict deduplication:
  - 'unchanged' alerts are NEVER notified (FR-NOTIFY-4)
  - Duplicate notifications for the same event and lifecycle state are suppressed via notifications_log
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from core.config import settings
from pipeline.events.group import SEVERITY_RANKS
from pipeline.notify.brevo_client import BrevoClient
from pipeline.notify.templates import format_lifecycle_email

logger = logging.getLogger("aagam.notify.lifecycle")


def process_lifecycle_notifications(
    alerts: Optional[List[Dict[str, Any]]] = None,
    conn: Optional[psycopg2.extensions.connection] = None,
    brevo_client: Optional[BrevoClient] = None,
) -> Dict[str, Any]:
    """Evaluates lifecycle alerts, matches eligible subscribers, and delivers emails with deduplication.

    Args:
        alerts: Optional list of alert dicts from current cycle. If None, queries DB for recent cycle alerts.
        conn: Optional active database connection. If None, connects via settings.DATABASE_URL.
        brevo_client: Optional BrevoClient instance. If None, instantiates default.

    Returns:
        Summary dict containing counts of eligible alerts, sent notifications, and suppressed duplicates.
    """
    client = brevo_client or BrevoClient()
    close_conn = False

    if conn is None:
        if not settings.DATABASE_URL:
            logger.warning("DATABASE_URL not configured. Cannot process notifications.")
            return {"status": "skipped", "reason": "no_database_url"}
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = True
        close_conn = True

    results = {
        "eligible_alerts": 0,
        "recipients_matched": 0,
        "sent": 0,
        "deduped": 0,
        "failed": 0,
    }

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Fetch alerts if not provided
            target_alerts = alerts
            if target_alerts is None:
                cur.execute(
                    """
                    SELECT a.id, a.event_id, a.location_id, a.hazard, a.severity,
                           a.valid_date, a.lead_days, a.value, a.lifecycle_state,
                           a.previous_severity, l.name as location_name
                    FROM alerts a
                    JOIN locations l ON a.location_id = l.id
                    WHERE a.lifecycle_state IN ('new', 'upgraded', 'downgraded', 'cancelled')
                      AND a.created_at >= NOW() - INTERVAL '6 hours'
                    ORDER BY a.id DESC;
                    """
                )
                target_alerts = [dict(row) for row in cur.fetchall()]

            # Fetch locations map for names
            cur.execute("SELECT id, name FROM locations;")
            locations_map = {row["id"]: row["name"] for row in cur.fetchall()}

            # 2. Fetch all active lifecycle subscribers
            cur.execute(
                """
                SELECT user_id, email, location_ids, hazards, min_severity
                FROM subscriptions
                WHERE active = true AND lifecycle_emails = true;
                """
            )
            subscribers = [dict(row) for row in cur.fetchall()]

            for alert in target_alerts:
                lifecycle_state = alert.get("lifecycle_state")
                # Rule FR-NOTIFY-4: Strictly skip unchanged alerts
                if not lifecycle_state or lifecycle_state == "unchanged":
                    continue

                event_id = alert.get("event_id")
                location_id = alert.get("location_id")
                hazard = alert.get("hazard")
                severity = alert.get("severity") or alert.get("severity_peak", "alert")
                alert_sev_rank = SEVERITY_RANKS.get(severity.lower(), 1)
                location_name = alert.get("location_name") or locations_map.get(location_id, f"Location #{location_id}")

                # Fetch full event record if needed
                event_record = None
                if event_id:
                    cur.execute(
                        """
                        SELECT id, location_id, hazard, status, severity_peak, value_peak,
                               start_date, end_date
                        FROM alert_events WHERE id = %s;
                        """,
                        (event_id,),
                    )
                    evt_row = cur.fetchone()
                    if evt_row:
                        event_record = dict(evt_row)

                if not event_record:
                    # Fallback representation from alert
                    event_record = {
                        "id": event_id or alert.get("id"),
                        "location_id": location_id,
                        "hazard": hazard,
                        "severity_peak": severity,
                        "value_peak": alert.get("value"),
                        "start_date": alert.get("valid_date"),
                        "end_date": alert.get("valid_date"),
                    }

                results["eligible_alerts"] += 1

                for sub in subscribers:
                    sub_locs = sub.get("location_ids") or []
                    sub_hazards = sub.get("hazards") or []
                    sub_min_sev = sub.get("min_severity") or "watch"
                    sub_min_rank = SEVERITY_RANKS.get(sub_min_sev.lower(), 2)

                    # Check location filter
                    if location_id not in sub_locs:
                        continue

                    # Check hazard filter
                    if hazard not in sub_hazards:
                        continue

                    # Check severity threshold (unless cancelled, which alerts on drop)
                    if lifecycle_state != "cancelled" and alert_sev_rank < sub_min_rank:
                        continue

                    results["recipients_matched"] += 1
                    user_id = str(sub["user_id"])
                    user_email = sub["email"]

                    # Deduplication key formulation
                    dedup_key = f"lifecycle:{event_record['id']}:{lifecycle_state}:{user_id}"

                    # Check if already notified
                    cur.execute(
                        """
                        SELECT id FROM notifications_log
                        WHERE dedup_key = %s AND status = 'sent'
                        LIMIT 1;
                        """,
                        (dedup_key,),
                    )
                    if cur.fetchone():
                        logger.debug(f"Suppressed duplicate lifecycle notification: {dedup_key}")
                        results["deduped"] += 1
                        continue

                    # Format and deliver email
                    subject, html_body, text_body = format_lifecycle_email(
                        alert_event=event_record,
                        lifecycle_state=lifecycle_state,
                        location_name=location_name,
                        previous_severity=alert.get("previous_severity"),
                    )

                    try:
                        send_res = client.send_email(
                            to_email=user_email,
                            subject=subject,
                            html_content=html_body,
                            text_content=text_body,
                        )
                        msg_id = send_res.get("messageId")

                        # Record in notifications_log
                        cur.execute(
                            """
                            INSERT INTO notifications_log (
                                user_id, kind, event_id, lifecycle_state, sent_at,
                                status, provider_message_id, dedup_key
                            ) VALUES (%s, 'lifecycle', %s, %s, NOW(), 'sent', %s, %s);
                            """,
                            (
                                user_id,
                                event_record.get("id"),
                                lifecycle_state,
                                msg_id,
                                dedup_key,
                            ),
                        )
                        results["sent"] += 1
                    except Exception as err:
                        logger.error(f"Error sending lifecycle notification to {user_email}: {err}")
                        cur.execute(
                            """
                            INSERT INTO notifications_log (
                                user_id, kind, event_id, lifecycle_state, sent_at,
                                status, dedup_key
                            ) VALUES (%s, 'lifecycle', %s, %s, NOW(), 'failed', %s);
                            """,
                            (
                                user_id,
                                event_record.get("id"),
                                lifecycle_state,
                                dedup_key,
                            ),
                        )
                        results["failed"] += 1

    finally:
        if close_conn:
            conn.close()

    logger.info(f"Lifecycle notification processing complete: {results}")
    return results
