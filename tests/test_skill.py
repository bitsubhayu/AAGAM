"""Unit and Integration Tests for AAGAM Phase 2: Skill Scoring & Baselines.

Covers:
  - MAE, RMSE, bias, n correctness against hand-computed golden vectors
  - Handling of missing values (NaNs never fabricated or imputed)
  - Deterministic 4-level hierarchical fallback order and n >= 300 threshold
  - Inverse-MAE weight properties (sum to 1.0, non-negative, monotonicity)
  - Dynamic re-normalization for missing models
  - Zero future-data leakage (temporal splitting inequality)
  - Parquet artifact validation
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.skill.baselines import (
    TEST_START_DATE,
    TRAIN_END_DATE,
    VAL_END_DATE,
    VAL_START_DATE,
    split_dataset_temporally,
)
from pipeline.skill.fallback import HierarchicalFallbackEngine
from pipeline.skill.scoring import compute_metrics, filter_by_trailing_window
from pipeline.skill.weights import compute_inverse_mae_weights


class TestSkillScoringMath:
    """Tests exact numerical correctness of skill scoring metrics (FR-SKILL-1)."""

    def test_compute_metrics_golden_vector(self):
        # Forecast: [10, 20, 30, NaN, 50]
        # Truth:    [12, 18, 35, 40,  NaN]
        # Valid pairs at idx 0, 1, 2:
        #   idx 0: f=10, y=12, diff=-2
        #   idx 1: f=20, y=18, diff=+2
        #   idx 2: f=30, y=35, diff=-5
        # MAE  = (2 + 2 + 5) / 3 = 3.0
        # RMSE = sqrt((4 + 4 + 25) / 3) = sqrt(33 / 3) = sqrt(11) ≈ 3.3166
        # Bias = (-2 + 2 - 5) / 3 = -1.6667
        # n    = 3
        forecast = np.array([10.0, 20.0, 30.0, np.nan, 50.0])
        truth = np.array([12.0, 18.0, 35.0, 40.0, np.nan])

        res = compute_metrics(forecast, truth)

        assert res["n"] == 3
        assert res["mae"] == 3.0
        assert math.isclose(res["rmse"], round(math.sqrt(11.0), 4), rel_tol=1e-4)
        assert math.isclose(res["bias"], round(-5.0 / 3.0, 4), rel_tol=1e-4)

    def test_compute_metrics_all_nans(self):
        forecast = np.array([np.nan, np.nan, np.nan])
        truth = np.array([10.0, 20.0, 30.0])

        res = compute_metrics(forecast, truth)
        assert res["n"] == 0
        assert np.isnan(res["mae"])
        assert np.isnan(res["rmse"])
        assert np.isnan(res["bias"])

    def test_compute_metrics_no_fabricated_zeros(self):
        # Ensure NaNs are not secretly converted to 0.0
        forecast = np.array([np.nan])
        truth = np.array([0.0])

        res = compute_metrics(forecast, truth)
        assert res["n"] == 0
        assert np.isnan(res["mae"])

    def test_trailing_window_filtering(self):
        dates = pd.date_range("2026-01-01", "2026-03-31", freq="D")
        df = pd.DataFrame({
            "valid_date": dates.date,
            "val": range(len(dates)),
        })

        cutoff = date(2026, 3, 31)
        # 60 days trailing window in 2026 (non-leap year: 31 days in Mar, 28 in Feb, 1 in Jan):
        # Jan 31 -> Mar 31 is exactly 60 calendar days
        filtered = filter_by_trailing_window(df, cutoff_date=cutoff, window_days=60)

        assert len(filtered) == 60
        assert filtered["valid_date"].min() == date(2026, 1, 31)
        assert filtered["valid_date"].max() == date(2026, 3, 31)


class TestInverseMaeWeights:
    """Tests inverse-MAE skill weighting properties (FR-SKILL-3, PRD §8.2)."""

    def test_weights_sum_to_one(self):
        mae_dict = {"gfs": 3.5, "ecmwf_ifs": 2.1, "icon": 2.8, "aifs": 1.9}
        weights = compute_inverse_mae_weights(mae_dict)

        total_weight = sum(weights.values())
        assert math.isclose(total_weight, 1.0, abs_tol=1e-5)
        for m, w in weights.items():
            assert w >= 0.0

    def test_weights_monotonicity(self):
        # Best model (lowest MAE) must receive highest weight
        mae_dict = {"gfs": 5.0, "ecmwf_ifs": 1.0, "icon": 3.0, "aifs": 2.0}
        weights = compute_inverse_mae_weights(mae_dict)

        assert weights["ecmwf_ifs"] > weights["aifs"]
        assert weights["aifs"] > weights["icon"]
        assert weights["icon"] > weights["gfs"]

    def test_weights_nan_handling(self):
        # If a model has NaN MAE, it receives weight 0.0 and others normalize to 1.0
        mae_dict = {"gfs": 2.0, "ecmwf_ifs": 2.0, "icon": np.nan, "aifs": 2.0}
        weights = compute_inverse_mae_weights(mae_dict)

        assert weights["icon"] == 0.0
        assert math.isclose(weights["gfs"], 1.0 / 3.0, rel_tol=1e-4)
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-5)

    def test_deterministic_output(self):
        mae_dict = {"gfs": 4.1234, "ecmwf_ifs": 2.5678, "icon": 3.4567, "aifs": 1.8901}
        w1 = compute_inverse_mae_weights(mae_dict)
        w2 = compute_inverse_mae_weights(mae_dict)
        assert w1 == w2


class TestHierarchicalFallback:
    """Tests deterministic 4-level fallback order and n >= 300 threshold (FR-SKILL-2)."""

    def test_fallback_levels_and_threshold(self):
        # Construct synthetic dataframe with:
        # Bucket 1: n = 400 at Level 0 -> should stay at Level 0
        # Bucket 2: n = 150 at Level 0, but n = 350 at Level 1 -> should fall back to Level 1
        rows = []
        # Bucket 1: (rain_mm, 1, NW, monsoon, heavy_rain) -> 400 rows
        for _ in range(400):
            rows.append({
                "variable": "rain_mm",
                "lead_days": 1,
                "region": "NW",
                "season": "monsoon",
                "regime": "heavy_rain",
                "f_gfs": 10.0,
                "f_ecmwf_ifs": 11.0,
                "f_icon": 9.0,
                "f_aifs": 10.5,
                "truth": 10.0,
            })

        # Bucket 2a: (tmax_c, 2, SOUTH, winter, heat_wave) -> 100 rows
        for _ in range(100):
            rows.append({
                "variable": "tmax_c",
                "lead_days": 2,
                "region": "SOUTH",
                "season": "winter",
                "regime": "heat_wave",
                "f_gfs": 35.0,
                "f_ecmwf_ifs": 34.0,
                "f_icon": 35.5,
                "f_aifs": 34.5,
                "truth": 34.0,
            })

        # Bucket 2b: (tmax_c, 2, SOUTH, winter, normal) -> 250 rows
        # Level 1 for (tmax_c, 2, SOUTH, winter) will have 100 + 250 = 350 rows!
        for _ in range(250):
            rows.append({
                "variable": "tmax_c",
                "lead_days": 2,
                "region": "SOUTH",
                "season": "winter",
                "regime": "normal",
                "f_gfs": 30.0,
                "f_ecmwf_ifs": 29.0,
                "f_icon": 30.5,
                "f_aifs": 29.5,
                "truth": 29.0,
            })

        df = pd.DataFrame(rows)
        engine = HierarchicalFallbackEngine(df, min_samples=300)

        # Query Bucket 1
        res1 = engine.resolve_bucket("rain_mm", 1, "NW", "monsoon", "heavy_rain")
        assert res1["resolved_level"] == 0
        assert res1["is_fallback"] is False
        assert res1["n_samples"] == 400

        # Query Bucket 2a (has 100 < 300, falls back to Level 1 with 350 samples)
        res2 = engine.resolve_bucket("tmax_c", 2, "SOUTH", "winter", "heat_wave")
        assert res2["resolved_level"] == 1
        assert res2["is_fallback"] is True
        assert res2["resolved_level_desc"] == "drop_regime"
        assert res2["n_samples"] == 350


class TestTemporalLeakageSafety:
    """Tests strict temporal splits with zero data leakage (PRD §7.4)."""

    def test_split_temporal_inequality(self):
        dates = pd.date_range("2024-01-20", "2026-09-18", freq="D")
        df = pd.DataFrame({
            "valid_date": dates.date,
            "variable": "rain_mm",
            "lead_days": 1,
            "region": "CENTRAL",
            "season": "monsoon",
            "regime": "normal",
            "truth": 5.0,
            "f_gfs": 5.0,
            "f_ecmwf_ifs": 5.0,
            "f_icon": 5.0,
            "f_aifs": 5.0,
        })

        splits = split_dataset_temporally(df)

        max_train = pd.to_datetime(splits.train_df["valid_date"].max()).date()
        min_val = pd.to_datetime(splits.val_df["valid_date"].min()).date()
        max_val = pd.to_datetime(splits.val_df["valid_date"].max()).date()
        min_test = pd.to_datetime(splits.test_df["valid_date"].min()).date()

        assert max_train < min_val, f"Leakage: train={max_train} not strictly before val={min_val}"
        assert max_val < min_test, f"Leakage: val={max_val} not strictly before test={min_test}"
        assert max_train == TRAIN_END_DATE
        assert min_val == VAL_START_DATE
        assert max_val == VAL_END_DATE
        assert min_test == TEST_START_DATE


class TestPhase2ParquetArtifacts:
    """Validates structural integrity and constraints of Phase 2 Parquet files."""

    def test_skill_scores_artifact(self):
        path = Path("data/skill_scores.parquet")
        assert path.exists(), f"Missing artifact: {path}"
        df = pd.read_parquet(path)

        expected_cols = [
            "variable", "lead_days", "region", "season", "regime",
            "model", "mae", "rmse", "bias", "n_model", "n_bucket",
            "fallback_level", "fallback_desc", "is_fallback"
        ]
        for col in expected_cols:
            assert col in df.columns, f"Missing column: {col}"

        # Confirm all models are present
        assert set(df["model"].unique()) == {"gfs", "ecmwf_ifs", "icon", "aifs"}
        # Minimum bucket sample size >= 300
        assert (df["n_bucket"] >= 300).all()

    def test_baseline_weights_artifact(self):
        path = Path("data/baseline_weights.parquet")
        assert path.exists(), f"Missing artifact: {path}"
        df = pd.read_parquet(path)

        expected_cols = [
            "variable", "lead_days", "region", "season", "regime",
            "model", "weight", "mae", "rmse", "bias", "n_samples",
            "fallback_level", "method"
        ]
        for col in expected_cols:
            assert col in df.columns, f"Missing column: {col}"

        # Verify weights sum to 1.0 per bucket
        bucket_sums = df.groupby(["variable", "lead_days", "region", "season", "regime"])["weight"].sum()
        for b_sum in bucket_sums:
            assert math.isclose(b_sum, 1.0, abs_tol=1e-4), f"Bucket weight sum {b_sum} != 1.0"

    def test_baseline_comparisons_artifact(self):
        path = Path("data/baseline_comparisons.parquet")
        assert path.exists(), f"Missing artifact: {path}"
        df = pd.read_parquet(path)

        expected_candidates = {
            "GFS", "ECMWF IFS", "ICON", "AIFS",
            "Equal-Weight Mean", "Best-Single Model", "Inverse-MAE Blend"
        }
        assert set(df["candidate"].unique()) == expected_candidates
        assert set(df["variable"].unique()) == {"rain_mm", "tmax_c", "wind_max_kmh"}

    def test_live_weights_60d_artifact(self):
        path = Path("data/live_weights_60d.parquet")
        assert path.exists(), f"Missing artifact: {path}"
        df = pd.read_parquet(path)

        expected_cols = [
            "variable", "lead_days", "region", "season", "regime",
            "model", "weight", "mae", "rmse", "bias", "n_samples",
            "fallback_level", "method"
        ]
        for col in expected_cols:
            assert col in df.columns, f"Missing column: {col}"

        assert (df["weight"] >= 0.0).all(), "Found negative weights in 60d live table"
        assert not df["weight"].isna().any(), "Found NaN weights in 60d live table"

        # Verify weights sum to 1.0 per bucket
        bucket_sums = df.groupby(["variable", "lead_days", "region", "season", "regime"])["weight"].sum()
        for b_sum in bucket_sums:
            assert math.isclose(b_sum, 1.0, abs_tol=1e-4), f"60d bucket weight sum {b_sum} != 1.0"

    def test_weights_no_negative_or_nan(self):
        for fname in ["baseline_weights.parquet", "live_weights_60d.parquet"]:
            p = Path("data") / fname
            df = pd.read_parquet(p)
            assert (df["weight"] >= 0.0).all(), f"Found negative weight in {fname}"
            assert not df["weight"].isna().any(), f"Found NaN weight in {fname}"

            # When model has samples (n > 0), MAE must be valid non-NaN
            valid_samples_mask = df["n_samples"] > 0
            assert not df.loc[valid_samples_mask, "mae"].isna().any(), f"Found NaN MAE with n > 0 in {fname}"

            # When model has 0 samples (e.g. ICON at lead 7), weight must be strictly 0.0
            zero_samples_mask = df["n_samples"] == 0
            if zero_samples_mask.any():
                assert (df.loc[zero_samples_mask, "weight"] == 0.0).all(), f"Zero-sample model has non-zero weight in {fname}"
                assert df.loc[zero_samples_mask, "mae"].isna().all(), f"Zero-sample model fabricated non-NaN MAE in {fname}"

    def test_zero_test_data_leakage_in_artifacts(self):
        # Verify training dataset dates vs train/val/test splits
        df = pd.read_parquet("data/training_dataset.parquet")
        splits = split_dataset_temporally(df)

        max_train = pd.to_datetime(splits.train_df["valid_date"].max()).date()
        min_test = pd.to_datetime(splits.test_df["valid_date"].min()).date()

        assert max_train == date(2026, 3, 22)
        assert min_test == date(2026, 6, 21)
        assert max_train < min_test, "Test data leakage: train overlap with test"

        # Confirm test set covers exactly the 2026 monsoon test block
        test_dates = pd.to_datetime(splits.test_df["valid_date"]).dt.date.unique()
        assert len(test_dates) == 90
        assert min(test_dates) == date(2026, 6, 21)
        assert max(test_dates) == date(2026, 9, 18)

