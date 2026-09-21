"""Inverse-MAE Skill Weight Engine for AAGAM (FR-SKILL-3, PRD §8.2).

Calculates deterministic, transparent inverse-MAE skill weights for each
hierarchically resolved bucket:
    w_m ∝ 1 / (MAE_m + ε)
    w_m = (1 / (MAE_m + ε)) / Σ_k (1 / (MAE_k + ε))

Where ε = 1e-4 prevents division by zero.
Guarantees:
  - w_m >= 0 for all models
  - Σ_m w_m = 1.0 (over valid models in the bucket)
  - If a model has NaN MAE (no valid observations), weight is assigned 0.0
"""

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger("aagam.pipeline.skill.weights")

EPSILON_DEFAULT = 1e-4


def compute_inverse_mae_weights(
    mae_dict: Dict[str, float],
    epsilon: float = EPSILON_DEFAULT,
) -> Dict[str, float]:
    """Calculates normalized inverse-MAE weights for a dictionary of model MAEs.

    Args:
        mae_dict: Dictionary mapping model_name -> MAE value.
        epsilon: Small positive constant to prevent division by zero.

    Returns:
        Dictionary mapping model_name -> normalized weight (summing to 1.0).
        Models with NaN or negative MAE receive weight 0.0.
    """
    raw_inv: Dict[str, float] = {}
    for m, mae in mae_dict.items():
        if mae is not None and not np.isnan(mae) and mae >= 0:
            raw_inv[m] = 1.0 / (float(mae) + epsilon)
        else:
            raw_inv[m] = 0.0

    total_inv = sum(raw_inv.values())

    weights: Dict[str, float] = {}
    if total_inv <= 0:
        # If no model has valid MAE, fall back to equal weight across all provided models
        n_models = len(mae_dict)
        eq_weight = round(1.0 / n_models, 6) if n_models > 0 else 0.0
        for m in mae_dict:
            weights[m] = eq_weight
        return weights

    for m, inv_val in raw_inv.items():
        weights[m] = round(inv_val / total_inv, 6)

    # Re-normalize to ensure exact 1.0 sum accounting for float rounding
    total_w = sum(weights.values())
    if abs(total_w - 1.0) > 1e-9 and total_w > 0:
        diff = 1.0 - total_w
        # Adjust the highest-weighted model slightly
        max_m = max(weights, key=weights.get)
        weights[max_m] = round(weights[max_m] + diff, 6)

    return weights


def build_skill_weights_table(
    resolved_skill_df: pd.DataFrame,
    epsilon: float = EPSILON_DEFAULT,
    method: str = "inverse_mae",
) -> pd.DataFrame:
    """Builds a complete, structured skill weights table from resolved skill metrics.

    Args:
        resolved_skill_df: DataFrame output from HierarchicalFallbackEngine.build_resolved_skill_table().
                           Contains bucket dimensions, model, mae, rmse, bias, n_model,
                           n_bucket, fallback_level, fallback_desc.
        epsilon: Epsilon for inverse-MAE calculation.
        method: Method name recorded in output table ('inverse_mae').

    Returns:
        DataFrame with columns:
          [variable, lead_days, region, season, regime, model, weight,
           mae, rmse, bias, n_samples, fallback_level, fallback_desc, method]
    """
    bucket_cols = ["variable", "lead_days", "region", "season", "regime"]
    records: List[Dict] = []

    grouped = resolved_skill_df.groupby(bucket_cols, observed=True)

    for bucket_key, group in grouped:
        if not isinstance(bucket_key, tuple):
            bucket_key = (bucket_key,)
        bucket_dict = dict(zip(bucket_cols, bucket_key))

        # Extract MAE per model
        mae_dict = {}
        row_map = {}
        for _, row in group.iterrows():
            m = row["model"]
            mae_dict[m] = row["mae"]
            row_map[m] = row

        # Compute weights
        weights = compute_inverse_mae_weights(mae_dict, epsilon=epsilon)

        for m, w in weights.items():
            r = row_map.get(m)
            records.append({
                **bucket_dict,
                "model": m,
                "weight": w,
                "mae": r["mae"] if r is not None else np.nan,
                "rmse": r["rmse"] if r is not None else np.nan,
                "bias": r["bias"] if r is not None else np.nan,
                "n_samples": r["n_model"] if r is not None else 0,
                "n_bucket": r["n_bucket"] if r is not None else 0,
                "fallback_level": r["fallback_level"] if r is not None else 3,
                "fallback_desc": r["fallback_desc"] if r is not None else "drop_region",
                "method": method,
            })

    weights_df = pd.DataFrame(records)
    logger.info(
        f"Computed skill weights table: {len(weights_df)} model-bucket rows "
        f"across {len(grouped)} buckets."
    )
    return weights_df
