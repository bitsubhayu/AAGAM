"""Diagnostic Plotting Engine for AAGAM Phase 3 (ML Engines & Backtest).

Produces publication-quality diagnostic figures in reports/figures/:
  1. phase3_blend_vs_baselines.png: MAE degradation vs. lead days for NWP, Ridge, LightGBM, and Blend.
  2. phase3_validation_selection.png: Ridge vs LightGBM validation MAE and FR-BLEND-2 selection decisions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logger = logging.getLogger("aagam.pipeline.models.plots")

FIGURES_DIR = Path("reports/figures")


def ensure_figures_dir() -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    return FIGURES_DIR


PHASE3_CANDIDATE_COLORS = {
    "GFS": "#1f77b4",          # Blue
    "ECMWF IFS": "#ff7f0e",     # Orange
    "ICON": "#2ca02c",          # Green
    "AIFS": "#9467bd",          # Purple
    "Equal-Weight Mean": "#7f7f7f",  # Gray dashed
    "Ridge": "#bcbd22",         # Olive Yellow
    "LightGBM": "#17becf",      # Cyan
    "Adaptive Blend": "#d62728", # Crimson Red (Star)
}

PHASE3_LINESTYLES = {
    "GFS": ":",
    "ECMWF IFS": "--",
    "ICON": "-.",
    "AIFS": ":",
    "Equal-Weight Mean": "--",
    "Ridge": "-.",
    "LightGBM": "--",
    "Adaptive Blend": "-",
}


def plot_phase3_blend_vs_baselines(
    eval_lead_df: pd.DataFrame,
    output_path: Optional[Path] = None,
) -> Path:
    """Plots test MAE vs Lead Day across all NWP models, Ridge, LightGBM, and Adaptive Blend."""
    ensure_figures_dir()
    out_file = output_path or (FIGURES_DIR / "phase3_blend_vs_baselines.png")

    variables = ["rain_mm", "tmax_c", "wind_max_kmh"]
    var_titles = {
        "rain_mm": "Rainfall (mm/day) — Test MAE vs Lead Day",
        "tmax_c": "Max Temperature (°C) — Test MAE vs Lead Day",
        "wind_max_kmh": "Max Wind Speed (km/h) — Test MAE vs Lead Day",
    }
    units = {"rain_mm": "mm", "tmax_c": "°C", "wind_max_kmh": "km/h"}

    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5), dpi=150)
    fig.patch.set_facecolor("#ffffff")

    candidates_order = [
        "GFS", "ECMWF IFS", "ICON", "AIFS",
        "Equal-Weight Mean", "Ridge", "LightGBM", "Adaptive Blend"
    ]

    for i, var in enumerate(variables):
        ax = axes[i]
        sub_df = eval_lead_df[eval_lead_df["variable"] == var]

        for cand in candidates_order:
            c_df = sub_df[sub_df["candidate"] == cand].sort_values("lead_days")
            if c_df.empty:
                continue

            color = PHASE3_CANDIDATE_COLORS.get(cand, "#333333")
            ls = PHASE3_LINESTYLES.get(cand, "-")
            lw = 2.8 if cand == "Adaptive Blend" else (2.0 if cand in ["Ridge", "LightGBM"] else 1.2)
            marker = "o" if cand == "Adaptive Blend" else ("^" if cand in ["Ridge", "LightGBM"] else "s")

            ax.plot(
                c_df["lead_days"],
                c_df["mae"],
                label=cand,
                color=color,
                linestyle=ls,
                linewidth=lw,
                marker=marker,
                markersize=6 if cand == "Adaptive Blend" else 4,
                alpha=0.95 if cand == "Adaptive Blend" else 0.85,
            )

        ax.set_title(var_titles[var], fontsize=12, fontweight="bold", pad=10)
        ax.set_xlabel("Forecast Lead Time (Days)", fontsize=10)
        ax.set_ylabel(f"Mean Absolute Error ({units[var]})", fontsize=10)
        ax.set_xticks(range(1, 8))
        ax.grid(True, linestyle="--", alpha=0.5)

        if i == 0:
            ax.legend(frameon=True, facecolor="#f8f9fa", edgecolor="#dddddd", fontsize=8.5)

    plt.suptitle("AAGAM Phase 3: Final Adaptive Blend vs. ML Engines & NWP (Held-Out 2026 Monsoon Test)", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.savefig(out_file, bbox_inches="tight", dpi=200)
    plt.close()
    logger.info(f"Saved Phase 3 blend vs baselines plot to: {out_file}")
    return out_file


def plot_phase3_validation_selection(
    decisions_df: pd.DataFrame,
    output_path: Optional[Path] = None,
) -> Path:
    """Plots Ridge vs LightGBM validation MAE and illustrates FR-BLEND-2 selection decisions."""
    ensure_figures_dir()
    out_file = output_path or (FIGURES_DIR / "phase3_validation_selection.png")

    variables = ["rain_mm", "tmax_c", "wind_max_kmh"]
    units = {"rain_mm": "mm", "tmax_c": "°C", "wind_max_kmh": "km/h"}

    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5), dpi=150)

    for i, var in enumerate(variables):
        ax = axes[i]
        sub = decisions_df[decisions_df["variable"] == var].sort_values("lead_days")

        leads = sub["lead_days"].to_numpy()
        ridge_mae = sub["val_mae_ridge"].to_numpy()
        lgbm_mae = sub["val_mae_lgbm"].to_numpy()
        engines = sub["selected_engine"].to_numpy()

        x = np.arange(len(leads))
        width = 0.35

        ax.bar(x - width/2, ridge_mae, width, label="Ridge", color="#bcbd22", alpha=0.85)
        ax.bar(x + width/2, lgbm_mae, width, label="LightGBM", color="#17becf", alpha=0.85)

        # Annotate selection
        for idx in range(len(leads)):
            eng = engines[idx].upper()
            y_pos = max(ridge_mae[idx], lgbm_mae[idx])
            badge_color = "#2ca02c" if eng == "AVERAGE" else ("#bcbd22" if eng == "RIDGE" else "#17becf")
            ax.text(
                x[idx],
                y_pos * 1.05,
                eng,
                ha="center",
                va="bottom",
                fontsize=8,
                fontweight="bold",
                color=badge_color,
            )

        ax.set_title(f"{var} Validation MAE & Engine Selection", fontsize=12, fontweight="bold", pad=10)
        ax.set_xlabel("Lead Days", fontsize=10)
        ax.set_ylabel(f"Validation MAE ({units[var]})", fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(leads)
        ax.set_ylim(0, max(np.max(ridge_mae), np.max(lgbm_mae)) * 1.25)
        ax.grid(True, axis="y", linestyle="--", alpha=0.5)

        if i == 0:
            ax.legend(frameon=True, fontsize=9)

    plt.suptitle("AAGAM Phase 3: FR-BLEND-2 Engine Selection on Validation Split (2026 Pre-Monsoon)", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.savefig(out_file, bbox_inches="tight", dpi=200)
    plt.close()
    logger.info(f"Saved Phase 3 validation selection plot to: {out_file}")
    return out_file
