"""AAGAM Alert Event Outcome Verification (PRD §12.2, Upgrade Pack v1.1).

Computes alert event verification outcomes once observational ground truth
covers all dates in an event's [start_date, end_date] window:
- 'hit': Observed value on at least one day in range crossed the threshold
  associated with the event's severity_peak.
- 'false_alarm': Truth available for the full range, but no day crossed that threshold.
- 'unverifiable': Truth still missing for part of the range after normal observation lag.
- 'pending': end_date has not passed yet.

Sets alert_events.outcome and alert_events.verified_at.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("aagam.pipeline.events.verify")

# Default thresholds calibrated to official IMD / Beaufort definitions
# matching config/thresholds.yaml
HAZARD_SEVERITY_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "heavy_rain": {
        "advisory": 64.5,
        "watch": 64.5,
        "alert": 64.5,
    },
    "heatwave": {
        "advisory": 40.0,
        "watch": 40.0,
        "alert": 45.0,
    },
    "high_wind": {
        "advisory": 50.0,
        "watch": 62.0,
        "alert": 75.0,
    },
    "heavy_rain_3day": {
        "advisory": 64.5,
        "watch": 64.5,
        "alert": 64.5,
    },
}


def get_hazard_threshold(hazard: str, severity: str) -> Optional[float]:
    """Returns cutoff threshold for given hazard and severity."""
    sev_map = HAZARD_SEVERITY_THRESHOLDS.get(hazard)
    if not sev_map:
        return None
    return sev_map.get(severity, sev_map.get("watch", 64.5))


def generate_date_range(start_date: Union[date, str], end_date: Union[date, str]) -> List[date]:
    """Generates inclusive list of dates between start_date and end_date."""
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)

    if start_date > end_date:
        return []

    cur = start_date
    dates = []
    while cur <= end_date:
        dates.append(cur)
        cur += timedelta(days=1)
    return dates


def evaluate_event_outcome(
    event: Dict[str, Any],
    truth_by_date: Dict[date, Optional[float]],
    as_of_date: Optional[date] = None,
) -> Tuple[str, Optional[datetime]]:
    """Evaluates the outcome of a single alert event given observational truth.

    Args:
        event: Dict containing start_date, end_date, hazard, severity_peak.
        truth_by_date: Dict mapping date to observed numerical value (or None if missing).
        as_of_date: Reference date for checking whether end_date has passed (defaults to UTC today).

    Returns:
        (outcome, verified_at): outcome in {'hit', 'false_alarm', 'unverifiable', 'pending'}
        and timestamp when verified (or None if still pending).
    """
    as_of = as_of_date or datetime.now(timezone.utc).date()
    start_d = event["start_date"]
    if isinstance(start_d, str):
        start_d = date.fromisoformat(start_d)
    end_d = event["end_date"]
    if isinstance(end_d, str):
        end_d = date.fromisoformat(end_d)

    # If the event has not yet concluded, status remains pending
    if end_d > as_of:
        return "pending", None

    hazard = event.get("hazard", "")
    severity = event.get("severity_peak", "watch")

    # High uncertainty does not represent a binary meteorological threshold crossing
    if hazard == "high_uncertainty":
        return "unverifiable", datetime.now(timezone.utc)

    threshold = get_hazard_threshold(hazard, severity)
    if threshold is None:
        return "unverifiable", datetime.now(timezone.utc)

    required_dates = generate_date_range(start_d, end_d)
    if not required_dates:
        return "unverifiable", datetime.now(timezone.utc)

    # Check if truth is available for ALL dates in the event window
    observed_values: List[float] = []
    for d in required_dates:
        if d not in truth_by_date or truth_by_date[d] is None:
            # Truth is missing for part of the range
            return "unverifiable", datetime.now(timezone.utc)
        observed_values.append(float(truth_by_date[d]))

    # If observed value on at least one day crossed the threshold -> hit
    if any(val >= threshold for val in observed_values):
        return "hit", datetime.now(timezone.utc)

    # Truth was available for the full range, but no day crossed threshold -> false_alarm
    return "false_alarm", datetime.now(timezone.utc)


def batch_verify_events(
    events: List[Dict[str, Any]],
    truth_records: List[Dict[str, Any]],
    as_of_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Evaluates verification outcomes for multiple events against truth records.

    truth_records should contain: location_id, valid_date, variable, value
    or rain_truth, tmax_truth, wind_max_truth.
    """
    as_of = as_of_date or datetime.now(timezone.utc).date()

    # Index truth by (location_id, hazard_variable, valid_date)
    # Map hazard to truth variable
    hazard_var_map = {
        "heavy_rain": "rain_mm",
        "heavy_rain_3day": "rain_mm",
        "heatwave": "tmax_c",
        "high_wind": "wind_max_kmh",
    }

    truth_lookup: Dict[Tuple[int, str, date], float] = {}
    for r in truth_records:
        loc_id = r.get("location_id")
        raw_vd = r.get("valid_date")
        if isinstance(raw_vd, str):
            vd = date.fromisoformat(raw_vd)
        elif isinstance(raw_vd, datetime):
            vd = raw_vd.date()
        else:
            vd = raw_vd

        var = r.get("variable")
        val = r.get("value")
        if loc_id is not None and vd is not None and var is not None and val is not None:
            truth_lookup[(loc_id, var, vd)] = float(val)

        # Alternative direct columns: rain_truth, tmax_truth, wind_max_truth
        if "rain_truth" in r and r["rain_truth"] is not None:
            truth_lookup[(loc_id, "rain_mm", vd)] = float(r["rain_truth"])
        if "tmax_truth" in r and r["tmax_truth"] is not None:
            truth_lookup[(loc_id, "tmax_c", vd)] = float(r["tmax_truth"])
        if "wind_max_truth" in r and r["wind_max_truth"] is not None:
            truth_lookup[(loc_id, "wind_max_kmh", vd)] = float(r["wind_max_truth"])

    results = []
    for evt in events:
        loc_id = evt.get("location_id")
        hazard = evt.get("hazard", "")
        var_name = hazard_var_map.get(hazard, "rain_mm")

        start_d = evt["start_date"]
        if isinstance(start_d, str):
            start_d = date.fromisoformat(start_d)
        end_d = evt["end_date"]
        if isinstance(end_d, str):
            end_d = date.fromisoformat(end_d)

        req_dates = generate_date_range(start_d, end_d)
        event_truth = {
            d: truth_lookup.get((loc_id, var_name, d))
            for d in req_dates
        }

        outcome, verified_at = evaluate_event_outcome(evt, event_truth, as_of_date=as_of)
        results.append({
            "id": evt.get("id"),
            "outcome": outcome,
            "verified_at": verified_at.isoformat() if verified_at else None,
        })

    return results
