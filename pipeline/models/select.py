"""Model Selection Engine for AAGAM (Phase 3, FR-BLEND-2).

Implements the deterministic selection rule per (variable, lead_days) based
strictly on the Validation partition (2026-03-23 to 2026-06-20):
  1. Lower validation MAE is selected.
  2. If validation MAEs are within 2%, average Ridge and LightGBM.

NEVER uses test data for selection decisions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("aagam.pipeline.models.select")

TOLERANCE_PCT = 0.02  # 2% threshold per PRD FR-BLEND-2


@dataclass
class SelectionDecision:
    variable: str
    lead_days: int
    val_mae_ridge: float
    val_mae_lgbm: float
    relative_diff_pct: float
    selected_engine: str  # 'ridge', 'lgbm', or 'average'
    rationale: str


def evaluate_slice_mae(y_pred: np.ndarray, y_true: np.ndarray) -> float:
    """Computes MAE for valid non-NaN prediction and truth pairs."""
    valid_mask = ~np.isnan(y_pred) & ~np.isnan(y_true)
    if not np.any(valid_mask):
        return float("inf")
    return float(np.mean(np.abs(y_pred[valid_mask] - y_true[valid_mask])))


def run_blend_selection(
    val_df: pd.DataFrame,
    pred_ridge: np.ndarray,
    pred_lgbm: np.ndarray,
    target_col: str = "truth",
    tolerance_pct: float = TOLERANCE_PCT,
) -> Dict[Tuple[str, int], SelectionDecision]:
    """Computes selection decisions for all (variable, lead_days) based strictly on validation MAE.

    Args:
        val_df: Validation DataFrame (2026-03-23 to 2026-06-20).
        pred_ridge: Ridge predictions on val_df.
        pred_lgbm: LightGBM predictions on val_df.
        target_col: Name of truth column.
        tolerance_pct: Relative difference tolerance (0.02 = 2%).

    Returns:
        Dictionary mapping (variable, lead_days) -> SelectionDecision.
    """
    logger.info("Running FR-BLEND-2 selection rule across (variable, lead_days)...")
    decisions: Dict[Tuple[str, int], SelectionDecision] = {}

    df_eval = val_df[["variable", "lead_days", target_col]].copy()
    df_eval["pred_ridge"] = pred_ridge
    df_eval["pred_lgbm"] = pred_lgbm

    grouped = df_eval.groupby(["variable", "lead_days"], observed=True)

    for (var, lead), group in grouped:
        y_true = group[target_col].to_numpy(dtype=float)
        y_ridge = group["pred_ridge"].to_numpy(dtype=float)
        y_lgbm = group["pred_lgbm"].to_numpy(dtype=float)

        mae_ridge = evaluate_slice_mae(y_ridge, y_true)
        mae_lgbm = evaluate_slice_mae(y_lgbm, y_true)

        min_mae = min(mae_ridge, mae_lgbm)
        if min_mae > 0:
            rel_diff = abs(mae_ridge - mae_lgbm) / min_mae
        else:
            rel_diff = 0.0

        if rel_diff <= tolerance_pct:
            selected = "average"
            rationale = (
                f"Validation MAEs are within {rel_diff * 100:.2f}% (<= {tolerance_pct * 100:.1f}%): "
                f"Averaging Ridge ({mae_ridge:.4f}) and LightGBM ({mae_lgbm:.4f})."
            )
        elif mae_ridge < mae_lgbm:
            selected = "ridge"
            rationale = (
                f"Ridge validation MAE ({mae_ridge:.4f}) beats LightGBM ({mae_lgbm:.4f}) "
                f"by {rel_diff * 100:.2f}% (> {tolerance_pct * 100:.1f}%)."
            )
        else:
            selected = "lgbm"
            rationale = (
                f"LightGBM validation MAE ({mae_lgbm:.4f}) beats Ridge ({mae_ridge:.4f}) "
                f"by {rel_diff * 100:.2f}% (> {tolerance_pct * 100:.1f}%)."
            )

        decisions[(var, int(lead))] = SelectionDecision(
            variable=var,
            lead_days=int(lead),
            val_mae_ridge=round(mae_ridge, 4),
            val_mae_lgbm=round(mae_lgbm, 4),
            relative_diff_pct=round(rel_diff * 100, 3),
            selected_engine=selected,
            rationale=rationale,
        )

    logger.info(f"Completed FR-BLEND-2 selection for {len(decisions)} (variable, lead_days) slices.")
    return decisions


def save_selection_decisions(
    decisions: Dict[Tuple[str, int], SelectionDecision],
    output_path: Path,
) -> None:
    """Serializes selection decisions to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = {}
    for (var, lead), dec in decisions.items():
        key = f"{var}_lead_{lead}"
        serialized[key] = asdict(dec)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serialized, f, indent=2)
    logger.info(f"Saved blend selection decisions to {output_path}")


def decisions_to_dataframe(
    decisions: Dict[Tuple[str, int], SelectionDecision],
) -> pd.DataFrame:
    """Converts selection decisions to a DataFrame for tables/reporting."""
    records = [asdict(d) for d in decisions.values()]
    return pd.DataFrame(records)
