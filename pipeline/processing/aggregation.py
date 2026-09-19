"""IST Day Aggregation and Alignment Engine for AAGAM.

Strictly adheres to:
- FR-PRE-1:
  * Rainfall: 03:00 -> 03:00 UTC (08:30 -> 08:30 IST next day) 24-hr sum in mm.
  * Tmax: Max of hourly 2m temperature over IST calendar day (00:00 -> 24:00 IST) in °C.
  * wind_max: Max of hourly 10m wind speed over IST calendar day (00:00 -> 24:00 IST) in km/h.
- FR-PRE-2:
  * Alignment key: (location_id, valid_date, lead_days)
  * Missing values remain NaN (NEVER forward-fill).
  * Gap and duplicate detection.
"""

from __future__ import annotations

import logging
from datetime import timedelta, timezone
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("aagam.processing.aggregation")

# IST is UTC + 5:30
IST_OFFSET = timedelta(hours=5, minutes=30)
IST_TZ = timezone(IST_OFFSET)


def aggregate_hourly_to_ist_daily(
    df_hourly: pd.DataFrame,
    rain_col: str = "precipitation",
    temp_col: str = "temperature_2m",
    wind_col: str = "wind_speed_10m",
    time_col: str = "time",
) -> pd.DataFrame:
    """Aggregates hourly time series into daily metrics under IST conventions (FR-PRE-1).

    Args:
        df_hourly: DataFrame with datetime column and weather variables.
        rain_col: Name of precipitation column (mm).
        temp_col: Name of temperature column (°C).
        wind_col: Name of wind speed column (km/h).
        time_col: Name of UTC timestamp column.

    Returns:
        DataFrame with columns: [valid_date, rain_sum, temp_max, wind_max]
    """
    if df_hourly.empty:
        return pd.DataFrame(columns=["valid_date", "rain_sum", "temp_max", "wind_max"])

    df = df_hourly.copy()

    # Ensure UTC datetime
    if not pd.api.types.is_datetime64_any_dtype(df[time_col]):
        df[time_col] = pd.to_datetime(df[time_col], utc=True)
    elif df[time_col].dt.tz is None:
        df[time_col] = df[time_col].dt.tz_localize("UTC")
    else:
        df[time_col] = df[time_col].dt.tz_convert("UTC")

    # IST Calendar Day calculation for Tmax and wind_max
    # IST timestamp = UTC + 5h30m
    df["ts_ist"] = df[time_col] + IST_OFFSET
    df["ist_calendar_date"] = df["ts_ist"].dt.date

    # Rainfall valid_date assignment:
    # IMD convention: 08:30 IST on day D to 08:30 IST on day D+1 represents rainfall for day D.
    # In UTC: 03:00 UTC day D to 03:00 UTC day D+1 represents rainfall for day D.
    # Therefore: subtracting 3 hours from UTC timestamp gives day D for hours [03:00 .. 02:00 next day].
    df["rain_valid_date"] = (df[time_col] - timedelta(hours=3)).dt.date

    # 1. Aggregate Rainfall (03:00 UTC -> 03:00 UTC)
    rain_records = []
    for val_date, group in df.groupby("rain_valid_date"):
        # Check that we have all 24 hours
        if len(group) == 24 and not group[rain_col].isna().any():
            r_sum = float(group[rain_col].sum())
        else:
            # Under FR-PRE-2: missing values remain NaN; never silently interpolate or partial-sum
            r_sum = np.nan
        rain_records.append({"valid_date": val_date, "rain_sum": r_sum})
    df_rain = pd.DataFrame(rain_records)

    # 2. Aggregate Tmax and wind_max (00:00 -> 24:00 IST calendar day)
    temp_wind_records = []
    for cal_date, group in df.groupby("ist_calendar_date"):
        if len(group) == 24 and not group[temp_col].isna().any():
            t_max = float(group[temp_col].max())
        else:
            t_max = np.nan

        if len(group) == 24 and not group[wind_col].isna().any():
            w_max = float(group[wind_col].max())
        else:
            w_max = np.nan

        temp_wind_records.append({
            "valid_date": cal_date,
            "temp_max": t_max,
            "wind_max": w_max,
        })
    df_temp_wind = pd.DataFrame(temp_wind_records)

    # Merge on valid_date
    if df_rain.empty and df_temp_wind.empty:
        return pd.DataFrame(columns=["valid_date", "rain_sum", "temp_max", "wind_max"])
    elif df_rain.empty:
        return df_temp_wind
    elif df_temp_wind.empty:
        return df_rain

    merged = pd.merge(df_rain, df_temp_wind, on="valid_date", how="outer").sort_values("valid_date").reset_index(drop=True)
    return merged


def validate_alignment_keys(
    df: pd.DataFrame,
    keys: Tuple[str, ...] = ("location_id", "valid_date", "lead_days"),
) -> Dict[str, Any]:
    """Validates dataset keys according to FR-PRE-2.

    Checks:
    - Duplicate keys
    - Missing values / gaps
    - Impossible value bounds
    """
    total_rows = len(df)
    for k in keys:
        if k not in df.columns:
            raise KeyError(f"Required alignment key '{k}' not in DataFrame columns: {list(df.columns)}")

    # Detect duplicates
    duplicates_mask = df.duplicated(subset=list(keys), keep=False)
    duplicate_count = int(duplicates_mask.sum())

    # Count NaNs per column
    nan_counts = df.isna().sum().to_dict()

    # Impossible value checks (rain < 0, temp < -40 or > 60, wind < 0)
    anomalies: Dict[str, int] = {}
    if "rain_sum" in df.columns:
        anomalies["rain_negative"] = int((df["rain_sum"] < 0).sum())
    if "temp_max" in df.columns:
        anomalies["temp_out_of_bounds"] = int(((df["temp_max"] < -40) | (df["temp_max"] > 60)).sum())
    if "wind_max" in df.columns:
        anomalies["wind_negative"] = int((df["wind_max"] < 0).sum())

    report = {
        "total_rows": total_rows,
        "duplicate_count": duplicate_count,
        "nan_counts": nan_counts,
        "anomalies": anomalies,
        "is_valid": (duplicate_count == 0 and sum(anomalies.values()) == 0),
    }

    if duplicate_count > 0:
        logger.warning(f"FR-PRE-2 Violation: {duplicate_count} duplicate keys found on {keys}!")

    return report
