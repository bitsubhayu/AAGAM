"""Track Record Evaluation Service (PRD §12.1, Upgrade Pack v1.1 Feature A).

Evaluates the historical 180-day verification track record for alert events:
- For an event's (hazard, location_id's region, severity_peak), queries alert_events
  over trailing 180 days where outcome IN ('hit', 'false_alarm').
- Excludes hazard = 'high_uncertainty' (returns applicable: false, note: "not applicable to this hazard type").
- If n < 5, returns figures with low_sample: true and warning note.
- Calculates hit_rate = hits / (hits + false_alarms).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger("aagam.api.track_record")

DEFAULT_WINDOW_DAYS = 180
MIN_SAMPLE_THRESHOLD = 5


def calculate_track_record_stats(
    events: List[Dict[str, Any]],
    hazard: str,
    region: str,
    severity: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    as_of_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Pure in-memory track record calculation for given events list.

    Args:
        events: List of event dicts with keys: hazard, region, severity_peak, outcome, start_date.
        hazard: Target hazard type.
        region: Target geographic region.
        severity: Target severity level.
        window_days: Trailing day window (default 180).
        as_of_date: Evaluation reference date (defaults to UTC today).
    """
    if hazard == "high_uncertainty":
        return {
            "applicable": False,
            "track_record": None,
            "hazard": hazard,
            "region": region,
            "severity": severity,
            "window_days": window_days,
            "n": 0,
            "hits": 0,
            "false_alarms": 0,
            "hit_rate": None,
            "low_sample": False,
            "note": "not applicable to this hazard type",
            "summary_text": "Not applicable to model spread uncertainty flags.",
        }

    as_of = as_of_date or datetime.now(timezone.utc).date()
    window_start = as_of - timedelta(days=window_days)

    hits = 0
    false_alarms = 0

    for e in events:
        # Check hazard, region, severity
        if e.get("hazard") != hazard:
            continue
        if e.get("region") != region:
            continue
        # Support both 'severity_peak' (db schema) and 'severity' (PRD phrasing)
        evt_sev = e.get("severity_peak") or e.get("severity")
        if evt_sev != severity:
            continue

        # Check date in trailing window
        sd = e.get("start_date")
        if isinstance(sd, str):
            sd = date.fromisoformat(sd)
        elif isinstance(sd, datetime):
            sd = sd.date()

        if sd is None or sd < window_start or sd > as_of:
            continue

        outcome = e.get("outcome")
        if outcome == "hit":
            hits += 1
        elif outcome == "false_alarm":
            false_alarms += 1

    n = hits + false_alarms
    low_sample = n < MIN_SAMPLE_THRESHOLD
    hit_rate = round(hits / n, 3) if n > 0 else None

    if low_sample:
        summary_text = "Not enough past alerts of this type yet to show a track record."
        note = "Not enough past alerts of this type yet to show a track record."
    else:
        summary_text = f"Alerts like this one (same hazard, region, severity) have verified true {hits} of {n} times in the last {window_days} days"
        note = None

    return {
        "applicable": True,
        "hazard": hazard,
        "region": region,
        "severity": severity,
        "window_days": window_days,
        "n": n,
        "hits": hits,
        "false_alarms": false_alarms,
        "hit_rate": hit_rate,
        "low_sample": low_sample,
        "note": note,
        "summary_text": summary_text,
    }


async def fetch_track_record(
    conn: asyncpg.Connection,
    hazard: str,
    region: str,
    severity: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> Dict[str, Any]:
    """Queries database for trailing window track record."""
    if hazard == "high_uncertainty":
        return {
            "applicable": False,
            "track_record": None,
            "hazard": hazard,
            "region": region,
            "severity": severity,
            "window_days": window_days,
            "n": 0,
            "hits": 0,
            "false_alarms": 0,
            "hit_rate": None,
            "low_sample": False,
            "note": "not applicable to this hazard type",
            "summary_text": "Not applicable to model spread uncertainty flags.",
        }

    query = """
        SELECT
            COUNT(*) FILTER (WHERE e.outcome = 'hit') AS hits,
            COUNT(*) FILTER (WHERE e.outcome = 'false_alarm') AS false_alarms
        FROM alert_events e
        JOIN locations l ON e.location_id = l.id
        WHERE e.hazard = $1
          AND l.region = $2
          AND e.severity_peak = $3
          AND e.start_date >= (CURRENT_DATE - ($4 || ' days')::INTERVAL)
          AND e.outcome IN ('hit', 'false_alarm');
    """
    row = await conn.fetchrow(query, hazard, region, severity, str(window_days))
    hits = int(row["hits"] or 0) if row else 0
    false_alarms = int(row["false_alarms"] or 0) if row else 0
    n = hits + false_alarms
    low_sample = n < MIN_SAMPLE_THRESHOLD
    hit_rate = round(hits / n, 3) if n > 0 else None

    if low_sample:
        summary_text = "Not enough past alerts of this type yet to show a track record."
        note = "Not enough past alerts of this type yet to show a track record."
    else:
        summary_text = f"Alerts like this one (same hazard, region, severity) have verified true {hits} of {n} times in the last {window_days} days"
        note = None

    return {
        "applicable": True,
        "hazard": hazard,
        "region": region,
        "severity": severity,
        "window_days": window_days,
        "n": n,
        "hits": hits,
        "false_alarms": false_alarms,
        "hit_rate": hit_rate,
        "low_sample": low_sample,
        "note": note,
        "summary_text": summary_text,
    }
