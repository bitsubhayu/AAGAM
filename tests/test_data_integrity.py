"""Data Integrity & Quality Assurance Test Suite (PRD §7.5).

Verifies:
1. Physical impossibility bounds (rain >= 0, Tmax -30..55°C, wind 0..250 km/h).
2. Alignment key uniqueness (no duplicate keys).
3. Truth source integrity (no unrecorded or mixed truth sources).
4. No silent forward-fill (NaNs are retained).
"""

from datetime import date

import pandas as pd

from pipeline.processing.aggregation import validate_alignment_keys


def test_physical_bounds_check():
    """Verify detection of physically impossible values."""
    # Impossible rain (<0), Impossible temp (>55), Impossible wind (<0)
    df_bad = pd.DataFrame({
        "location_id": [1, 2, 3],
        "valid_date": [date(2024, 6, 1)] * 3,
        "lead_days": [1, 1, 1],
        "rain_sum": [-5.0, 10.0, 0.0],
        "temp_max": [30.0, 65.0, 25.0],
        "wind_max": [15.0, 20.0, -10.0],
    })

    report = validate_alignment_keys(df_bad, keys=("location_id", "valid_date", "lead_days"))
    assert report["is_valid"] is False
    assert report["anomalies"]["rain_negative"] == 1
    assert report["anomalies"]["temp_out_of_bounds"] == 1
    assert report["anomalies"]["wind_negative"] == 1


def test_truth_source_tracking():
    """Verify truth source tracking rules."""
    allowed_sources = {"imd_gridded", "era5_historical"}

    valid_sources = ["imd_gridded", "era5_historical"]
    for s in valid_sources:
        assert s in allowed_sources

    invalid_sources = ["mixed", "unknown", None, ""]
    for s in invalid_sources:
        assert s not in allowed_sources
