"""Daily Summary Notification Job (PRD §6.12, Tech Stack §8a, §12).

Executes daily at ~01:30 UTC (07:00 IST).
Compiles and delivers an interactive morning digest of currently active severe weather
events to subscribers configured for daily summaries.
Enforces once-per-day deduplication via notifications_log.
"""

from __future__ import annotations

import datetime as dt
import logging
import sys
from typing import Any, Dict, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from core.config import settings
from pipeline.events.group import SEVERITY_RANKS
from pipeline.notify.brevo_client import BrevoClient
from pipeline.notify.templates import format_daily_summary_email

logger = logging.getLogger("aagam.notify.daily_summary")


def run_daily_summary_job(
    conn: Optional[psycopg2.extensions.connection] = None,
    brevo_client: Optional[BrevoClient] = None,
    today_date_str: Optional[str] = None,
) -> Dict[str, Any]:
    """Compiles and delivers daily morning weather alert summaries to active subscribers.

    Args:
        conn: Optional psycopg2 database connection.
        brevo_client: Optional BrevoClient instance.
        today_date_str: Optional date string override (YYYY-MM-DD) for testing.

    Returns:
        Summary metrics dict of subscribers processed, sent, and deduped.
    """
    client = brevo_client or BrevoClient()
    close_conn = False

    if conn is None:
        if not settings.DATABASE_URL:
            logger.error("DATABASE_URL is not set.")
            return {"status": "skipped", "reason": "no_database_url"}
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = True
        close_conn = True

    # Compute IST date
    if today_date_str:
        today_ist = today_date_str
    else:
        now_utc = dt.datetime.now(dt.timezone.utc)
        ist_time = now_utc + dt.timedelta(hours=5, minutes=30)
        today_ist = ist_time.strftime("%Y-%m-%d")

    results = {
        "date": today_ist,
        "active_subscribers": 0,
        "sent": 0,
        "deduped": 0,
        "failed": 0,
    }

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Fetch locations map
            cur.execute("SELECT id, name FROM locations;")
            locations_map = {row["id"]: row["name"] for row in cur.fetchall()}

            # 2. Fetch all active daily summary subscribers
            cur.execute(
                """
                SELECT user_id, email, location_ids, hazards, min_severity
                FROM subscriptions
                WHERE active = true AND daily_summary = true;
                """
            )
            subscribers = [dict(row) for row in cur.fetchall()]
            results["active_subscribers"] = len(subscribers)

            # 3. Fetch currently active alert events
            cur.execute(
                """
                SELECT id, location_id, hazard, status, severity_peak, value_peak,
                       start_date, end_date
                FROM alert_events
                WHERE status = 'active'
                ORDER BY severity_peak DESC, start_date ASC;
                """
            )
            active_events = [dict(row) for row in cur.fetchall()]
            for evt in active_events:
                evt["location_name"] = locations_map.get(evt["location_id"], f"Location #{evt['location_id']}")

            for sub in subscribers:
                user_id = str(sub["user_id"])
                user_email = sub["email"]
                sub_locs = sub.get("location_ids") or []
                sub_hazards = sub.get("hazards") or []
                sub_min_sev = sub.get("min_severity") or "watch"
                sub_min_rank = SEVERITY_RANKS.get(sub_min_sev.lower(), 2)

                # Deduplication key for today
                dedup_key = f"daily_summary:{user_id}:{today_ist}"

                # Check deduplication
                cur.execute(
                    """
                    SELECT id FROM notifications_log
                    WHERE dedup_key = %s AND status = 'sent'
                    LIMIT 1;
                    """,
                    (dedup_key,),
                )
                if cur.fetchone():
                    logger.debug(f"Daily summary already sent today to {user_email} (key={dedup_key})")
                    results["deduped"] += 1
                    continue

                # Filter active events matching subscriber preferences
                matching_events = []
                for evt in active_events:
                    if evt["location_id"] not in sub_locs:
                        continue
                    if evt["hazard"] not in sub_hazards:
                        continue
                    evt_rank = SEVERITY_RANKS.get(evt.get("severity_peak", "").lower(), 1)
                    if evt_rank < sub_min_rank:
                        continue
                    matching_events.append(evt)

                # Send summary email
                subject, html_body, text_body = format_daily_summary_email(
                    user_email=user_email,
                    date_str=today_ist,
                    active_events=matching_events,
                )

                try:
                    send_res = client.send_email(
                        to_email=user_email,
                        subject=subject,
                        html_content=html_body,
                        text_content=text_body,
                    )
                    msg_id = send_res.get("messageId")

                    cur.execute(
                        """
                        INSERT INTO notifications_log (
                            user_id, kind, sent_at, status, provider_message_id, dedup_key
                        ) VALUES (%s, 'daily_summary', NOW(), 'sent', %s, %s);
                        """,
                        (user_id, msg_id, dedup_key),
                    )
                    results["sent"] += 1
                except Exception as err:
                    logger.error(f"Failed to deliver daily summary to {user_email}: {err}")
                    cur.execute(
                        """
                        INSERT INTO notifications_log (
                            user_id, kind, sent_at, status, dedup_key
                        ) VALUES (%s, 'daily_summary', NOW(), 'failed', %s);
                        """,
                        (user_id, dedup_key),
                    )
                    results["failed"] += 1

    finally:
        if close_conn:
            conn.close()

    logger.info(f"Daily summary job completed: {results}")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    res = run_daily_summary_job()
    print(f"Daily summary result: {res}")
    sys.exit(0 if res.get("failed", 0) == 0 else 1)
