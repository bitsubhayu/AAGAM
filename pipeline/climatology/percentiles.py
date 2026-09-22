"""AAGAM Climatology Percentiles Calculation Engine (PRD §6.11, §11.2).

Calculates station-level climatological distributions:
- Circular DOY window (±7 days) with seamless calendar wrap-around across year boundaries (DOY 1, 365, 366).
- 1-day metric ('1day') for rain_mm, tmax_c, and wind_max_kmh.
- 3-day accumulated metric ('3day_sum') for rain_mm.
- Minimum history requirement (n_years >= 15): Suppresses percentiles when insufficient data exists.
  Never fabricates percentiles or extrapolates unsupported thresholds.
- Local extremeness rarity mapping:
    >= p99: "roughly a 1-in-100 event"
    >= p95: "roughly a 1-in-20 event"
    >= p90: "roughly a 1-in-10 event"
    < p90 or n_years < 15: None
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

logger = logging.getLogger("aagam.pipeline.climatology.percentiles")

MINIMUM_HISTORY_YEARS: int = 15
DEFAULT_WINDOW_DAYS: int = 7


def is_doy_in_window(obs_doy: int, center_doy: int, window_days: int = DEFAULT_WINDOW_DAYS) -> bool:
    """Determines if obs_doy falls within circular DOY window [center - window_days, center + window_days].

    Correctly handles calendar year wrapping on a 366-day calendar.
    For example:
      - center = 1 with window 7 includes DOYs [359..366] and [1..8].
      - center = 365 with window 7 includes DOYs [358..366] and [1..6].
      - center = 366 with window 7 includes DOYs [359..366] and [1..7].
    """
    if not (1 <= obs_doy <= 366) or not (1 <= center_doy <= 366):
        raise ValueError(f"DOY values must be between 1 and 366 (got obs_doy={obs_doy}, center_doy={center_doy})")

    diff = abs(obs_doy - center_doy)
    circ_dist = min(diff, 366 - diff)
    return circ_dist <= window_days


def compute_3day_rainfall_sums(df: pd.DataFrame, rain_col: str = "rain_truth") -> pd.DataFrame:
    """Computes rolling 3-day accumulated rainfall ending on each day for each location.

    Strict continuity check: A 3-day sum for day t is only valid if observations exist for
    day t-2, t-1, and t (i.e. strictly contiguous dates).
    """
    if df.empty or rain_col not in df.columns:
        return pd.DataFrame(columns=["location_id", "valid_date", "rain_3day_sum", "doy", "year"])

    work_df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(work_df["valid_date"]):
        work_df["valid_date"] = pd.to_datetime(work_df["valid_date"])

    results = []
    for loc_id, group in work_df.groupby("location_id"):
        group = group.sort_values("valid_date").reset_index(drop=True)
        # Set date index for rolling window
        indexed = group.set_index("valid_date")
        # Rolling 3-day window
        # To ensure contiguous dates, verify 2 days prior exists
        rolling_sum = indexed[rain_col].rolling("3D", closed="right").sum()
        rolling_count = indexed[rain_col].rolling("3D", closed="right").count()

        # Only retain windows that have exactly 3 days of observations
        valid_mask = rolling_count == 3
        filtered_sums = rolling_sum.where(valid_mask, np.nan)

        loc_res = pd.DataFrame({
            "location_id": loc_id,
            "valid_date": indexed.index,
            "rain_3day_sum": filtered_sums.values,
            "doy": indexed.index.dayofyear,
            "year": indexed.index.year,
        })
        loc_res = loc_res.dropna(subset=["rain_3day_sum"])
        results.append(loc_res)

    if not results:
        return pd.DataFrame(columns=["location_id", "valid_date", "rain_3day_sum", "doy", "year"])

    return pd.concat(results, ignore_index=True)


def calculate_percentiles(
    values: Union[np.ndarray, Sequence[float]],
    n_years: int,
    min_years: int = MINIMUM_HISTORY_YEARS,
) -> Dict[str, Optional[float]]:
    """Calculates p90, p95, p99, and mean from historical observations.

    Guarded at n_years >= min_years. When n_years < min_years:
    - Does NOT fabricate percentiles.
    - Does NOT extrapolate unsupported thresholds.
    - Returns None for all percentile values.
    """
    if n_years < min_years:
        return {
            "mean": None,
            "p90": None,
            "p95": None,
            "p99": None,
        }

    arr = np.array(values, dtype=float)
    clean_arr = arr[~np.isnan(arr)]

    if len(clean_arr) == 0:
        return {
            "mean": None,
            "p90": None,
            "p95": None,
            "p99": None,
        }

    return {
        "mean": float(np.round(np.mean(clean_arr), 2)),
        "p90": float(np.round(np.percentile(clean_arr, 90), 2)),
        "p95": float(np.round(np.percentile(clean_arr, 95), 2)),
        "p99": float(np.round(np.percentile(clean_arr, 99), 2)),
    }


def get_rarity_label(
    val: Optional[float],
    p90: Optional[float],
    p95: Optional[float],
    p99: Optional[float],
    n_years: int,
    min_years: int = MINIMUM_HISTORY_YEARS,
) -> Optional[str]:
    """Classifies local extremeness/rarity against climatological percentiles.

    Rules:
    - If n_years < 15: returns None (suppressed due to insufficient history).
    - If val < p90 or percentiles missing: returns None.
    - If val >= p99: "roughly a 1-in-100 event"
    - If val >= p95: "roughly a 1-in-20 event"
    - If val >= p90: "roughly a 1-in-10 event"
    """
    if n_years < min_years or p90 is None or p95 is None or p99 is None or val is None:
        return None

    if val >= p99:
        return "roughly a 1-in-100 event"
    elif val >= p95:
        return "roughly a 1-in-20 event"
    elif val >= p90:
        return "roughly a 1-in-10 event"

    return None


def compute_station_climatology(
    df_observations: pd.DataFrame,
    location_id: int,
    variable: str,
    metric: str = "1day",
    value_col: Optional[str] = None,
    min_years: int = MINIMUM_HISTORY_YEARS,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> List[Dict[str, Any]]:
    """Computes all 366 DOY climatology rows for a single station, variable, and metric.

    Returns a list of dicts matching the `climatology_percentiles` database schema.
    """
    if df_observations.empty:
        return []

    # Map variable to default value column if not specified
    if value_col is None:
        col_map = {
            "rain_mm": "rain_truth",
            "tmax_c": "tmax_truth",
            "wind_max_kmh": "wind_max_truth",
        }
        value_col = col_map.get(variable, "value")

    df_loc = df_observations[df_observations["location_id"] == location_id].copy()
    if df_loc.empty:
        return []

    if not pd.api.types.is_datetime64_any_dtype(df_loc["valid_date"]):
        df_loc["valid_date"] = pd.to_datetime(df_loc["valid_date"])

    df_loc["doy"] = df_loc["valid_date"].dt.dayofyear
    df_loc["year"] = df_loc["valid_date"].dt.year

    # If metric is 3day_sum, precompute 3-day sums
    if metric == "3day_sum":
        df_prepared = compute_3day_rainfall_sums(df_loc, rain_col=value_col)
        calc_col = "rain_3day_sum"
    else:
        df_prepared = df_loc.dropna(subset=[value_col]).copy()
        calc_col = value_col

    records: List[Dict[str, Any]] = []
    now_ts = dt.datetime.now(dt.timezone.utc).isoformat()

    # Pre-extract numpy arrays for fast vectorized window selection
    if df_prepared.empty:
        # Generate empty rows for all 366 DOYs with n_years=0
        for center_doy in range(1, 367):
            records.append({
                "location_id": location_id,
                "variable": variable,
                "metric": metric,
                "doy_window": center_doy,
                "mean": None,
                "p90": None,
                "p95": None,
                "p99": None,
                "n_years": 0,
                "computed_at": now_ts,
            })
        return records

    obs_doys = df_prepared["doy"].to_numpy()
    obs_years = df_prepared["year"].to_numpy()
    obs_vals = df_prepared[calc_col].to_numpy(dtype=float)

    for center_doy in range(1, 367):
        # Circular distance vectorized
        diff = np.abs(obs_doys - center_doy)
        circ_dist = np.minimum(diff, 366 - diff)
        in_window = circ_dist <= window_days

        if not np.any(in_window):
            n_years = 0
            stats = {"mean": None, "p90": None, "p95": None, "p99": None}
        else:
            window_years = obs_years[in_window]
            n_years = int(len(np.unique(window_years)))
            window_vals = obs_vals[in_window]
            stats = calculate_percentiles(window_vals, n_years=n_years, min_years=min_years)

        records.append({
            "location_id": location_id,
            "variable": variable,
            "metric": metric,
            "doy_window": center_doy,
            "mean": stats["mean"],
            "p90": stats["p90"],
            "p95": stats["p95"],
            "p99": stats["p99"],
            "n_years": n_years,
            "computed_at": now_ts,
        })

    return records
