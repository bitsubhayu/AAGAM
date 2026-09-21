"""LightGBM Regression Engine for AAGAM (Phase 3, PRD §8.3).

Implements one gradient-boosted decision tree per weather variable:
  - rain_mm: regression_l1 on sqrt-transformed target (with square back-transform & non-negative clip)
  - tmax_c: regression_l1
  - wind_max_kmh: regression_l1 (with non-negative clip)

Features (16 inputs):
  [f_gfs, f_ecmwf_ifs, f_icon, f_aifs, mean, std, max, min,
   lead_days, doy_sin, doy_cos, lat, lon, region, season, regime]

Early stopping evaluated strictly on the Validation block (2026-03-23 to 2026-06-20).
Zero data leakage from the test block.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

logger = logging.getLogger("aagam.pipeline.models.lgbm")

FEATURE_COLS = [
    "f_gfs",
    "f_ecmwf_ifs",
    "f_icon",
    "f_aifs",
    "mean",
    "std",
    "max",
    "min",
    "lead_days",
    "doy_sin",
    "doy_cos",
    "lat",
    "lon",
    "region",
    "season",
    "regime",
]

CATEGORICAL_COLS = ["region", "season", "regime"]


def prepare_features(
    df: pd.DataFrame,
    feature_cols: Optional[List[str]] = None,
    cat_cols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Extracts and formats feature matrix with categorical encodings for LightGBM."""
    if feature_cols is None:
        feature_cols = FEATURE_COLS
    if cat_cols is None:
        cat_cols = CATEGORICAL_COLS

    X = df[feature_cols].copy()
    for col in cat_cols:
        if col in X.columns:
            X[col] = X[col].astype("category")

    return X


class LightGBMEngine:
    """Manages training, validation early-stopping, serialization, and inference for LightGBM."""

    def __init__(self, models_dir: Optional[Path] = None) -> None:
        self.models_dir = models_dir or Path("models")
        self.models: Dict[str, lgb.LGBMRegressor] = {}
        self.best_iterations: Dict[str, int] = {}
        self.validation_maes: Dict[str, float] = {}

    def train_for_variable(
        self,
        var: str,
        train_df: pd.DataFrame,
        val_df: pd.DataFrame,
        target_col: str = "truth",
    ) -> lgb.LGBMRegressor:
        """Trains a single LightGBM model for a given weather variable with early stopping.

        Args:
            var: Variable name ('rain_mm', 'tmax_c', 'wind_max_kmh').
            train_df: Historical training data (up to 2026-03-22).
            val_df: Validation data (2026-03-23 to 2026-06-20).
            target_col: Name of truth observation column.

        Returns:
            Trained LGBMRegressor.
        """
        logger.info(f"Training LightGBM model for {var}...")

        # Filter to target variable
        tr_sub = train_df[train_df["variable"] == var].copy()
        val_sub = val_df[val_df["variable"] == var].copy()

        # Clean NaNs in target
        tr_sub = tr_sub.dropna(subset=[target_col])
        val_sub = val_sub.dropna(subset=[target_col])

        # Prepare features
        X_train = prepare_features(tr_sub)
        y_train = tr_sub[target_col].to_numpy(dtype=float)

        X_val = prepare_features(val_sub)
        y_val = val_sub[target_col].to_numpy(dtype=float)

        # Target transformation for rain: sqrt(rain)
        if var == "rain_mm":
            y_train_fit = np.sqrt(np.maximum(0.0, y_train))
            y_val_fit = np.sqrt(np.maximum(0.0, y_val))
        else:
            y_train_fit = y_train
            y_val_fit = y_val

        # LightGBM Regressor configuration
        model = lgb.LGBMRegressor(
            objective="regression_l1",
            n_estimators=600,
            learning_rate=0.03,
            num_leaves=31,
            min_child_samples=50,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )

        callbacks = [lgb.early_stopping(stopping_rounds=30, verbose=False)]
        model.fit(
            X_train,
            y_train_fit,
            eval_set=[(X_val, y_val_fit)],
            callbacks=callbacks,
        )

        best_iter = model.best_iteration_ or model.n_estimators
        self.best_iterations[var] = best_iter
        self.models[var] = model

        # Evaluate validation MAE on original target scale
        val_preds_raw = model.predict(X_val)
        if var == "rain_mm":
            val_preds = np.square(np.maximum(0.0, val_preds_raw))
        elif var == "wind_max_kmh":
            val_preds = np.maximum(0.0, val_preds_raw)
        else:
            val_preds = val_preds_raw

        val_mae = float(np.mean(np.abs(val_preds - y_val)))
        self.validation_maes[var] = round(val_mae, 4)

        logger.info(
            f"Trained LightGBM for {var}: best_iteration={best_iter}, "
            f"Validation MAE={self.validation_maes[var]}"
        )
        return model

    def train_all(
        self,
        train_df: pd.DataFrame,
        val_df: pd.DataFrame,
        variables: Optional[List[str]] = None,
    ) -> None:
        """Trains LightGBM models for all weather variables."""
        if variables is None:
            variables = ["rain_mm", "tmax_c", "wind_max_kmh"]

        for var in variables:
            self.train_for_variable(var, train_df, val_df)

    def predict_for_variable(
        self,
        var: str,
        df: pd.DataFrame,
    ) -> np.ndarray:
        """Generates predictions for a specific variable's DataFrame."""
        if var not in self.models:
            raise KeyError(f"No trained LightGBM model found for {var}")

        model = self.models[var]
        X = prepare_features(df)
        raw_pred = model.predict(X)

        if var == "rain_mm":
            preds = np.square(np.maximum(0.0, raw_pred))
        elif var == "wind_max_kmh":
            preds = np.maximum(0.0, raw_pred)
        else:
            preds = raw_pred

        return preds

    def predict_dataframe(self, df: pd.DataFrame) -> np.ndarray:
        """Predicts across a heterogeneous DataFrame containing multiple variables."""
        all_preds = np.empty(len(df), dtype=float)
        all_preds[:] = np.nan

        for var in ["rain_mm", "tmax_c", "wind_max_kmh"]:
            mask = df["variable"] == var
            if mask.any():
                sub_df = df[mask]
                preds = self.predict_for_variable(var, sub_df)
                all_preds[mask.to_numpy()] = preds

        return all_preds

    def save_models(self, output_dir: Optional[Path] = None) -> List[Path]:
        """Serializes trained LightGBM models to disk."""
        target_dir = output_dir or self.models_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        saved_paths = []

        for var, model in self.models.items():
            path = target_dir / f"lgbm_{var}.joblib"
            joblib.dump(model, path)
            saved_paths.append(path)
            logger.info(f"Saved LightGBM model for {var} to {path}")

        return saved_paths

    def load_models(self, input_dir: Optional[Path] = None) -> None:
        """Loads serialized LightGBM models from disk."""
        target_dir = input_dir or self.models_dir
        for var in ["rain_mm", "tmax_c", "wind_max_kmh"]:
            path = target_dir / f"lgbm_{var}.joblib"
            if path.exists():
                self.models[var] = joblib.load(path)
                logger.info(f"Loaded LightGBM model for {var} from {path}")
            else:
                logger.warning(f"Model file not found: {path}")
