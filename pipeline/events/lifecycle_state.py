"""Lifecycle State & Event Expiry/Cancellation Engine (PRD §6.10, §11.1).

Computes exact lifecycle states by comparing current cycle alerts with the immediately
previous cycle for each (location_id, hazard, valid_date):
  - new: newly flagged alert not present in immediately previous cycle
  - upgraded: alert exists in previous cycle with lower severity
  - downgraded: alert exists in previous cycle with higher severity
  - unchanged: alert exists in previous cycle with identical severity
  - cancelled: alert present in previous cycle for future valid_date disappears before arrival

Also marks active events whose end_date is past today as expired.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Set, Tuple

from pipeline.events.group import SEVERITY_RANKS, AlertEventRecord, _parse_date


def compute_lifecycle_states(
    current_alerts: List[Any],
    previous_alerts: List[Any],
) -> List[Any]:
    """Assigns lifecycle_state and previous_severity to each alert in current_alerts.

    Args:
        current_alerts: Alerts generated in the current pipeline cycle.
        previous_alerts: Alerts from the immediately preceding pipeline cycle.

    Returns:
        The current_alerts list with lifecycle_state and previous_severity populated.
    """
    # Index previous alerts by (location_id, hazard, valid_date)
    prev_map: Dict[Tuple[int, str, dt.date], Any] = {}
    for pa in previous_alerts:
        loc_id = int(getattr(pa, "location_id", None) or pa["location_id"])
        hazard = str(getattr(pa, "hazard", None) or pa["hazard"])
        v_date = _parse_date(getattr(pa, "valid_date", None) or pa["valid_date"])
        prev_map[(loc_id, hazard, v_date)] = pa

    for alert in current_alerts:
        loc_id = int(getattr(alert, "location_id", None) or alert["location_id"])
        hazard = str(getattr(alert, "hazard", None) or alert["hazard"])
        v_date = _parse_date(getattr(alert, "valid_date", None) or alert["valid_date"])
        curr_sev = str(getattr(alert, "severity", None) or alert["severity"]).lower()

        key = (loc_id, hazard, v_date)
        if key in prev_map:
            prev_alert = prev_map[key]
            prev_sev = str(getattr(prev_alert, "severity", None) or prev_alert["severity"]).lower()

            curr_rank = SEVERITY_RANKS.get(curr_sev, 0)
            prev_rank = SEVERITY_RANKS.get(prev_sev, 0)

            if curr_rank > prev_rank:
                l_state = "upgraded"
            elif curr_rank < prev_rank:
                l_state = "downgraded"
            else:
                l_state = "unchanged"

            p_sev = prev_sev
        else:
            l_state = "new"
            p_sev = None

        if isinstance(alert, dict):
            alert["lifecycle_state"] = l_state
            alert["previous_severity"] = p_sev
        else:
            setattr(alert, "lifecycle_state", l_state)
            setattr(alert, "previous_severity", p_sev)

    return current_alerts


def update_event_cancellations_and_expiries(
    current_alerts: List[Any],
    previous_alerts: List[Any],
    active_events: List[AlertEventRecord],
    today_date: Optional[dt.date] = None,
    now: Optional[dt.datetime] = None,
) -> Tuple[List[int], List[int], List[int]]:
    """Evaluates event expiries and cancellations according to PRD §6.10 / §11.1.

    Rules:
      1. Expiry: active events whose end_date < today_date -> expired
      2. Cancellation: if an active event has all remaining forecast dates drop before arrival -> cancelled
      3. For any previous alert whose valid_date >= today_date that dropped out in current cycle ->
         mark alert row lifecycle_state = 'cancelled'

    Returns:
      Tuple of (expired_event_ids, cancelled_event_ids, cancelled_alert_ids)
    """
    if today_date is None:
        today_date = dt.datetime.now(dt.timezone.utc).date()
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)

    # Set of current active (loc_id, hazard, valid_date) keys
    current_active_keys: Set[Tuple[int, str, dt.date]] = set()
    for ca in current_alerts:
        loc_id = int(getattr(ca, "location_id", None) or ca["location_id"])
        hazard = str(getattr(ca, "hazard", None) or ca["hazard"])
        v_date = _parse_date(getattr(ca, "valid_date", None) or ca["valid_date"])
        current_active_keys.add((loc_id, hazard, v_date))

    # Identify dropped future alerts
    cancelled_alert_ids: List[int] = []
    dropped_future_keys: Set[Tuple[int, str, dt.date]] = set()

    for pa in previous_alerts:
        loc_id = int(getattr(pa, "location_id", None) or pa["location_id"])
        hazard = str(getattr(pa, "hazard", None) or pa["hazard"])
        v_date = _parse_date(getattr(pa, "valid_date", None) or pa["valid_date"])

        key = (loc_id, hazard, v_date)
        if key not in current_active_keys and v_date >= today_date:
            dropped_future_keys.add(key)
            pa_id = getattr(pa, "id", None) or pa.get("id")
            if pa_id is not None:
                cancelled_alert_ids.append(int(pa_id))

    expired_event_ids: List[int] = []
    cancelled_event_ids: List[int] = []

    for evt in active_events:
        if evt.status != "active":
            continue

        # Check if event has passed
        if evt.end_date < today_date:
            evt.status = "expired"
            evt.last_updated_at = now
            if evt.id and evt.id > 0:
                expired_event_ids.append(evt.id)
            continue

        # Check if event should be cancelled:
        # If all valid dates covered by the event are in the future and have dropped out
        # (i.e. no current alert exists for this event's location and hazard)
        has_current_active = any(
            loc_id == evt.location_id and hazard == evt.hazard
            for (loc_id, hazard, _) in current_active_keys
        )

        has_dropped_future = any(
            loc_id == evt.location_id and hazard == evt.hazard
            for (loc_id, hazard, _) in dropped_future_keys
        )

        if not has_current_active and has_dropped_future:
            evt.status = "cancelled"
            evt.last_updated_at = now
            if evt.id and evt.id > 0:
                cancelled_event_ids.append(evt.id)

    return expired_event_ids, cancelled_event_ids, cancelled_alert_ids
