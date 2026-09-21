"""Master Pipeline Runner for AAGAM Phase 3: ML Engines & Backtest.

Orchestrates:
  1. Strict temporal splitting into Train, Val, and Test blocks (PRD §7.4).
  2. Training Ridge stacking engine with 4-fold rolling-origin time-series CV.
  3. Training LightGBM engine with early stopping on the Validation block.
  4. Running FR-BLEND-2 selection rule strictly on Validation predictions.
  5. Generating full FR-BLEND-1 outputs on the held-out Test block (2026 Monsoon).
  6. Computing backtest metrics across raw NWP, baselines, ML engines, and Adaptive Blend.
  7. Exporting model artifacts, Parquet backtest tables, metrics.json, and diagnostic plots.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

import joblib
import pandas as pd

from pipeline.blend.blender import AagamBlender
from pipeline.models.lgbm import LightGBMEngine
from pipeline.models.plots import (
    plot_phase3_blend_vs_baselines,
    plot_phase3_validation_selection,
)
from pipeline.models.ridge import RidgeStackingEngine
from pipeline.models.select import (
    decisions_to_dataframe,
    run_blend_selection,
    save_selection_decisions,
)
from pipeline.skill.baselines import (
    evaluate_forecast_candidates,
    split_dataset_temporally,
)
from pipeline.skill.fallback import HierarchicalFallbackEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("aagam.pipeline.models.runner")

TRAINING_DATASET_PATH = Path("data/training_dataset.parquet")
MODELS_DIR = Path("models")
REPORTS_DIR = Path("reports")
DATA_DIR = Path("data")


def to_markdown_table(df: pd.DataFrame) -> str:
    """Formats DataFrame as a Markdown table without requiring external tabulate dependency."""
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    separator = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = []
    for _, row in df.iterrows():
        row_str = "| " + " | ".join(str(row[c]) for c in cols) + " |"
        rows.append(row_str)
    return "\n".join([header, separator] + rows)


def run_phase_3_pipeline(
    dataset_path: Path = TRAINING_DATASET_PATH,
    models_dir: Path = MODELS_DIR,
) -> Dict[str, Any]:
    """Runs the complete Phase 3 ML engines, selection, blending, and backtest pipeline."""
    logger.info("=================================================================")
    logger.info("STARTING AAGAM PHASE 3: ML ENGINES & BACKTEST PIPELINE")
    logger.info("=================================================================")

    models_dir.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load Dataset & Create Strict Temporal Splits
    logger.info(f"Loading dataset from {dataset_path}...")
    df = pd.read_parquet(dataset_path)
    splits = split_dataset_temporally(df)

    # 2. Train Ridge Stacking Engine (PRD §8.3)
    logger.info("Fitting HierarchicalFallbackEngine on Train data for Ridge...")
    fallback_engine = HierarchicalFallbackEngine(splits.train_df, min_samples=300)

    logger.info("Fitting Ridge stacking models with 4-fold rolling-origin time-series CV...")
    ridge_engine = RidgeStackingEngine(splits.train_df, fallback_engine=fallback_engine)

    ridge_weights_path = models_dir / "ridge_weights.joblib"
    joblib.dump(ridge_engine, ridge_weights_path)
    logger.info(f"Saved Ridge engine to {ridge_weights_path}")

    ridge_weights_df = ridge_engine.to_dataframe()
    ridge_weights_df.to_parquet(models_dir / "ridge_weights_table.parquet", index=False)

    # 3. Train LightGBM Engine (PRD §8.3)
    logger.info("Training LightGBM models per variable with early stopping on Validation block...")
    lgbm_engine = LightGBMEngine(models_dir=models_dir)
    lgbm_engine.train_all(splits.train_df, splits.val_df)
    lgbm_engine.save_models()

    # 4. Run FR-BLEND-2 Selection Rule on Validation Block (PRD §6.4)
    logger.info("Generating predictions on Validation block for FR-BLEND-2 selection...")
    pred_ridge_val, deg_ridge_val = ridge_engine.predict_dataframe(splits.val_df)
    pred_lgbm_val = lgbm_engine.predict_dataframe(splits.val_df)

    selection_decisions = run_blend_selection(
        splits.val_df,
        pred_ridge=pred_ridge_val,
        pred_lgbm=pred_lgbm_val,
    )
    save_selection_decisions(selection_decisions, models_dir / "blend_selection.json")
    decisions_df = decisions_to_dataframe(selection_decisions)

    # 5. Out-of-Sample Inference on Held-Out Test Block (2026 Monsoon)
    logger.info("Generating predictions on strictly held-out Test block (2026-06-21 to 2026-09-18)...")
    pred_ridge_test, deg_ridge_test = ridge_engine.predict_dataframe(splits.test_df)
    pred_lgbm_test = lgbm_engine.predict_dataframe(splits.test_df)

    blender = AagamBlender(selection_decisions=selection_decisions)
    test_blended_df = blender.blend_dataframe(
        splits.test_df,
        pred_ridge=pred_ridge_test,
        pred_lgbm=pred_lgbm_test,
        degraded_ridge=deg_ridge_test,
    )

    blended_test_path = DATA_DIR / "blended_forecasts_test.parquet"
    test_blended_df.to_parquet(blended_test_path, index=False)
    logger.info(f"Saved blended test forecasts to {blended_test_path} ({len(test_blended_df):,} rows).")

    # 6. Comprehensive Backtest Evaluation on Test Block
    logger.info("Evaluating candidates across Test block...")
    candidate_cols = {
        "GFS": "f_gfs",
        "ECMWF IFS": "f_ecmwf_ifs",
        "ICON": "f_icon",
        "AIFS": "f_aifs",
        "Equal-Weight Mean": "equal_mean",
        "Ridge": "ridge",
        "LightGBM": "lgbm",
        "Adaptive Blend": "blended",
    }

    eval_overall = evaluate_forecast_candidates(test_blended_df, candidate_cols, group_cols=["variable"])
    eval_lead = evaluate_forecast_candidates(test_blended_df, candidate_cols, group_cols=["variable", "lead_days"])
    eval_region = evaluate_forecast_candidates(test_blended_df, candidate_cols, group_cols=["variable", "region"])
    eval_season = evaluate_forecast_candidates(test_blended_df, candidate_cols, group_cols=["variable", "season"])

    # Combine backtest results
    eval_lead["slice_type"] = "lead_days"
    eval_lead["slice_value"] = eval_lead["lead_days"].astype(str)

    eval_region["slice_type"] = "region"
    eval_region["slice_value"] = eval_region["region"].astype(str)

    eval_season["slice_type"] = "season"
    eval_season["slice_value"] = eval_season["season"].astype(str)

    eval_overall["slice_type"] = "overall"
    eval_overall["slice_value"] = "all"

    backtest_df = pd.concat([
        eval_overall[["variable", "slice_type", "slice_value", "candidate", "mae", "rmse", "bias", "n"]],
        eval_lead[["variable", "slice_type", "slice_value", "candidate", "mae", "rmse", "bias", "n"]],
        eval_region[["variable", "slice_type", "slice_value", "candidate", "mae", "rmse", "bias", "n"]],
        eval_season[["variable", "slice_type", "slice_value", "candidate", "mae", "rmse", "bias", "n"]],
    ], ignore_index=True)

    backtest_parquet_path = DATA_DIR / "phase_3_backtest.parquet"
    backtest_df.to_parquet(backtest_parquet_path, index=False)
    logger.info(f"Saved Phase 3 backtest comparison table to {backtest_parquet_path} ({len(backtest_df):,} rows).")

    # 7. Export metrics.json
    metrics_summary = {
        "training_period": {
            "start": str(splits.train_df["valid_date"].min()),
            "end": str(splits.train_df["valid_date"].max()),
            "rows": len(splits.train_df),
        },
        "validation_period": {
            "start": str(splits.val_df["valid_date"].min()),
            "end": str(splits.val_df["valid_date"].max()),
            "rows": len(splits.val_df),
        },
        "test_period": {
            "start": str(splits.test_df["valid_date"].min()),
            "end": str(splits.test_df["valid_date"].max()),
            "rows": len(splits.test_df),
        },
        "lightgbm_validation_mae": lgbm_engine.validation_maes,
        "lightgbm_best_iterations": lgbm_engine.best_iterations,
        "selection_decisions": {f"{k[0]}_lead_{k[1]}": v.selected_engine for k, v in selection_decisions.items()},
        "test_overall_metrics": eval_overall.to_dict(orient="records"),
    }

    metrics_json_path = models_dir / "metrics.json"
    with open(metrics_json_path, "w", encoding="utf-8") as f:
        json.dump(metrics_summary, f, indent=2)
    logger.info(f"Saved metrics.json to {metrics_json_path}")

    # 8. Save Markdown Backtest Summary
    summary_path = REPORTS_DIR / "phase_3_backtest_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("# AAGAM Phase 3: ML Engines & Adaptive Blend Backtest Summary\n\n")
        f.write("## FR-BLEND-2 Validation Selection Decisions\n\n")
        f.write(to_markdown_table(decisions_df))
        f.write("\n\n## Overall Test Performance (Held-Out 2026 Monsoon Test Block)\n\n")
        f.write(to_markdown_table(eval_overall))
        f.write("\n\n## Performance by Lead Day\n\n")
        f.write(to_markdown_table(eval_lead))
        f.write("\n\n## Performance by Region\n\n")
        f.write(to_markdown_table(eval_region))
    logger.info(f"Wrote markdown backtest summary to {summary_path}")

    # 9. Generate Diagnostic Figures
    logger.info("Generating Phase 3 diagnostic figures in reports/figures/...")
    plot_phase3_blend_vs_baselines(eval_lead)
    plot_phase3_validation_selection(decisions_df)
    logger.info("All diagnostic figures generated successfully.")

    logger.info("=================================================================")
    logger.info("AAGAM PHASE 3 PIPELINE EXECUTION COMPLETE")
    logger.info("=================================================================")

    return {
        "ridge_engine": ridge_engine,
        "lgbm_engine": lgbm_engine,
        "selection_decisions": selection_decisions,
        "test_blended_df": test_blended_df,
        "backtest_df": backtest_df,
        "eval_overall": eval_overall,
        "eval_lead": eval_lead,
    }


if __name__ == "__main__":
    run_phase_3_pipeline()
