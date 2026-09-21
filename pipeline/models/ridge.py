"""Stacking Ridge Regression Engine for AAGAM (Phase 3, PRD §8.3, FR-BLEND-3, FR-BLEND-4).

Implements constrained Ridge stacking:
  - Features: [f_gfs, f_ecmwf_ifs, f_icon, f_aifs]
  - Target: truth
  - Granularity: One fit per bucket defined by Phase 2 hierarchical fallback
  - Constraints: positive=True, fit_intercept=False, coefficients normalized to sum=1.0
  - Hyperparameter tuning: 4-fold rolling-origin time-series CV on historical training data
  - Missing-model inference: Dynamic re-normalization over available models with degraded=True
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from pipeline.skill.fallback import HierarchicalFallbackEngine
from pipeline.skill.scoring import MODEL_COLS, NWP_MODELS

logger = logging.getLogger("aagam.pipeline.models.ridge")

CANDIDATE_ALPHAS = [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
DEFAULT_ALPHA = 1.0


@dataclass
class BucketRidgeModel:
    variable: str
    lead_days: int
    region: str
    season: str
    regime: str
    alpha: float
    weights: Dict[str, float]
    fallback_level: int
    fallback_desc: str
    n_samples: int
    cv_mae: float


def rolling_origin_cv_ridge(
    df_bucket: pd.DataFrame,
    date_col: str = "valid_date",
    models: Optional[List[str]] = None,
    candidate_alphas: Optional[List[float]] = None,
    n_splits: int = 4,
) -> float:
    """Selects best Ridge alpha using strictly ordered rolling-origin time-series CV.

    Never random-shuffles. Folds expand forward in chronological order.
    """
    if models is None:
        models = NWP_MODELS
    if candidate_alphas is None:
        candidate_alphas = CANDIDATE_ALPHAS

    model_cols = [MODEL_COLS[m] for m in models]

    # Filter to complete cases for training
    valid_mask = ~df_bucket["truth"].isna()
    # At least one model forecast must be valid
    valid_mask &= df_bucket[model_cols].notna().any(axis=1)

    df_clean = df_bucket[valid_mask].sort_values(date_col).copy()
    n_total = len(df_clean)

    # If insufficient samples for 4-fold rolling CV, return default alpha
    if n_total < 40:
        return DEFAULT_ALPHA

    # Unique chronological time steps
    unique_dates = df_clean[date_col].drop_duplicates().sort_values().to_list()
    n_dates = len(unique_dates)
    if n_dates < n_splits + 1:
        return DEFAULT_ALPHA

    # Determine date split thresholds for n_splits folds
    # Fold 1: train 40% dates, test next 15%
    # Fold 2: train 55% dates, test next 15%
    # Fold 3: train 70% dates, test next 15%
    # Fold 4: train 85% dates, test last 15%
    step = int(np.floor(0.15 * n_dates))
    if step < 1:
        step = 1

    alpha_maes: Dict[float, List[float]] = {a: [] for a in candidate_alphas}

    for fold in range(n_splits):
        val_end_idx = min(n_dates, int(0.40 * n_dates) + (fold + 1) * step)
        val_start_idx = max(1, val_end_idx - step)
        train_end_idx = val_start_idx

        train_dates = set(unique_dates[:train_end_idx])
        val_dates = set(unique_dates[val_start_idx:val_end_idx])

        train_sub = df_clean[df_clean[date_col].isin(train_dates)]
        val_sub = df_clean[df_clean[date_col].isin(val_dates)]

        if len(train_sub) < 10 or len(val_sub) < 5:
            continue

        # Prepare X, y
        # Fill missing model forecasts with row-mean during CV so Ridge can fit
        X_train = train_sub[model_cols].copy()
        row_means_train = X_train.mean(axis=1, skipna=True)
        for col in model_cols:
            X_train[col] = X_train[col].fillna(row_means_train)
        y_train = train_sub["truth"].to_numpy(dtype=float)

        X_val = val_sub[model_cols].copy()
        row_means_val = X_val.mean(axis=1, skipna=True)
        for col in model_cols:
            X_val[col] = X_val[col].fillna(row_means_val)
        y_val = val_sub["truth"].to_numpy(dtype=float)

        for a in candidate_alphas:
            try:
                clf = Ridge(alpha=a, positive=True, fit_intercept=False)
                clf.fit(X_train.to_numpy(), y_train)

                # Normalize weights
                w = clf.coef_
                w_sum = np.sum(w)
                if w_sum > 0:
                    w_norm = w / w_sum
                else:
                    w_norm = np.ones(len(models)) / len(models)

                y_pred = X_val.to_numpy() @ w_norm
                fold_mae = float(np.mean(np.abs(y_pred - y_val)))
                alpha_maes[a].append(fold_mae)
            except Exception:
                continue

    # Find alpha with lowest mean CV MAE
    best_alpha = DEFAULT_ALPHA
    lowest_mae = float("inf")
    for a, maes in alpha_maes.items():
        if len(maes) > 0:
            mean_mae = float(np.mean(maes))
            if mean_mae < lowest_mae:
                lowest_mae = mean_mae
                best_alpha = a

    return best_alpha


def fit_ridge_for_bucket(
    df_bucket: pd.DataFrame,
    alpha: float,
    models: Optional[List[str]] = None,
) -> Tuple[Dict[str, float], float]:
    """Fits non-negative constrained Ridge on bucket data with normalized weights."""
    if models is None:
        models = NWP_MODELS

    model_cols = [MODEL_COLS[m] for m in models]
    valid_mask = ~df_bucket["truth"].isna() & df_bucket[model_cols].notna().any(axis=1)
    df_clean = df_bucket[valid_mask].copy()

    if len(df_clean) == 0:
        eq_w = {m: round(1.0 / len(models), 6) for m in models}
        return eq_w, 0.0

    X = df_clean[model_cols].copy()
    row_means = X.mean(axis=1, skipna=True)
    for col in model_cols:
        X[col] = X[col].fillna(row_means)
    y = df_clean["truth"].to_numpy(dtype=float)

    clf = Ridge(alpha=alpha, positive=True, fit_intercept=False)
    clf.fit(X.to_numpy(), y)

    coefs = clf.coef_
    total_coef = np.sum(coefs)

    weights: Dict[str, float] = {}
    if total_coef > 0:
        for m, c in zip(models, coefs):
            weights[m] = round(float(c / total_coef), 6)
    else:
        for m in models:
            weights[m] = round(1.0 / len(models), 6)

    # Re-normalize to exact 1.0 accounting for float rounding
    w_sum = sum(weights.values())
    if abs(w_sum - 1.0) > 1e-9 and w_sum > 0:
        max_m = max(weights, key=weights.get)
        weights[max_m] = round(weights[max_m] + (1.0 - w_sum), 6)

    # Compute training MAE
    pred = X.to_numpy() @ np.array([weights[m] for m in models])
    train_mae = float(np.mean(np.abs(pred - y)))

    return weights, round(train_mae, 4)


class RidgeStackingEngine:
    """Manages hierarchical fallback, CV tuning, and inference for Ridge stacking."""

    def __init__(
        self,
        train_df: pd.DataFrame,
        fallback_engine: HierarchicalFallbackEngine,
        models: Optional[List[str]] = None,
    ) -> None:
        self.train_df = train_df
        self.fallback_engine = fallback_engine
        self.models = models or NWP_MODELS
        self.bucket_models: Dict[Tuple, BucketRidgeModel] = {}
        self._fit_all_buckets()
        # Free memory and prevent pickling 660k DataFrame
        self.train_df = None
        self.fallback_engine = None

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["train_df"] = None
        state["fallback_engine"] = None
        return state

    def _fit_all_buckets(self) -> None:
        """Trains Ridge for all fallback-resolved buckets present in the training set."""
        logger.info("Fitting Ridge stacking models across fallback-resolved buckets...")
        l0_cols = ["variable", "lead_days", "region", "season", "regime"]
        unique_buckets = self.train_df[l0_cols].drop_duplicates().sort_values(l0_cols)

        # Cache level-fitted models to avoid duplicate fitting when fallback occurs
        level_cache: Dict[Tuple[int, Tuple], Tuple[float, Dict[str, float], float]] = {}

        for _, b in unique_buckets.iterrows():
            var, lead, reg, seas, regime = (
                b["variable"],
                b["lead_days"],
                b["region"],
                b["season"],
                b["regime"],
            )

            # Resolve fallback level from Phase 2 engine
            res = self.fallback_engine.resolve_bucket(var, lead, reg, seas, regime)
            res_level = res["resolved_level"]
            res_dims = res["resolved_dims"]
            res_desc = res["resolved_level_desc"]
            n_samples = res["n_samples"]

            # Key for cache
            dim_vals = tuple(res["query"][col] for col in res_dims)
            cache_key = (res_level, dim_vals)

            if cache_key in level_cache:
                best_alpha, weights, train_mae = level_cache[cache_key]
            else:
                # Filter train_df to resolved slice
                mask = pd.Series(True, index=self.train_df.index)
                for col in res_dims:
                    mask &= (self.train_df[col] == res["query"][col])
                df_slice = self.train_df[mask]

                # Select alpha via 4-fold rolling origin CV
                best_alpha = rolling_origin_cv_ridge(df_slice, models=self.models)
                # Fit final Ridge on resolved slice
                weights, train_mae = fit_ridge_for_bucket(df_slice, alpha=best_alpha, models=self.models)
                level_cache[cache_key] = (best_alpha, weights, train_mae)

            b_key = (var, lead, reg, seas, regime)
            self.bucket_models[b_key] = BucketRidgeModel(
                variable=var,
                lead_days=lead,
                region=reg,
                season=seas,
                regime=regime,
                alpha=best_alpha,
                weights=weights,
                fallback_level=res_level,
                fallback_desc=res_desc,
                n_samples=n_samples,
                cv_mae=train_mae,
            )

        logger.info(
            f"Successfully fitted Ridge stacking engine: {len(self.bucket_models)} buckets "
            f"({len(level_cache)} unique models after fallback)."
        )

    def predict_row(
        self,
        row: Dict[str, Any],
    ) -> Tuple[float, Dict[str, float], bool]:
        """Predicts single row using Ridge weights with dynamic re-normalization.

        Returns:
            Tuple of (prediction, normalized_weights, degraded_flag).
        """
        b_key = (
            row["variable"],
            row["lead_days"],
            row["region"],
            row["season"],
            row["regime"],
        )
        model_obj = self.bucket_models.get(b_key)
        if model_obj is None:
            # Fallback to equal weight
            base_weights = {m: 1.0 / len(self.models) for m in self.models}
        else:
            base_weights = model_obj.weights

        # Check model availability in row
        valid_models = []
        missing_models = []
        for m in self.models:
            val = row.get(MODEL_COLS[m])
            if val is not None and not pd.isna(val):
                valid_models.append(m)
            else:
                missing_models.append(m)

        degraded = len(missing_models) > 0

        if not valid_models:
            return np.nan, {m: 0.0 for m in self.models}, True

        # Dynamic re-normalization over available models (FR-BLEND-4)
        valid_w_sum = sum(base_weights.get(m, 0.0) for m in valid_models)
        norm_weights: Dict[str, float] = {}

        if valid_w_sum > 0:
            for m in self.models:
                if m in valid_models:
                    norm_weights[m] = base_weights.get(m, 0.0) / valid_w_sum
                else:
                    norm_weights[m] = 0.0
        else:
            # Equal weight among available models
            eq_val = 1.0 / len(valid_models)
            for m in self.models:
                norm_weights[m] = eq_val if m in valid_models else 0.0

        # Compute prediction
        pred = sum(norm_weights[m] * row[MODEL_COLS[m]] for m in valid_models)
        return float(pred), norm_weights, degraded

    def predict_dataframe(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Vectorized/batched prediction across DataFrame.

        Returns:
            Tuple of (predictions_array, degraded_flags_array).
        """
        preds = np.empty(len(df), dtype=float)
        degraded = np.empty(len(df), dtype=bool)

        cols = ["variable", "lead_days", "region", "season", "regime"] + [MODEL_COLS[m] for m in self.models]
        df_sub = df[cols].to_dict(orient="records")

        for idx, row in enumerate(df_sub):
            p, _, deg = self.predict_row(row)
            preds[idx] = p
            degraded[idx] = deg

        return preds, degraded

    def to_dataframe(self) -> pd.DataFrame:
        """Exports all fitted Ridge models into a structured DataFrame."""
        rows = []
        for b_key, m_obj in self.bucket_models.items():
            for m, w in m_obj.weights.items():
                rows.append({
                    "variable": m_obj.variable,
                    "lead_days": m_obj.lead_days,
                    "region": m_obj.region,
                    "season": m_obj.season,
                    "regime": m_obj.regime,
                    "model": m,
                    "ridge_weight": w,
                    "alpha": m_obj.alpha,
                    "fallback_level": m_obj.fallback_level,
                    "fallback_desc": m_obj.fallback_desc,
                    "n_samples": m_obj.n_samples,
                    "train_mae": m_obj.cv_mae,
                })
        return pd.DataFrame(rows)
