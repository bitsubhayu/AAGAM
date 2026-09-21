"""Master Pipeline Runner for AAGAM Phase 2: Skill Scoring & Baselines.

Orchestrates:
  1. Data ingestion from data/training_dataset.parquet
  2. Temporal splitting (Train, Val, Test) strictly adhering to PRD §7.4
  3. Hierarchical Fallback calculation (FR-SKILL-1, FR-SKILL-2) with n_min = 300
  4. Inverse-MAE Skill Weight table computation (FR-SKILL-3, PRD §8.2)
  5. Baseline forecasting & evaluation on held-out Test set (Equal-Weight, Best-Single, Inverse-MAE)
  6. Saving Parquet artifacts:
     - data/skill_scores.parquet
     - data/baseline_weights.parquet
     - data/baseline_comparisons.parquet
  7. Generating diagnostic plots in reports/figures/
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict

import pandas as pd

from pipeline.skill.baselines import (
    compute_baseline_forecasts,
    determine_best_single_models,
    evaluate_forecast_candidates,
    split_dataset_temporally,
)
from pipeline.skill.fallback import HierarchicalFallbackEngine
from pipeline.skill.plots import (
    plot_fallback_distribution,
    plot_model_coverage_audit,
    plot_skill_by_lead_day,
    plot_skill_by_region,
    plot_skill_by_season,
)
from pipeline.skill.scoring import filter_by_trailing_window
from pipeline.skill.weights import build_skill_weights_table

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("aagam.pipeline.skill.runner")

TRAINING_DATASET_PATH = Path("data/training_dataset.parquet")
OUTPUT_SKILL_SCORES_PATH = Path("data/skill_scores.parquet")
OUTPUT_WEIGHTS_PATH = Path("data/baseline_weights.parquet")
OUTPUT_LIVE_WEIGHTS_60D_PATH = Path("data/live_weights_60d.parquet")
OUTPUT_COMPARISONS_PATH = Path("data/baseline_comparisons.parquet")
REPORTS_DIR = Path("reports")


def to_markdown_str(df: pd.DataFrame) -> str:
    """Formats DataFrame as a Markdown table without requiring external tabulate dependency."""
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    separator = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = []
    for _, row in df.iterrows():
        row_str = "| " + " | ".join(str(row[c]) for c in cols) + " |"
        rows.append(row_str)
    return "\n".join([header, separator] + rows)


def run_phase_2_pipeline(
    dataset_path: Path = TRAINING_DATASET_PATH,
    min_samples: int = 300,
    epsilon: float = 1e-4,
) -> Dict[str, pd.DataFrame]:
    """Runs the complete Phase 2 skill scoring and baseline evaluation pipeline."""
    logger.info("=================================================================")
    logger.info("STARTING AAGAM PHASE 2: SKILL SCORING & BASELINES PIPELINE")
    logger.info("=================================================================")

    # 1. Load training dataset
    if not dataset_path.exists():
        raise FileNotFoundError(f"Training dataset not found at {dataset_path}")

    logger.info(f"Loading training dataset from {dataset_path}...")
    df = pd.read_parquet(dataset_path)
    logger.info(f"Loaded {len(df):,} rows across {df['valid_date'].nunique()} calendar dates.")

    # 2. Strict temporal split (PRD §7.4)
    logger.info("Splitting dataset temporally (Train, Val, Test)...")
    splits = split_dataset_temporally(df)

    # 3. Fit Hierarchical Fallback Engine on historical Training data
    logger.info(f"Initializing HierarchicalFallbackEngine with min_samples={min_samples} on Train data...")
    engine = HierarchicalFallbackEngine(splits.train_df, min_samples=min_samples)
    resolved_skill_df = engine.build_resolved_skill_table()

    # 4. Build Skill Weights Table (FR-SKILL-3, PRD §8.2)
    logger.info("Computing normalized inverse-MAE skill weights...")
    weights_df = build_skill_weights_table(resolved_skill_df, epsilon=epsilon)

    # Save skill scores and weights Parquet artifacts
    OUTPUT_SKILL_SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    resolved_skill_df.to_parquet(OUTPUT_SKILL_SCORES_PATH, index=False)
    logger.info(f"Saved skill scores Parquet to {OUTPUT_SKILL_SCORES_PATH} ({len(resolved_skill_df):,} rows).")

    weights_df.to_parquet(OUTPUT_WEIGHTS_PATH, index=False)
    logger.info(f"Saved baseline weights Parquet to {OUTPUT_WEIGHTS_PATH} ({len(weights_df):,} rows).")

    # 4b. Trailing 60-Day Window Live Weights (FR-SKILL-1)
    logger.info("Computing trailing 60-day live weights (FR-SKILL-1 live window)...")
    max_date = pd.to_datetime(df["valid_date"].max()).date()
    df_60d = filter_by_trailing_window(df, cutoff_date=max_date, window_days=60)
    engine_60d = HierarchicalFallbackEngine(df_60d, min_samples=min_samples)
    resolved_skill_60d = engine_60d.build_resolved_skill_table()
    weights_60d = build_skill_weights_table(resolved_skill_60d, epsilon=epsilon, method="inverse_mae_60d_live")
    weights_60d.to_parquet(OUTPUT_LIVE_WEIGHTS_60D_PATH, index=False)
    logger.info(f"Saved trailing 60-day live weights Parquet to {OUTPUT_LIVE_WEIGHTS_60D_PATH} ({len(weights_60d):,} rows).")

    # 5. Baseline Evaluation on Held-Out Test Set
    logger.info("Determining best-single models on training history...")
    best_single_map = determine_best_single_models(splits.train_df)
    logger.info(f"Best single models map: {best_single_map}")

    logger.info("Computing baseline forecasts on held-out test data (2026 Monsoon)...")
    test_with_baselines = compute_baseline_forecasts(
        splits.test_df,
        weights_df=weights_df,
        best_single_map=best_single_map,
    )

    candidate_cols = {
        "GFS": "f_gfs",
        "ECMWF IFS": "f_ecmwf_ifs",
        "ICON": "f_icon",
        "AIFS": "f_aifs",
        "Equal-Weight Mean": "f_equal_weight",
        "Best-Single Model": "f_best_single",
        "Inverse-MAE Blend": "f_inverse_mae",
    }

    logger.info("Evaluating candidates overall by variable...")
    eval_overall = evaluate_forecast_candidates(test_with_baselines, candidate_cols, group_cols=["variable"])

    logger.info("Evaluating candidates by (variable, lead_days)...")
    eval_lead = evaluate_forecast_candidates(test_with_baselines, candidate_cols, group_cols=["variable", "lead_days"])

    logger.info("Evaluating candidates by (variable, region)...")
    eval_region = evaluate_forecast_candidates(test_with_baselines, candidate_cols, group_cols=["variable", "region"])

    logger.info("Evaluating candidates by (variable, season)...")
    eval_season = evaluate_forecast_candidates(test_with_baselines, candidate_cols, group_cols=["variable", "season"])

    # Combine evaluations into a comprehensive comparison artifact
    eval_lead["slice_type"] = "lead_days"
    eval_lead["slice_value"] = eval_lead["lead_days"].astype(str)

    eval_region["slice_type"] = "region"
    eval_region["slice_value"] = eval_region["region"].astype(str)

    eval_season["slice_type"] = "season"
    eval_season["slice_value"] = eval_season["season"].astype(str)

    eval_overall["slice_type"] = "overall"
    eval_overall["slice_value"] = "all"

    comparisons_df = pd.concat([
        eval_overall[["variable", "slice_type", "slice_value", "candidate", "mae", "rmse", "bias", "n"]],
        eval_lead[["variable", "slice_type", "slice_value", "candidate", "mae", "rmse", "bias", "n"]],
        eval_region[["variable", "slice_type", "slice_value", "candidate", "mae", "rmse", "bias", "n"]],
        eval_season[["variable", "slice_type", "slice_value", "candidate", "mae", "rmse", "bias", "n"]],
    ], ignore_index=True)

    comparisons_df.to_parquet(OUTPUT_COMPARISONS_PATH, index=False)
    logger.info(f"Saved baseline comparisons Parquet to {OUTPUT_COMPARISONS_PATH} ({len(comparisons_df):,} rows).")

    # 6. Save Markdown summary tables for inspection
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = REPORTS_DIR / "phase_2_baseline_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("# AAGAM Phase 2: Baseline Benchmark Evaluation Summary\n\n")
        f.write("## Overall Test Performance (2026 Monsoon Test Block)\n\n")
        f.write(to_markdown_str(eval_overall))
        f.write("\n\n## Performance by Lead Day\n\n")
        f.write(to_markdown_str(eval_lead))
        f.write("\n\n## Performance by Region\n\n")
        f.write(to_markdown_str(eval_region))
    logger.info(f"Wrote markdown summary tables to {summary_path}")

    # 7. Generate Diagnostic Figures
    logger.info("Generating diagnostic figures in reports/figures/...")
    plot_skill_by_lead_day(eval_lead)
    plot_skill_by_region(eval_region)
    plot_skill_by_season(eval_season)
    plot_fallback_distribution(weights_df)
    plot_model_coverage_audit(resolved_skill_df)
    logger.info("All diagnostic figures generated successfully.")

    logger.info("=================================================================")
    logger.info("AAGAM PHASE 2 PIPELINE EXECUTION COMPLETE")
    logger.info("=================================================================")

    return {
        "skill_scores": resolved_skill_df,
        "weights": weights_df,
        "comparisons": comparisons_df,
        "eval_overall": eval_overall,
        "eval_lead": eval_lead,
        "eval_region": eval_region,
        "eval_season": eval_season,
    }


if __name__ == "__main__":
    run_phase_2_pipeline()
