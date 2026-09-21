"""Baseline Evaluation Engine for AAGAM (Phase 2, PRD §7.4, §8.2).

Implements and evaluates three foundational benchmark baselines on strictly
held-out test data (2026-06-21 -> 2026-09-18, 2026 monsoon):
  A. Equal-Weight Mean: Simple average of all available NWP forecasts in each cell.
  B. Best-Single Model: Forecast of the NWP model with lowest historical training MAE.
  C. Inverse-MAE Skill-Weight Baseline: Weighted blend using hierarchically resolved
     inverse-MAE weights, dynamically re-normalized over non-NaN models.

Evaluates and compares against raw NWP models (GFS, ECMWF IFS, ICON, AIFS) across:
  - Overall by variable
  - By lead day (1 to 7)
  - By region (NW, CENTRAL, EAST_NE, SOUTH, HIMALAYAN)
  - By season
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pipeline.skill.scoring import (
    MODEL_COLS,
    NWP_MODELS,
    compute_metrics,
)

logger = logging.getLogger("aagam.pipeline.skill.baselines")

# Strict temporal splits per PRD §7.4
TRAIN_END_DATE = date(2026, 3, 22)
VAL_START_DATE = date(2026, 3, 23)
VAL_END_DATE = date(2026, 6, 20)
TEST_START_DATE = date(2026, 6, 21)
TEST_END_DATE = date(2026, 9, 18)


@dataclass
class DatasetSplits:
    train_df: pd.DataFrame
    val_df: pd.DataFrame
    test_df: pd.DataFrame


def split_dataset_temporally(
    df: pd.DataFrame,
    date_col: str = "valid_date",
    train_end: date = TRAIN_END_DATE,
    val_start: date = VAL_START_DATE,
    val_end: date = VAL_END_DATE,
    test_start: date = TEST_START_DATE,
    test_end: date = TEST_END_DATE,
) -> DatasetSplits:
    """Splits dataset into train, validation, and test subsets based strictly on time.

    Enforces: max(train_date) < min(val_date) < min(test_date)
    Zero random-shuffling or future-data leakage.
    """
    # Ensure dates are date objects for comparison
    dates = pd.to_datetime(df[date_col]).dt.date

    train_mask = dates <= train_end
    val_mask = (dates >= val_start) & (dates <= val_end)
    test_mask = (dates >= test_start) & (dates <= test_end)

    train_df = df[train_mask].copy()
    val_df = df[val_mask].copy()
    test_df = df[test_mask].copy()

    # Integrity assertion
    max_train = train_df[date_col].max()
    min_val = val_df[date_col].min()
    max_val = val_df[date_col].max()
    min_test = test_df[date_col].min()

    assert pd.to_datetime(max_train).date() < pd.to_datetime(min_val).date(), (
        f"Data leakage detected: max(train)={max_train} >= min(val)={min_val}"
    )
    assert pd.to_datetime(max_val).date() < pd.to_datetime(min_test).date(), (
        f"Data leakage detected: max(val)={max_val} >= min(test)={min_test}"
    )

    logger.info(
        f"Temporal splits created successfully:\n"
        f"  Train: {len(train_df):,} rows ({train_df[date_col].min()} to {max_train})\n"
        f"  Val:   {len(val_df):,} rows ({min_val} to {max_val})\n"
        f"  Test:  {len(test_df):,} rows ({min_test} to {test_df[date_col].max()})"
    )

    return DatasetSplits(train_df=train_df, val_df=val_df, test_df=test_df)


def determine_best_single_models(
    train_df: pd.DataFrame,
    group_cols: List[str] = ["variable", "lead_days"],
    models: Optional[List[str]] = None,
) -> Dict[Tuple, str]:
    """Determines the best single NWP model (lowest historical MAE) per group."""
    if models is None:
        models = NWP_MODELS

    best_models: Dict[Tuple, str] = {}
    grouped = train_df.groupby(group_cols, observed=True)

    for key, group in grouped:
        if not isinstance(key, tuple):
            key = (key,)

        truth = group["truth"].to_numpy(dtype=float)
        lowest_mae = float("inf")
        best_m = models[0]

        for m in models:
            col = MODEL_COLS.get(m, f"f_{m}")
            if col in group.columns:
                fc = group[col].to_numpy(dtype=float)
                metrics = compute_metrics(fc, truth)
                if not np.isnan(metrics["mae"]) and metrics["mae"] < lowest_mae:
                    lowest_mae = metrics["mae"]
                    best_m = m

        best_models[key] = best_m

    return best_models


def compute_baseline_forecasts(
    test_df: pd.DataFrame,
    weights_df: pd.DataFrame,
    best_single_map: Dict[Tuple, str],
    models: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Computes forecasts for the three benchmark baselines on the test dataframe.

    Baselines:
      1. f_equal_weight: Mean of valid model forecasts.
      2. f_best_single: Forecast from the best historical model for (variable, lead_days).
      3. f_inverse_mae: Inverse-MAE weighted blend, re-normalized over available models.

    Args:
        test_df: Test dataset.
        weights_df: Fallback-resolved weights table from build_skill_weights_table().
        best_single_map: Mapping from (variable, lead_days) -> best model name.
        models: List of NWP model keys.

    Returns:
        DataFrame with baseline forecast columns added.
    """
    if models is None:
        models = NWP_MODELS

    df = test_df.copy()
    model_cols = [MODEL_COLS[m] for m in models]

    # 1. Equal-Weight Mean: Row-wise mean across available models
    df["f_equal_weight"] = df[model_cols].mean(axis=1, skipna=True)

    # 2. Best-Single Model: Pick the forecast of the best model for (variable, lead_days)
    best_single_series = []
    for _, row in df[["variable", "lead_days"] + model_cols].iterrows():
        key = (row["variable"], row["lead_days"])
        best_m = best_single_map.get(key, "ecmwf_ifs")
        col = MODEL_COLS.get(best_m, f"f_{best_m}")
        val = row[col]

        # If best model forecast is NaN for this row, fallback to row mean
        if pd.isna(val):
            val = row[model_cols].mean(skipna=True)
        best_single_series.append(val)

    df["f_best_single"] = best_single_series

    # 3. Inverse-MAE Skill-Weight Baseline
    # Build lookup dictionary for weights: (variable, lead_days, region, season, regime) -> {model: weight}
    weight_lookup: Dict[Tuple, Dict[str, float]] = {}
    for _, w_row in weights_df.iterrows():
        b_key = (
            w_row["variable"],
            w_row["lead_days"],
            w_row["region"],
            w_row["season"],
            w_row["regime"],
        )
        if b_key not in weight_lookup:
            weight_lookup[b_key] = {}
        weight_lookup[b_key][w_row["model"]] = w_row["weight"]

    # Compute blend row-by-row with dynamic re-normalization for missing models
    blend_values = []
    bucket_cols = ["variable", "lead_days", "region", "season", "regime"]

    for _, row in df[bucket_cols + model_cols].iterrows():
        b_key = (
            row["variable"],
            row["lead_days"],
            row["region"],
            row["season"],
            row["regime"],
        )
        b_weights = weight_lookup.get(b_key, {})

        # Find non-NaN models for this row
        valid_models = [m for m in models if not pd.isna(row[MODEL_COLS[m]])]

        if not valid_models:
            blend_values.append(np.nan)
            continue

        # Extract weights for valid models
        valid_weights = {m: b_weights.get(m, 0.0) for m in valid_models}
        w_sum = sum(valid_weights.values())

        if w_sum > 0:
            # Re-normalize weights so sum = 1.0
            norm_w = {m: valid_weights[m] / w_sum for m in valid_models}
        else:
            # Equal weight fallback among valid models
            norm_w = {m: 1.0 / len(valid_models) for m in valid_models}

        # Weighted blend
        blend_val = sum(norm_w[m] * row[MODEL_COLS[m]] for m in valid_models)
        blend_values.append(blend_val)

    df["f_inverse_mae"] = blend_values
    return df


def evaluate_forecast_candidates(
    df: pd.DataFrame,
    candidate_cols: Dict[str, str],
    group_cols: Optional[List[str]] = None,
    truth_col: str = "truth",
) -> pd.DataFrame:
    """Evaluates multiple forecast candidates against ground truth.

    Args:
        df: DataFrame containing candidate forecasts and truth.
        candidate_cols: Dictionary mapping display_name -> column_name.
                        e.g. {'GFS': 'f_gfs', 'Equal Mean': 'f_equal_weight', ...}
        group_cols: Optional columns to group by (e.g. ['variable', 'lead_days']).
        truth_col: Name of the truth column.

    Returns:
        DataFrame comparing candidates across metrics (MAE, RMSE, bias, n).
    """
    records = []

    if group_cols is None or len(group_cols) == 0:
        # Evaluate globally
        truth = df[truth_col].to_numpy(dtype=float)
        for name, col in candidate_cols.items():
            if col in df.columns:
                fc = df[col].to_numpy(dtype=float)
                metrics = compute_metrics(fc, truth)
                records.append({"candidate": name, **metrics})
    else:
        grouped = df.groupby(group_cols, observed=True)
        for group_key, group in grouped:
            if not isinstance(group_key, tuple):
                group_key = (group_key,)
            group_dict = dict(zip(group_cols, group_key))
            truth = group["truth"].to_numpy(dtype=float)

            for name, col in candidate_cols.items():
                if col in group.columns:
                    fc = group[col].to_numpy(dtype=float)
                    metrics = compute_metrics(fc, truth)
                    records.append({**group_dict, "candidate": name, **metrics})

    return pd.DataFrame(records)
