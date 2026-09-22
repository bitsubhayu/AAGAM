"""Phase 12 — Track Record Calculation Tests (PRD §12.1, Feature A).

Tests trailing 180-day historical verification track record:
- Trailing 180-day window filtering.
- high_uncertainty hazard exclusion.
- Low-sample (n < 5) handling and flag.
- Accurate hit rate computation: hits / (hits + false_alarms).
- Excludes pending and unverifiable outcomes from denominator.
- No hardcoded production values.
"""

from __future__ import annotations

from datetime import date, timedelta

from api.app.services.track_record import (
    calculate_track_record_stats,
)


def test_high_uncertainty_exclusion():
    """Verify that hazard='high_uncertainty' is excluded per PRD §12.1."""
    stats = calculate_track_record_stats(
        events=[],
        hazard="high_uncertainty",
        region="EAST_NE",
        severity="watch",
    )
    assert stats["applicable"] is False
    assert stats["track_record"] is None
    assert stats["note"] == "not applicable to this hazard type"
    assert "uncertainty" in stats["summary_text"].lower()
    assert stats["n"] == 0
    assert stats["hit_rate"] is None


def test_180_day_window_boundary():
    """Verify that only events within the trailing 180-day window are counted."""
    today = date(2026, 9, 22)
    within_window_date = today - timedelta(days=100)
    outside_window_date = today - timedelta(days=181)

    events = [
        # Inside 180 days: 3 hits, 1 false alarm
        {"hazard": "heavy_rain", "region": "EAST_NE", "severity_peak": "watch", "outcome": "hit", "start_date": within_window_date},
        {"hazard": "heavy_rain", "region": "EAST_NE", "severity_peak": "watch", "outcome": "hit", "start_date": within_window_date},
        {"hazard": "heavy_rain", "region": "EAST_NE", "severity_peak": "watch", "outcome": "hit", "start_date": within_window_date},
        {"hazard": "heavy_rain", "region": "EAST_NE", "severity_peak": "watch", "outcome": "false_alarm", "start_date": within_window_date},
        # Outside 180 days: should be excluded
        {"hazard": "heavy_rain", "region": "EAST_NE", "severity_peak": "watch", "outcome": "hit", "start_date": outside_window_date},
        {"hazard": "heavy_rain", "region": "EAST_NE", "severity_peak": "watch", "outcome": "false_alarm", "start_date": outside_window_date},
    ]

    stats = calculate_track_record_stats(
        events=events,
        hazard="heavy_rain",
        region="EAST_NE",
        severity="watch",
        window_days=180,
        as_of_date=today,
    )

    assert stats["applicable"] is True
    assert stats["hits"] == 3
    assert stats["false_alarms"] == 1
    assert stats["n"] == 4  # 4 within window, 2 outside excluded
    assert stats["low_sample"] is True  # 4 < 5
    assert stats["hit_rate"] == 0.75


def test_low_sample_flag_under_5():
    """Verify that when n < 5, low_sample is True and warning note is set."""
    today = date(2026, 9, 22)
    events = [
        {"hazard": "heatwave", "region": "NORTH_NW", "severity_peak": "alert", "outcome": "hit", "start_date": today - timedelta(days=10)},
        {"hazard": "heatwave", "region": "NORTH_NW", "severity_peak": "alert", "outcome": "hit", "start_date": today - timedelta(days=20)},
    ]

    stats = calculate_track_record_stats(
        events=events,
        hazard="heatwave",
        region="NORTH_NW",
        severity="alert",
        window_days=180,
        as_of_date=today,
    )

    assert stats["n"] == 2
    assert stats["low_sample"] is True
    assert "Not enough past alerts" in stats["summary_text"]
    assert stats["note"] is not None


def test_hit_rate_computation_and_summary_text():
    """Verify PRD §10.4 example: 7 hits of 9 verified true times in last 180 days."""
    today = date(2026, 9, 22)
    events = []
    # 7 hits
    for i in range(7):
        events.append({
            "hazard": "heavy_rain",
            "region": "EAST_NE",
            "severity_peak": "watch",
            "outcome": "hit",
            "start_date": today - timedelta(days=10 + i * 5),
        })
    # 2 false alarms
    for i in range(2):
        events.append({
            "hazard": "heavy_rain",
            "region": "EAST_NE",
            "severity_peak": "watch",
            "outcome": "false_alarm",
            "start_date": today - timedelta(days=15 + i * 10),
        })
    # Pending and unverifiable outcomes must NOT be in denominator n
    events.append({
        "hazard": "heavy_rain",
        "region": "EAST_NE",
        "severity_peak": "watch",
        "outcome": "pending",
        "start_date": today - timedelta(days=2),
    })
    events.append({
        "hazard": "heavy_rain",
        "region": "EAST_NE",
        "severity_peak": "watch",
        "outcome": "unverifiable",
        "start_date": today - timedelta(days=40),
    })

    stats = calculate_track_record_stats(
        events=events,
        hazard="heavy_rain",
        region="EAST_NE",
        severity="watch",
        window_days=180,
        as_of_date=today,
    )

    assert stats["applicable"] is True
    assert stats["hits"] == 7
    assert stats["false_alarms"] == 2
    assert stats["n"] == 9
    assert stats["low_sample"] is False
    assert stats["hit_rate"] == round(7 / 9, 3)  # 0.778
    assert "verified true 7 of 9 times in the last 180 days" in stats["summary_text"]


def test_zero_samples_handling():
    """Verify n=0 results return low_sample=True, hit_rate=None cleanly."""
    today = date(2026, 9, 22)
    stats = calculate_track_record_stats(
        events=[],
        hazard="high_wind",
        region="SOUTH_PENINSULAR",
        severity="alert",
        window_days=180,
        as_of_date=today,
    )
    assert stats["n"] == 0
    assert stats["hits"] == 0
    assert stats["false_alarms"] == 0
    assert stats["hit_rate"] is None
    assert stats["low_sample"] is True
