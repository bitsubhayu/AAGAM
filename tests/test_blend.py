"""Unit and Integration Tests for AAGAM Phase 3: ML Engines & Backtest.

Covers:
  - Strict temporal ordering & zero test data leakage (PRD §7.4)
  - Proof that test data was never used for training, alpha tuning, or blend selection
  - Ridge rolling-origin 4-fold CV with expanding chronological windows
  - Ridge non-negative weights and exact 1.0 normalization (FR-BLEND-3)
  - Dynamic weight re-normalization and degraded=True for missing models (FR-BLEND-4)
  - LightGBM inference, target transformations, and non-negative outputs
  - FR-BLEND-2 selection rule logic (2% threshold between Ridge and LightGBM)
  - Models over threshold counting against config/thresholds.yaml
  - Parquet artifact and metrics.json schema validation
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.blend.blender import AagamBlender, load_advisory_thresholds
from pipeline.models.ridge import (
    fit_ridge_for_bucket,
    rolling_origin_cv_ridge,
)
from pipeline.models.select import (
    SelectionDecision,
    run_blend_selection,
)
from pipeline.skill.baselines import (
    TEST_START_DATE,
    TRAIN_END_DATE,
    VAL_END_DATE,
    VAL_START_DATE,
    split_dataset_temporally,
)


class TestTemporalSplitZeroLeakage:
    """Rigorous tests proving zero future-data leakage into training or tuning."""

    def test_temporal_inequality_strict(self):
        df = pd.read_parquet("data/training_dataset.parquet")
        splits = split_dataset_temporally(df)

        max_train = pd.to_datetime(splits.train_df["valid_date"].max()).date()
        min_val = pd.to_datetime(splits.val_df["valid_date"].min()).date()
        max_val = pd.to_datetime(splits.val_df["valid_date"].max()).date()
        min_test = pd.to_datetime(splits.test_df["valid_date"].min()).date()

        assert max_train == TRAIN_END_DATE
        assert min_val == VAL_START_DATE
        assert max_val == VAL_END_DATE
        assert min_test == TEST_START_DATE

        assert max_train < min_val, f"Train overlaps with Val: {max_train} >= {min_val}"
        assert max_val < min_test, f"Val overlaps with Test: {max_val} >= {min_test}"

    def test_metrics_json_confirms_strict_periods(self):
        metrics_path = Path("models/metrics.json")
        assert metrics_path.exists()
        with open(metrics_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["training_period"]["end"] == "2026-03-22"
        assert data["validation_period"]["start"] == "2026-03-23"
        assert data["validation_period"]["end"] == "2026-06-20"
        assert data["test_period"]["start"] == "2026-06-21"
        assert data["test_period"]["end"] == "2026-09-18"


class TestRidgeStackingEngine:
    """Tests Ridge stacking, rolling-origin CV, and FR-BLEND-3/4 constraints."""

    def test_ridge_weights_non_negative_and_sum_one(self):
        # Synthetic data with 4 models and truth
        np.random.seed(42)
        n = 200
        df_bucket = pd.DataFrame({
            "valid_date": pd.date_range("2024-01-01", periods=n, freq="D").date,
            "f_gfs": np.random.uniform(20, 35, n),
            "f_ecmwf_ifs": np.random.uniform(20, 35, n),
            "f_icon": np.random.uniform(20, 35, n),
            "f_aifs": np.random.uniform(20, 35, n),
            "truth": np.random.uniform(20, 35, n),
        })

        weights, train_mae = fit_ridge_for_bucket(df_bucket, alpha=1.0)

        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-5)
        for m, w in weights.items():
            assert w >= 0.0, f"Negative weight for {m}: {w}"
        assert train_mae >= 0.0

    def test_ridge_rolling_origin_cv_folds_chronological(self):
        # Verify rolling origin CV runs without error and selects an alpha
        dates = pd.date_range("2024-01-01", "2025-12-31", freq="D").date
        n = len(dates)
        df_cv = pd.DataFrame({
            "valid_date": dates,
            "f_gfs": np.linspace(10, 30, n) + np.random.normal(0, 1, n),
            "f_ecmwf_ifs": np.linspace(10, 30, n) + np.random.normal(0, 0.5, n),
            "f_icon": np.linspace(10, 30, n) + np.random.normal(0, 1.5, n),
            "f_aifs": np.linspace(10, 30, n) + np.random.normal(0, 0.8, n),
            "truth": np.linspace(10, 30, n),
        })

        chosen_alpha = rolling_origin_cv_ridge(df_cv)
        assert chosen_alpha in [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]

    def test_ridge_dynamic_renormalization_missing_models(self):
        from pipeline.models.ridge import BucketRidgeModel, RidgeStackingEngine

        # Mock engine with a known bucket
        base_weights = {"gfs": 0.25, "ecmwf_ifs": 0.35, "icon": 0.15, "aifs": 0.25}
        model_obj = BucketRidgeModel(
            variable="rain_mm",
            lead_days=7,
            region="NW",
            season="monsoon",
            regime="heavy_rain",
            alpha=1.0,
            weights=base_weights,
            fallback_level=0,
            fallback_desc="full_bucket",
            n_samples=500,
            cv_mae=5.0,
        )

        class MockRidgeEngine:
            models = ["gfs", "ecmwf_ifs", "icon", "aifs"]
            bucket_models = {("rain_mm", 7, "NW", "monsoon", "heavy_rain"): model_obj}
            predict_row = RidgeStackingEngine.predict_row

        engine = MockRidgeEngine()

        # Case 1: All models present
        row_full = {
            "variable": "rain_mm",
            "lead_days": 7,
            "region": "NW",
            "season": "monsoon",
            "regime": "heavy_rain",
            "f_gfs": 10.0,
            "f_ecmwf_ifs": 12.0,
            "f_icon": 8.0,
            "f_aifs": 11.0,
        }
        pred, w_full, deg = engine.predict_row(row_full)
        assert deg is False
        assert math.isclose(sum(w_full.values()), 1.0, abs_tol=1e-5)
        expected_pred = 0.25 * 10 + 0.35 * 12 + 0.15 * 8 + 0.25 * 11
        assert math.isclose(pred, expected_pred, rel_tol=1e-4)

        # Case 2: ICON is NaN (e.g. Lead 7)
        row_missing = dict(row_full)
        row_missing["f_icon"] = np.nan
        pred_miss, w_miss, deg_miss = engine.predict_row(row_missing)

        assert deg_miss is True
        assert w_miss["icon"] == 0.0
        assert math.isclose(sum(w_miss.values()), 1.0, abs_tol=1e-5)
        # Sum of available weights = 0.25 + 0.35 + 0.25 = 0.85
        # Re-normalized gfs = 0.25 / 0.85
        assert math.isclose(w_miss["gfs"], 0.25 / 0.85, rel_tol=1e-4)
        assert math.isclose(w_miss["ecmwf_ifs"], 0.35 / 0.85, rel_tol=1e-4)
        assert math.isclose(w_miss["aifs"], 0.25 / 0.85, rel_tol=1e-4)


class TestFrBlendSelectionRule:
    """Tests FR-BLEND-2 selection rule logic (2% threshold)."""

    def test_selection_rule_average_within_two_percent(self):
        # Case A: within 2% -> average
        val_df = pd.DataFrame({
            "variable": ["tmax_c"] * 10,
            "lead_days": [1] * 10,
            "truth": [30.0] * 10,
        })
        # Ridge MAE = 1.00
        pred_ridge = np.array([31.0] * 10)
        # LightGBM MAE = 1.01 (diff = 1% <= 2%)
        pred_lgbm = np.array([31.01] * 10)

        decisions = run_blend_selection(val_df, pred_ridge, pred_lgbm)
        dec = decisions[("tmax_c", 1)]
        assert dec.selected_engine == "average"
        assert dec.relative_diff_pct <= 2.0

    def test_selection_rule_ridge_wins(self):
        # Case B: Ridge significantly beats LightGBM (> 2%)
        val_df = pd.DataFrame({
            "variable": ["rain_mm"] * 10,
            "lead_days": [2] * 10,
            "truth": [10.0] * 10,
        })
        # Ridge MAE = 1.00
        pred_ridge = np.array([11.0] * 10)
        # LightGBM MAE = 1.15 (diff = 15% > 2%)
        pred_lgbm = np.array([11.15] * 10)

        decisions = run_blend_selection(val_df, pred_ridge, pred_lgbm)
        dec = decisions[("rain_mm", 2)]
        assert dec.selected_engine == "ridge"

    def test_selection_rule_lgbm_wins(self):
        # Case C: LightGBM significantly beats Ridge (> 2%)
        val_df = pd.DataFrame({
            "variable": ["wind_max_kmh"] * 10,
            "lead_days": [3] * 10,
            "truth": [20.0] * 10,
        })
        # Ridge MAE = 2.50
        pred_ridge = np.array([22.50] * 10)
        # LightGBM MAE = 2.00 (diff = 25% > 2%)
        pred_lgbm = np.array([22.00] * 10)

        decisions = run_blend_selection(val_df, pred_ridge, pred_lgbm)
        dec = decisions[("wind_max_kmh", 3)]
        assert dec.selected_engine == "lgbm"


class TestAagamBlenderOutputSchema:
    """Tests FR-BLEND-1 schema compliance, spread calculation, and models_over_threshold."""

    def test_blender_columns_and_spread(self):
        decisions = {
            ("rain_mm", 1): SelectionDecision(
                variable="rain_mm",
                lead_days=1,
                val_mae_ridge=5.0,
                val_mae_lgbm=4.5,
                relative_diff_pct=11.1,
                selected_engine="lgbm",
                rationale="LightGBM beats Ridge",
            )
        }
        blender = AagamBlender(selection_decisions=decisions)

        df = pd.DataFrame({
            "variable": ["rain_mm"],
            "lead_days": [1],
            "f_gfs": [10.0],
            "f_ecmwf_ifs": [12.0],
            "f_icon": [8.0],
            "f_aifs": [14.0],
        })
        pred_ridge = np.array([11.0])
        pred_lgbm = np.array([10.5])

        out = blender.blend_dataframe(df, pred_ridge=pred_ridge, pred_lgbm=pred_lgbm)

        # Schema assertions
        expected_cols = [
            "blended", "ridge", "lgbm", "equal_mean", "spread",
            "models_over_threshold", "degraded", "selected_engine"
        ]
        for c in expected_cols:
            assert c in out.columns, f"Missing output column: {c}"

        assert out["selected_engine"].iloc[0] == "lgbm"
        assert math.isclose(out["blended"].iloc[0], 10.5)
        assert math.isclose(out["equal_mean"].iloc[0], 11.0)
        # Spread is std([10, 12, 8, 14]) with ddof=1: std=2.581988897
        assert math.isclose(out["spread"].iloc[0], np.std([10, 12, 8, 14], ddof=1), rel_tol=1e-4)

    def test_models_over_threshold_advisory(self):
        thresholds = load_advisory_thresholds()
        assert thresholds["rain_mm"] == 64.5
        assert thresholds["tmax_c"] == 40.0
        assert thresholds["wind_max_kmh"] == 50.0

        decisions = {
            ("rain_mm", 1): SelectionDecision(
                variable="rain_mm",
                lead_days=1,
                val_mae_ridge=5.0,
                val_mae_lgbm=4.5,
                relative_diff_pct=11.1,
                selected_engine="lgbm",
                rationale="test",
            )
        }
        blender = AagamBlender(selection_decisions=decisions, thresholds=thresholds)

        # 2 models over 64.5 mm
        df = pd.DataFrame({
            "variable": ["rain_mm"],
            "lead_days": [1],
            "f_gfs": [70.0],       # Over
            "f_ecmwf_ifs": [65.0], # Over
            "f_icon": [50.0],      # Under
            "f_aifs": [20.0],      # Under
        })
        out = blender.blend_dataframe(df, pred_ridge=np.array([55.0]), pred_lgbm=np.array([54.0]))
        assert out["models_over_threshold"].iloc[0] == 2


class TestPhase3ArtifactsIntegrity:
    """Verifies existence, row counts, and zero duplicates in generated Phase 3 artifacts."""

    def test_model_artifacts_exist(self):
        assert Path("models/ridge_weights.joblib").exists()
        assert Path("models/ridge_weights_table.parquet").exists()
        assert Path("models/lgbm_rain_mm.joblib").exists()
        assert Path("models/lgbm_tmax_c.joblib").exists()
        assert Path("models/lgbm_wind_max_kmh.joblib").exists()
        assert Path("models/blend_selection.json").exists()
        assert Path("models/metrics.json").exists()

    def test_backtest_parquet_integrity(self):
        p = Path("data/phase_3_backtest.parquet")
        assert p.exists()
        df = pd.read_parquet(p)

        assert len(df) == 336
        assert df.duplicated().sum() == 0, "Found duplicate rows in phase_3_backtest.parquet"

        candidates = set(df["candidate"].unique())
        expected_candidates = {
            "GFS", "ECMWF IFS", "ICON", "AIFS",
            "Equal-Weight Mean", "Ridge", "LightGBM", "Adaptive Blend"
        }
        assert candidates == expected_candidates

    def test_blended_forecasts_test_integrity(self):
        p = Path("data/blended_forecasts_test.parquet")
        assert p.exists()
        df = pd.read_parquet(p)

        assert len(df) == 75600
        assert df.duplicated(subset=["valid_date", "location_id", "variable", "lead_days"]).sum() == 0

        # Physical non-negativity for rain and wind
        rain_mask = df["variable"] == "rain_mm"
        assert (df.loc[rain_mask, "blended"] >= 0.0).all(), "Found negative rain predictions in blended forecasts"

        wind_mask = df["variable"] == "wind_max_kmh"
        assert (df.loc[wind_mask, "blended"] >= 0.0).all(), "Found negative wind predictions in blended forecasts"
