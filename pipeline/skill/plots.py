"""Plot Generation Engine for AAGAM Skill Scoring & Baselines (Phase 2).

Produces publication-quality, reproducible diagnostic figures in reports/figures/:
  1. skill_by_lead_day.png: MAE degradation vs. Lead Days (1 to 7) across NWP models & baselines.
  2. skill_by_region.png: MAE by geographic region across NWP models & baselines.
  3. skill_by_season.png: Climatological skill variation across IMD seasons.
  4. fallback_distribution.png: Frequency distribution of resolved hierarchical fallback levels.
  5. model_coverage_audit.png: Observation counts (n) per model and lead day showing data coverage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logger = logging.getLogger("aagam.pipeline.skill.plots")

FIGURES_DIR = Path("reports/figures")

CANDIDATE_COLORS = {
    "GFS": "#1f77b4",          # Blue
    "ECMWF IFS": "#ff7f0e",     # Orange
    "ICON": "#2ca02c",          # Green
    "AIFS": "#9467bd",          # Purple
    "Equal-Weight Mean": "#7f7f7f",  # Gray dashed
    "Best-Single Model": "#8c564b",  # Brown
    "Inverse-MAE Blend": "#d62728",  # Crimson Red (Highlighted)
}

CANDIDATE_LINESTYLES = {
    "GFS": ":",
    "ECMWF IFS": "--",
    "ICON": "-.",
    "AIFS": ":",
    "Equal-Weight Mean": "--",
    "Best-Single Model": "-.",
    "Inverse-MAE Blend": "-",
}


def ensure_figures_dir() -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    return FIGURES_DIR


def plot_skill_by_lead_day(
    eval_lead_df: pd.DataFrame,
    output_path: Optional[Path] = None,
) -> Path:
    """Plots MAE vs. Lead Day (1-7) for rain_mm, tmax_c, and wind_max_kmh."""
    ensure_figures_dir()
    out_file = output_path or (FIGURES_DIR / "skill_by_lead_day.png")

    variables = ["rain_mm", "tmax_c", "wind_max_kmh"]
    var_titles = {
        "rain_mm": "Rainfall (mm/day) — MAE vs Lead Day",
        "tmax_c": "Max Temperature (°C) — MAE vs Lead Day",
        "wind_max_kmh": "Max Wind Speed (km/h) — MAE vs Lead Day",
    }
    units = {"rain_mm": "mm", "tmax_c": "°C", "wind_max_kmh": "km/h"}

    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5), dpi=150)
    fig.patch.set_facecolor("#ffffff")

    for i, var in enumerate(variables):
        ax = axes[i]
        sub_df = eval_lead_df[eval_lead_df["variable"] == var]

        candidates = sub_df["candidate"].unique()
        for cand in candidates:
            c_df = sub_df[sub_df["candidate"] == cand].sort_values("lead_days")
            color = CANDIDATE_COLORS.get(cand, "#333333")
            ls = CANDIDATE_LINESTYLES.get(cand, "-")
            lw = 2.5 if cand == "Inverse-MAE Blend" else 1.5
            marker = "o" if cand == "Inverse-MAE Blend" else "s"

            ax.plot(
                c_df["lead_days"],
                c_df["mae"],
                label=cand,
                color=color,
                linestyle=ls,
                linewidth=lw,
                marker=marker,
                markersize=5,
                alpha=0.9,
            )

        ax.set_title(var_titles[var], fontsize=12, fontweight="bold", pad=10)
        ax.set_xlabel("Forecast Lead Time (Days)", fontsize=10)
        ax.set_ylabel(f"Mean Absolute Error ({units[var]})", fontsize=10)
        ax.set_xticks(range(1, 8))
        ax.grid(True, linestyle="--", alpha=0.5)

        if i == 0:
            ax.legend(frameon=True, facecolor="#f8f9fa", edgecolor="#dddddd", fontsize=8.5)

    plt.suptitle("AAGAM Phase 2: NWP Models vs Baselines by Lead Time (Test Split: 2026 Monsoon)", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.savefig(out_file, bbox_inches="tight", dpi=200)
    plt.close()
    logger.info(f"Saved skill by lead day plot to: {out_file}")
    return out_file


def plot_skill_by_region(
    eval_region_df: pd.DataFrame,
    output_path: Optional[Path] = None,
) -> Path:
    """Plots grouped bar chart of MAE across the 5 IMD regions."""
    ensure_figures_dir()
    out_file = output_path or (FIGURES_DIR / "skill_by_region.png")

    variables = ["rain_mm", "tmax_c", "wind_max_kmh"]
    units = {"rain_mm": "mm", "tmax_c": "°C", "wind_max_kmh": "km/h"}

    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5), dpi=150)

    # Focus on key candidates to keep chart readable
    key_candidates = ["GFS", "ECMWF IFS", "ICON", "AIFS", "Equal-Weight Mean", "Inverse-MAE Blend"]

    for i, var in enumerate(variables):
        ax = axes[i]
        sub_df = eval_region_df[(eval_region_df["variable"] == var) & (eval_region_df["candidate"].isin(key_candidates))]

        regions = sorted(sub_df["region"].unique())
        n_cands = len(key_candidates)
        width = 0.8 / n_cands
        x = np.arange(len(regions))

        for j, cand in enumerate(key_candidates):
            c_df = sub_df[sub_df["candidate"] == cand]
            mae_map = dict(zip(c_df["region"], c_df["mae"]))
            maes = [mae_map.get(r, np.nan) for r in regions]

            color = CANDIDATE_COLORS.get(cand, "#333333")
            ax.bar(
                x + (j - n_cands / 2 + 0.5) * width,
                maes,
                width,
                label=cand if i == 0 else "",
                color=color,
                edgecolor="white",
                linewidth=0.5,
                alpha=0.85,
            )

        ax.set_title(f"{var} across Regions", fontsize=12, fontweight="bold", pad=10)
        ax.set_xlabel("Region", fontsize=10)
        ax.set_ylabel(f"MAE ({units[var]})", fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(regions, rotation=15, fontsize=9)
        ax.grid(True, axis="y", linestyle="--", alpha=0.5)

    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 1.05), ncol=6, frameon=True, fontsize=10)
    plt.tight_layout()
    plt.savefig(out_file, bbox_inches="tight", dpi=200)
    plt.close()
    logger.info(f"Saved skill by region plot to: {out_file}")
    return out_file


def plot_skill_by_season(
    eval_season_df: pd.DataFrame,
    output_path: Optional[Path] = None,
) -> Path:
    """Plots grouped bar chart of MAE across climatological seasons."""
    ensure_figures_dir()
    out_file = output_path or (FIGURES_DIR / "skill_by_season.png")

    variables = ["rain_mm", "tmax_c", "wind_max_kmh"]
    units = {"rain_mm": "mm", "tmax_c": "°C", "wind_max_kmh": "km/h"}

    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5), dpi=150)
    key_candidates = ["GFS", "ECMWF IFS", "ICON", "AIFS", "Equal-Weight Mean", "Inverse-MAE Blend"]

    for i, var in enumerate(variables):
        ax = axes[i]
        sub_df = eval_season_df[(eval_season_df["variable"] == var) & (eval_season_df["candidate"].isin(key_candidates))]

        seasons = [s for s in ["winter", "pre_monsoon", "monsoon", "post_monsoon"] if s in sub_df["season"].values]
        n_cands = len(key_candidates)
        width = 0.8 / n_cands
        x = np.arange(len(seasons))

        for j, cand in enumerate(key_candidates):
            c_df = sub_df[sub_df["candidate"] == cand]
            mae_map = dict(zip(c_df["season"], c_df["mae"]))
            maes = [mae_map.get(s, np.nan) for s in seasons]

            color = CANDIDATE_COLORS.get(cand, "#333333")
            ax.bar(
                x + (j - n_cands / 2 + 0.5) * width,
                maes,
                width,
                label=cand if i == 0 else "",
                color=color,
                edgecolor="white",
                linewidth=0.5,
                alpha=0.85,
            )

        ax.set_title(f"{var} by Season", fontsize=12, fontweight="bold", pad=10)
        ax.set_xlabel("Season", fontsize=10)
        ax.set_ylabel(f"MAE ({units[var]})", fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(seasons, fontsize=9)
        ax.grid(True, axis="y", linestyle="--", alpha=0.5)

    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 1.05), ncol=6, frameon=True, fontsize=10)
    plt.tight_layout()
    plt.savefig(out_file, bbox_inches="tight", dpi=200)
    plt.close()
    logger.info(f"Saved skill by season plot to: {out_file}")
    return out_file


def plot_fallback_distribution(
    weights_df: pd.DataFrame,
    output_path: Optional[Path] = None,
) -> Path:
    """Plots the distribution of resolved fallback levels across all buckets."""
    ensure_figures_dir()
    out_file = output_path or (FIGURES_DIR / "fallback_distribution.png")

    # Group by unique buckets (drop duplicates across models)
    bucket_cols = ["variable", "lead_days", "region", "season", "regime"]
    unique_buckets = weights_df.drop_duplicates(subset=bucket_cols)

    level_counts = unique_buckets["fallback_level"].value_counts().sort_index()
    level_labels = [
        "Level 0\n(Full Bucket)",
        "Level 1\n(Drop Regime)",
        "Level 2\n(Drop Season)",
        "Level 3\n(Drop Region)",
    ]

    # Map available levels to counts
    counts = [level_counts.get(i, 0) for i in range(4)]
    percentages = [100.0 * c / len(unique_buckets) if len(unique_buckets) > 0 else 0 for c in counts]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5), dpi=150)

    # Bar chart of counts
    bars = ax1.bar(
        range(4),
        counts,
        color=["#2b5c8f", "#418ab3", "#6baed6", "#bdd7e7"],
        edgecolor="#1c3b5e",
        linewidth=1.2,
    )
    ax1.set_title("Resolved Fallback Levels Count (n_min = 300)", fontsize=12, fontweight="bold")
    ax1.set_xlabel("Hierarchy Level", fontsize=10)
    ax1.set_ylabel("Number of Buckets", fontsize=10)
    ax1.set_xticks(range(4))
    ax1.set_xticklabels(level_labels, fontsize=9)
    ax1.grid(True, axis="y", linestyle="--", alpha=0.5)

    for bar, pct in zip(bars, percentages):
        height = bar.get_height()
        ax1.annotate(
            f"{int(height):,}\n({pct:.1f}%)",
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
        )

    # Histogram of bucket sample sizes
    ax2.hist(
        unique_buckets["n_bucket"],
        bins=30,
        color="#2ca02c",
        edgecolor="black",
        alpha=0.75,
    )
    ax2.axvline(300, color="red", linestyle="--", linewidth=2, label="Threshold n = 300")
    ax2.set_title("Distribution of Resolved Bucket Sample Sizes (n)", fontsize=12, fontweight="bold")
    ax2.set_xlabel("Bucket Sample Size (n)", fontsize=10)
    ax2.set_ylabel("Frequency", fontsize=10)
    ax2.grid(True, linestyle="--", alpha=0.5)
    ax2.legend(fontsize=10)

    plt.suptitle("AAGAM Hierarchical Fallback Audit (FR-SKILL-2)", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.savefig(out_file, bbox_inches="tight", dpi=200)
    plt.close()
    logger.info(f"Saved fallback distribution plot to: {out_file}")
    return out_file


def plot_model_coverage_audit(
    skill_df: pd.DataFrame,
    output_path: Optional[Path] = None,
) -> Path:
    """Plots valid sample counts (n) per model across lead days to document missing data."""
    ensure_figures_dir()
    out_file = output_path or (FIGURES_DIR / "model_coverage_audit.png")

    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5), dpi=150)
    variables = ["rain_mm", "tmax_c", "wind_max_kmh"]

    for i, var in enumerate(variables):
        ax = axes[i]
        sub_df = skill_df[skill_df["variable"] == var]

        # Aggregate total n per model and lead_days
        cov = sub_df.groupby(["model", "lead_days"], observed=True)["n_model"].sum().reset_index()

        for m in ["gfs", "ecmwf_ifs", "icon", "aifs"]:
            m_df = cov[cov["model"] == m].sort_values("lead_days")
            display_name = {
                "gfs": "GFS",
                "ecmwf_ifs": "ECMWF IFS",
                "icon": "ICON",
                "aifs": "AIFS",
            }.get(m, m)

            ax.plot(
                m_df["lead_days"],
                m_df["n_model"],
                label=display_name,
                marker="o",
                linewidth=2,
                color=CANDIDATE_COLORS.get(display_name, "#333333"),
            )

        ax.set_title(f"{var} Observation Count by Lead Time", fontsize=12, fontweight="bold")
        ax.set_xlabel("Lead Days", fontsize=10)
        ax.set_ylabel("Valid Forecast-Truth Pairs (n)", fontsize=10)
        ax.set_xticks(range(1, 8))
        ax.grid(True, linestyle="--", alpha=0.5)

        if i == 0:
            ax.legend(fontsize=9)

    plt.suptitle("AAGAM Phase 2: NWP Model Data Coverage & Gap Audit", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.savefig(out_file, bbox_inches="tight", dpi=200)
    plt.close()
    logger.info(f"Saved model coverage audit plot to: {out_file}")
    return out_file
