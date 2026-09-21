"""Skill Scoring Engine for AAGAM (FR-SKILL-1).

Computes MAE, RMSE, bias, and valid observation counts (n) for each NWP model
across hierarchical buckets and configurable temporal evaluation windows.
Strictly respects missing observations: NaNs are preserved and never imputed.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("aagam.pipeline.skill.scoring")

NWP_MODELS = ["gfs", "ecmwf_ifs", "icon", "aifs"]
MODEL_COLS = {
    "gfs": "f_gfs",
    "ecmwf_ifs": "f_ecmwf_ifs",
    "icon": "f_icon",
    "aifs": "f_aifs",
}


def compute_metrics(
    forecast: np.ndarray,
    truth: np.ndarray,
) -> Dict[str, float]:
    """Computes MAE, RMSE, bias, and sample count for valid (non-NaN) pairs.

    Args:
        forecast: Array of model forecasts.
        truth: Array of ground truth observations.

    Returns:
        Dictionary containing 'mae', 'rmse', 'bias', and 'n'.
        If n == 0, returns NaN for metrics and 0 for n.
    """
    valid_mask = ~np.isnan(forecast) & ~np.isnan(truth)
    n = int(np.sum(valid_mask))

    if n == 0:
        return {
            "mae": np.nan,
            "rmse": np.nan,
            "bias": np.nan,
            "n": 0,
        }

    f_valid = forecast[valid_mask]
    y_valid = truth[valid_mask]
    diff = f_valid - y_valid

    mae = float(np.mean(np.abs(diff)))
    rmse = float(np.sqrt(np.mean(diff**2)))
    bias = float(np.mean(diff))

    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "bias": round(bias, 4),
        "n": n,
    }


def filter_by_trailing_window(
    df: pd.DataFrame,
    cutoff_date: Optional[date] = None,
    window_days: int = 60,
    date_col: str = "valid_date",
) -> pd.DataFrame:
    """Filters dataset to a trailing evaluation window.

    Args:
        df: Input DataFrame containing date_col.
        cutoff_date: End date of the trailing window (defaults to max date in df).
        window_days: Window length in calendar days (default 60).
        date_col: Name of the date column.

    Returns:
        Filtered DataFrame spanning [cutoff_date - window_days + 1, cutoff_date].
    """
    if df.empty:
        return df

    if cutoff_date is None:
        cutoff_date = df[date_col].max()
        if isinstance(cutoff_date, pd.Timestamp):
            cutoff_date = cutoff_date.date()

    start_date = cutoff_date - timedelta(days=window_days - 1)
    mask = (df[date_col] >= start_date) & (df[date_col] <= cutoff_date)
    filtered = df[mask].copy()

    logger.info(
        f"Filtered trailing window: {start_date} to {cutoff_date} "
        f"({window_days} days): {len(filtered)} rows retained."
    )
    return filtered


def compute_model_skills_for_group(
    group_df: pd.DataFrame,
    models: Optional[List[str]] = None,
    truth_col: str = "truth",
) -> List[Dict[str, any]]:
    """Computes skill metrics for all models in a single bucket DataFrame."""
    if models is None:
        models = NWP_MODELS

    truth = group_df[truth_col].to_numpy(dtype=float)
    results = []

    for m in models:
        col = MODEL_COLS.get(m, f"f_{m}")
        if col not in group_df.columns:
            continue

        forecast = group_df[col].to_numpy(dtype=float)
        metrics = compute_metrics(forecast, truth)
        metrics["model"] = m
        results.append(metrics)

    return results


def compute_skill_table_for_level(
    df: pd.DataFrame,
    group_cols: List[str],
    models: Optional[List[str]] = None,
    truth_col: str = "truth",
) -> pd.DataFrame:
    """Computes model skill metrics grouped by specified dimension columns.

    Args:
        df: DataFrame containing forecasts and truth.
        group_cols: List of grouping columns defining the bucket granularity.
        models: List of model identifiers.
        truth_col: Name of the truth column.

    Returns:
        DataFrame with group_cols + [model, mae, rmse, bias, n].
    """
    if models is None:
        models = NWP_MODELS

    records = []
    # Use groupby for fast computation
    grouped = df.groupby(group_cols, observed=True)

    for group_key, group_df in grouped:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)

        key_dict = dict(zip(group_cols, group_key))
        truth = group_df[truth_col].to_numpy(dtype=float)

        for m in models:
            col = MODEL_COLS.get(m, f"f_{m}")
            if col not in group_df.columns:
                continue

            fc = group_df[col].to_numpy(dtype=float)
            m_metrics = compute_metrics(fc, truth)

            row = {**key_dict, "model": m, **m_metrics}
            records.append(row)

    res_df = pd.DataFrame(records)
    return res_df
