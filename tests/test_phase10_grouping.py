"""Tests for Phase 10: Alert Event Grouping and Lifecycle State Logic.

Authoritative source: AAGAM_PRD.md §6.10 / §11.1
"""

import datetime as dt

from pipeline.events.group import (
    AlertEventRecord,
    group_alerts_into_events,
)
from pipeline.events.lifecycle_state import (
    compute_lifecycle_states,
    update_event_cancellations_and_expiries,
)


class TestEventGrouping:
    def test_new_event_creation(self):
        """Single alert creates a new event with matching start_date and end_date."""
        alerts = [
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-23",
                "severity": "watch",
                "value": 75.5,
            }
        ]
        updated_alerts, events = group_alerts_into_events(alerts, active_events=[])
        assert len(events) == 1
        ev = events[0]
        assert ev.location_id == 1
        assert ev.hazard == "heavy_rain"
        assert ev.status == "active"
        assert ev.severity_peak == "watch"
        assert ev.value_peak == 75.5
        assert ev.start_date == dt.date(2026, 9, 23)
        assert ev.end_date == dt.date(2026, 9, 23)
        assert updated_alerts[0]["event_id"] == ev.id

    def test_consecutive_day_grouping_and_peak_update(self):
        """Consecutive days for same location & hazard group into the same event, updating peak and end_date."""
        alerts = [
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-23",
                "severity": "advisory",
                "value": 45.0,
            },
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-24",
                "severity": "alert",
                "value": 120.0,
            },
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-25",
                "severity": "watch",
                "value": 60.0,
            },
        ]
        updated_alerts, events = group_alerts_into_events(alerts, active_events=[])
        assert len(events) == 1
        ev = events[0]
        assert ev.start_date == dt.date(2026, 9, 23)
        assert ev.end_date == dt.date(2026, 9, 25)
        assert ev.severity_peak == "alert"
        assert ev.value_peak == 120.0
        assert all(a["event_id"] == ev.id for a in updated_alerts)

    def test_separate_events_for_gap_in_days(self):
        """A gap of more than 1 day between alerts creates separate events."""
        alerts = [
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-23",
                "severity": "watch",
                "value": 70.0,
            },
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-26",  # Gap: 24th and 25th missing
                "severity": "alert",
                "value": 115.0,
            },
        ]
        updated_alerts, events = group_alerts_into_events(alerts, active_events=[])
        assert len(events) == 2
        assert events[0].end_date == dt.date(2026, 9, 23)
        assert events[1].start_date == dt.date(2026, 9, 26)
        assert updated_alerts[0]["event_id"] != updated_alerts[1]["event_id"]

    def test_separate_events_for_different_locations_or_hazards(self):
        """Different locations or different hazards on same day produce separate events."""
        alerts = [
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-23",
                "severity": "watch",
                "value": 70.0,
            },
            {
                "location_id": 2,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-23",
                "severity": "watch",
                "value": 65.0,
            },
            {
                "location_id": 1,
                "hazard": "heatwave",
                "valid_date": "2026-09-23",
                "severity": "advisory",
                "value": 41.5,
            },
        ]
        updated_alerts, events = group_alerts_into_events(alerts, active_events=[])
        assert len(events) == 3
        event_ids = {a["event_id"] for a in updated_alerts}
        assert len(event_ids) == 3

    def test_continuity_with_existing_active_event(self):
        """An incoming alert attaches to an existing active event in DB when end_date >= valid_date - 1."""
        existing_ev = AlertEventRecord(
            id=101,
            location_id=5,
            hazard="high_wind",
            status="active",
            severity_peak="watch",
            value_peak=55.0,
            start_date=dt.date(2026, 9, 21),
            end_date=dt.date(2026, 9, 22),
            first_detected_at=dt.datetime(2026, 9, 21, 6, 0, tzinfo=dt.timezone.utc),
            last_updated_at=dt.datetime(2026, 9, 21, 6, 0, tzinfo=dt.timezone.utc),
        )
        incoming_alerts = [
            {
                "location_id": 5,
                "hazard": "high_wind",
                "valid_date": "2026-09-23",  # continuous (22 + 1)
                "severity": "alert",         # more severe
                "value": 68.0,               # higher value
            }
        ]
        updated_alerts, events = group_alerts_into_events(incoming_alerts, active_events=[existing_ev])
        assert len(events) == 1
        ev = events[0]
        assert ev.id == 101
        assert ev.end_date == dt.date(2026, 9, 23)
        assert ev.severity_peak == "alert"
        assert ev.value_peak == 68.0
        assert updated_alerts[0]["event_id"] == 101


class TestLifecycleState:
    def test_lifecycle_new_state(self):
        """Newly detected alert has lifecycle_state = 'new' and previous_severity = None."""
        current_alerts = [
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-24",
                "severity": "watch",
            }
        ]
        computed = compute_lifecycle_states(current_alerts, previous_alerts=[])
        assert len(computed) == 1
        assert computed[0]["lifecycle_state"] == "new"
        assert computed[0]["previous_severity"] is None

    def test_lifecycle_upgraded_state(self):
        """Alert severity increased from watch to alert -> upgraded."""
        previous_alerts = [
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-24",
                "severity": "watch",
            }
        ]
        current_alerts = [
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-24",
                "severity": "alert",
            }
        ]
        computed = compute_lifecycle_states(current_alerts, previous_alerts)
        assert computed[0]["lifecycle_state"] == "upgraded"
        assert computed[0]["previous_severity"] == "watch"

    def test_lifecycle_downgraded_state(self):
        """Alert severity decreased from alert to advisory -> downgraded."""
        previous_alerts = [
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-24",
                "severity": "alert",
            }
        ]
        current_alerts = [
            {
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-24",
                "severity": "advisory",
            }
        ]
        computed = compute_lifecycle_states(current_alerts, previous_alerts)
        assert computed[0]["lifecycle_state"] == "downgraded"
        assert computed[0]["previous_severity"] == "alert"

    def test_lifecycle_unchanged_state(self):
        """Alert severity identical to previous cycle -> unchanged."""
        previous_alerts = [
            {
                "location_id": 1,
                "hazard": "heatwave",
                "valid_date": "2026-09-24",
                "severity": "watch",
            }
        ]
        current_alerts = [
            {
                "location_id": 1,
                "hazard": "heatwave",
                "valid_date": "2026-09-24",
                "severity": "watch",
            }
        ]
        computed = compute_lifecycle_states(current_alerts, previous_alerts)
        assert computed[0]["lifecycle_state"] == "unchanged"
        assert computed[0]["previous_severity"] == "watch"

    def test_lifecycle_cancellation_and_expiry(self):
        """Disappearing future alerts are marked cancelled; past events expire."""
        previous_alerts = [
            {
                "id": 999,
                "location_id": 1,
                "hazard": "heavy_rain",
                "valid_date": "2026-09-25",
                "severity": "watch",
                "event_id": 50,
            }
        ]
        # Current cycle detects no alerts for valid_date 2026-09-25
        current_alerts = []
        today = dt.date(2026, 9, 23)  # Danger was for future 2026-09-25

        # Past event whose end_date is before today
        past_event = AlertEventRecord(
            id=60,
            location_id=1,
            hazard="heatwave",
            status="active",
            severity_peak="alert",
            value_peak=44.0,
            start_date=dt.date(2026, 9, 20),
            end_date=dt.date(2026, 9, 22),  # In the past relative to today (23rd)
            first_detected_at=dt.datetime(2026, 9, 20, tzinfo=dt.timezone.utc),
            last_updated_at=dt.datetime(2026, 9, 22, tzinfo=dt.timezone.utc),
        )

        future_cancelled_event = AlertEventRecord(
            id=50,
            location_id=1,
            hazard="heavy_rain",
            status="active",
            severity_peak="watch",
            value_peak=75.0,
            start_date=dt.date(2026, 9, 25),
            end_date=dt.date(2026, 9, 25),
            first_detected_at=dt.datetime(2026, 9, 22, tzinfo=dt.timezone.utc),
            last_updated_at=dt.datetime(2026, 9, 22, tzinfo=dt.timezone.utc),
        )

        expired_event_ids, cancelled_event_ids, cancelled_alert_ids = update_event_cancellations_and_expiries(
            current_alerts=current_alerts,
            previous_alerts=previous_alerts,
            active_events=[past_event, future_cancelled_event],
            today_date=today,
        )

        assert 999 in cancelled_alert_ids
        assert 60 in expired_event_ids
        assert 50 in cancelled_event_ids
        assert past_event.status == "expired"
        assert future_cancelled_event.status == "cancelled"
