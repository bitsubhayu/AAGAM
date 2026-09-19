"""Golden Unit Test for IST Aggregation (FR-PRE-1 & FR-PRE-2).

Verifies:
1. Exact rainfall aggregation: 03:00 UTC -> 03:00 UTC next day (08:30 -> 08:30 IST).
   Guarantees rain before 03:00 UTC and at/after 03:00 UTC next day do not bleed into valid_date.
2. Exact Tmax: max hourly 2m temperature over IST calendar day (00:00 -> 24:00 IST).
   Guarantees peak temps outside the IST calendar day do not bleed in.
3. Exact wind_max: max hourly 10m wind speed over IST calendar day (00:00 -> 24:00 IST).
   Guarantees peak winds outside the IST calendar day do not bleed in.
4. Missing value handling: incomplete hours produce NaN, never forward-filling.
"""

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from pipeline.processing.aggregation import aggregate_hourly_to_ist_daily, validate_alignment_keys


def test_golden_ist_day_aggregation():
    """Golden hand-computed test for FR-PRE-1."""
    # Target IST date to test: 2024-07-01
    target_date = date(2024, 7, 1)

    # Generate hourly timestamps covering:
    # 2024-06-30 00:00 UTC to 2024-07-02 23:00 UTC (72 hours total)
    start_utc = datetime(2024, 6, 30, 0, 0, tzinfo=timezone.utc)
    times = [start_utc + timedelta(hours=i) for i in range(72)]

    # Default baseline values:
    # Rain = 0.0 mm, Temp = 25.0 °C, Wind = 10.0 km/h
    rain = [0.0] * 72
    temp = [25.0] * 72
    wind = [10.0] * 72

    # Map each timestamp to its index
    t_idx = {t: i for i, t in enumerate(times)}

    # -------------------------------------------------------------
    # 1. RAINFALL BOUNDARY CONDITIONS (03:00 UTC -> 03:00 UTC)
    # -------------------------------------------------------------
    # Case A: Rain at 2024-07-01 02:00 UTC (07:30 IST) -> Must belong to 2024-06-30
    t_prev_rain = datetime(2024, 7, 1, 2, 0, tzinfo=timezone.utc)
    rain[t_idx[t_prev_rain]] = 20.0

    # Case B: Rain at 2024-07-01 03:00 UTC (08:30 IST) -> First hour of 2024-07-01
    t_rain_1 = datetime(2024, 7, 1, 3, 0, tzinfo=timezone.utc)
    rain[t_idx[t_rain_1]] = 12.5

    # Case C: Rain at 2024-07-01 18:00 UTC (23:30 IST) -> Within 2024-07-01
    t_rain_2 = datetime(2024, 7, 1, 18, 0, tzinfo=timezone.utc)
    rain[t_idx[t_rain_2]] = 25.0

    # Case D: Rain at 2024-07-02 02:00 UTC (07:30 IST next day) -> Last hour of 2024-07-01
    t_rain_3 = datetime(2024, 7, 2, 2, 0, tzinfo=timezone.utc)
    rain[t_idx[t_rain_3]] = 15.0

    # Case E: Rain at 2024-07-02 03:00 UTC (08:30 IST next day) -> Must belong to 2024-07-02
    t_next_rain = datetime(2024, 7, 2, 3, 0, tzinfo=timezone.utc)
    rain[t_idx[t_next_rain]] = 30.0

    # Expected Hand-Computed Rain for 2024-07-01:
    # 12.5 + 25.0 + 15.0 = 52.5 mm
    expected_rain = 52.5

    # -------------------------------------------------------------
    # 2. TEMPERATURE BOUNDARY CONDITIONS (00:00 -> 24:00 IST)
    # IST 2024-07-01 is 2024-06-30 18:30 UTC -> 2024-07-01 18:30 UTC
    # -------------------------------------------------------------
    # Boundary before: 2024-06-30 18:00 UTC (23:30 IST June 30) -> High temp 45.0 °C (Must NOT bleed into July 1)
    t_prev_temp = datetime(2024, 6, 30, 18, 0, tzinfo=timezone.utc)
    temp[t_idx[t_prev_temp]] = 45.0

    # Peak during: 2024-07-01 09:00 UTC (14:30 IST July 1) -> Tmax = 38.5 °C
    t_peak_temp = datetime(2024, 7, 1, 9, 0, tzinfo=timezone.utc)
    temp[t_idx[t_peak_temp]] = 38.5

    # Boundary after: 2024-07-01 19:00 UTC (00:30 IST July 2) -> High temp 42.0 °C (Must NOT bleed into July 1)
    t_next_temp = datetime(2024, 7, 1, 19, 0, tzinfo=timezone.utc)
    temp[t_idx[t_next_temp]] = 42.0

    # Expected Hand-Computed Tmax for 2024-07-01: 38.5 °C
    expected_tmax = 38.5

    # -------------------------------------------------------------
    # 3. WIND SPEED BOUNDARY CONDITIONS (00:00 -> 24:00 IST)
    # -------------------------------------------------------------
    # Boundary before: 2024-06-30 18:00 UTC (23:30 IST June 30) -> High wind 60.0 km/h (Must NOT bleed into July 1)
    wind[t_idx[t_prev_temp]] = 60.0

    # Peak during: 2024-07-01 12:00 UTC (17:30 IST July 1) -> wind_max = 45.2 km/h
    t_peak_wind = datetime(2024, 7, 1, 12, 0, tzinfo=timezone.utc)
    wind[t_idx[t_peak_wind]] = 45.2

    # Boundary after: 2024-07-01 19:00 UTC (00:30 IST July 2) -> High wind 55.0 km/h (Must NOT bleed into July 1)
    wind[t_idx[t_next_temp]] = 55.0

    # Expected Hand-Computed wind_max for 2024-07-01: 45.2 km/h
    expected_wind = 45.2

    # Create test dataframe
    df_hourly = pd.DataFrame({
        "time": times,
        "precipitation": rain,
        "temperature_2m": temp,
        "wind_speed_10m": wind,
    })

    # Run IST aggregation
    df_daily = aggregate_hourly_to_ist_daily(df_hourly)

    # Filter for target date
    row = df_daily[df_daily["valid_date"] == target_date]
    assert not row.empty, f"Target date {target_date} missing from aggregated output!"

    res = row.iloc[0]
    # Assert exact hand-computed values
    assert pytest.approx(res["rain_sum"], rel=1e-4) == expected_rain, (
        f"Rainfall mismatch: expected {expected_rain} mm, got {res['rain_sum']} mm"
    )
    assert pytest.approx(res["temp_max"], rel=1e-4) == expected_tmax, (
        f"Tmax mismatch: expected {expected_tmax} °C, got {res['temp_max']} °C"
    )
    assert pytest.approx(res["wind_max"], rel=1e-4) == expected_wind, (
        f"wind_max mismatch: expected {expected_wind} km/h, got {res['wind_max']} km/h"
    )


def test_missing_values_stay_nan():
    """FR-PRE-2: Missing values must remain NaN and never be silently forward-filled."""
    start_utc = datetime(2024, 7, 1, 0, 0, tzinfo=timezone.utc)
    times = [start_utc + timedelta(hours=i) for i in range(24)]

    # Intentionally insert NaNs
    rain = [1.0] * 23 + [np.nan]
    temp = [30.0] * 24
    wind = [15.0] * 24

    df_hourly = pd.DataFrame({
        "time": times,
        "precipitation": rain,
        "temperature_2m": temp,
        "wind_speed_10m": wind,
    })

    df_daily = aggregate_hourly_to_ist_daily(df_hourly)
    # Because rain had NaN and lacked full 24 hours, rain_sum must be NaN
    assert np.isnan(df_daily.iloc[0]["rain_sum"])


def test_validate_alignment_keys_duplicate_detection():
    """FR-PRE-2: Duplicate detection test."""
    df = pd.DataFrame({
        "location_id": [1, 1, 2],
        "valid_date": [date(2024, 7, 1), date(2024, 7, 1), date(2024, 7, 1)],
        "lead_days": [1, 1, 1],
        "rain_sum": [10.0, 10.0, 5.0],
    })
    report = validate_alignment_keys(df)
    assert report["duplicate_count"] == 2
    assert report["is_valid"] is False
