"""Deterministic Alert Event Grouping Engine (PRD §6.10, §11.1).

Groups consecutive flagged days per (location_id, hazard) into cohesive alert_events.
Deterministic rules:
- For each newly flagged (location_id, hazard, valid_date):
  - If an active alert_event exists for the same (location_id, hazard) and end_date >= valid_date - 1:
      attach alert row to that event
      extend end_date to valid_date when later
      extend start_date to valid_date when earlier
      update severity_peak when more severe
      update value_peak when higher
      update last_updated_at
  - Otherwise:
      create a new alert_event with start_date = end_date = valid_date,
      severity_peak = alert.severity, value_peak = alert.value,
      status = 'active', outcome = 'pending'.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

SEVERITY_RANKS = {
    "advisory": 1,
    "watch": 2,
    "alert": 3,
}


@dataclass
class AlertEventRecord:
    """Represents an alert_events database entity."""

    id: Optional[int]
    location_id: int
    hazard: str
    status: str  # 'active' | 'expired' | 'cancelled'
    severity_peak: str  # 'advisory' | 'watch' | 'alert'
    value_peak: Optional[float]
    start_date: dt.date
    end_date: dt.date
    first_detected_at: dt.datetime
    last_updated_at: dt.datetime
    outcome: str = "pending"  # 'hit' | 'false_alarm' | 'pending' | 'unverifiable'
    verified_at: Optional[dt.datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "location_id": self.location_id,
            "hazard": self.hazard,
            "status": self.status,
            "severity_peak": self.severity_peak,
            "value_peak": self.value_peak,
            "start_date": self.start_date.isoformat() if isinstance(self.start_date, dt.date) else str(self.start_date),
            "end_date": self.end_date.isoformat() if isinstance(self.end_date, dt.date) else str(self.end_date),
            "first_detected_at": self.first_detected_at.isoformat(),
            "last_updated_at": self.last_updated_at.isoformat(),
            "outcome": self.outcome,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }


def _parse_date(d: Any) -> dt.date:
    """Safely converts string or datetime/date to datetime.date."""
    if isinstance(d, dt.date) and not isinstance(d, dt.datetime):
        return d
    if isinstance(d, dt.datetime):
        return d.date()
    return dt.date.fromisoformat(str(d).split("T")[0])


def group_alerts_into_events(
    alerts: List[Any],
    active_events: List[AlertEventRecord],
    now: Optional[dt.datetime] = None,
) -> Tuple[List[Any], List[AlertEventRecord]]:
    """Groups alerts into alert_events and updates event peaks and date ranges.

    Args:
        alerts: List of alert objects or dicts for the current cycle.
        active_events: Existing active AlertEventRecords loaded from database.
        now: Optional current timestamp (defaults to UTC now).

    Returns:
        Tuple of (alerts_with_event_assignment, updated_and_new_active_events).
    """
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)

    # Work with copies of active events to avoid accidental external mutation
    events_pool: List[AlertEventRecord] = list(active_events)

    # Sort alerts chronologically so consecutive days are evaluated in order
    def _alert_sort_key(a: Any) -> Tuple[int, str, dt.date]:
        loc_id = getattr(a, "location_id", None) or a["location_id"]
        hazard = getattr(a, "hazard", None) or a["hazard"]
        v_date = _parse_date(getattr(a, "valid_date", None) or a["valid_date"])
        return (int(loc_id), str(hazard), v_date)

    sorted_alerts = sorted(alerts, key=_alert_sort_key)

    # Temporary negative ID generator for newly created in-memory events before DB insert
    new_event_id_seq = -1

    for alert in sorted_alerts:
        loc_id = int(getattr(alert, "location_id", None) or alert["location_id"])
        hazard = str(getattr(alert, "hazard", None) or alert["hazard"])
        v_date = _parse_date(getattr(alert, "valid_date", None) or alert["valid_date"])
        severity = str(getattr(alert, "severity", None) or alert["severity"]).lower()
        val = getattr(alert, "value", None) if hasattr(alert, "value") else alert.get("value")
        val = float(val) if val is not None else None

        # Search for an active event matching location and hazard with end_date >= valid_date - 1
        matched_event: Optional[AlertEventRecord] = None

        # Find best matching event: must be same location, same hazard, active status,
        # and continuity condition: end_date >= valid_date - 1 (and start_date <= valid_date + 1)
        for evt in events_pool:
            if (
                evt.status == "active"
                and evt.location_id == loc_id
                and evt.hazard == hazard
                and evt.end_date >= v_date - dt.timedelta(days=1)
                and evt.start_date <= v_date + dt.timedelta(days=1)
            ):
                matched_event = evt
                break

        if matched_event is not None:
            # Update event bounds
            if v_date > matched_event.end_date:
                matched_event.end_date = v_date
            if v_date < matched_event.start_date:
                matched_event.start_date = v_date

            # Update severity peak if more severe
            curr_rank = SEVERITY_RANKS.get(severity, 0)
            peak_rank = SEVERITY_RANKS.get(matched_event.severity_peak, 0)
            if curr_rank > peak_rank:
                matched_event.severity_peak = severity

            # Update value peak if higher
            if val is not None:
                if matched_event.value_peak is None or val > matched_event.value_peak:
                    matched_event.value_peak = val

            matched_event.last_updated_at = now

            # Attach event reference to alert
            if isinstance(alert, dict):
                alert["event_id"] = matched_event.id
                alert["_event_ref"] = matched_event
            else:
                setattr(alert, "event_id", matched_event.id)
                setattr(alert, "_event_ref", matched_event)

        else:
            # Create a new alert_event
            new_evt = AlertEventRecord(
                id=new_event_id_seq,
                location_id=loc_id,
                hazard=hazard,
                status="active",
                severity_peak=severity,
                value_peak=val,
                start_date=v_date,
                end_date=v_date,
                first_detected_at=now,
                last_updated_at=now,
                outcome="pending",
                verified_at=None,
            )
            new_event_id_seq -= 1
            events_pool.append(new_evt)

            # Attach event reference to alert
            if isinstance(alert, dict):
                alert["event_id"] = new_evt.id
                alert["_event_ref"] = new_evt
            else:
                setattr(alert, "event_id", new_evt.id)
                setattr(alert, "_event_ref", new_evt)

    return sorted_alerts, events_pool
