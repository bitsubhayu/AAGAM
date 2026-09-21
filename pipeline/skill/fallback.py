"""Hierarchical Fallback Engine for AAGAM (FR-SKILL-2).

Implements deterministic 4-level bucket fallback to prevent noisy statistical
metrics in small sample sizes (n < 300):
  Level 0: (variable, lead_days, region, season, regime)
  Level 1: (variable, lead_days, region, season)        [drop regime]
  Level 2: (variable, lead_days, region)                [drop season]
  Level 3: (variable, lead_days)                        [drop region]
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from pipeline.skill.scoring import NWP_MODELS, compute_skill_table_for_level

logger = logging.getLogger("aagam.pipeline.skill.fallback")

DEFAULT_MIN_SAMPLES = 300

HIERARCHY_LEVELS: List[Tuple[int, List[str], str]] = [
    (0, ["variable", "lead_days", "region", "season", "regime"], "full_bucket"),
    (1, ["variable", "lead_days", "region", "season"], "drop_regime"),
    (2, ["variable", "lead_days", "region"], "drop_season"),
    (3, ["variable", "lead_days"], "drop_region"),
]


class HierarchicalFallbackEngine:
    """Manages multi-level aggregation and deterministic fallback for skill scoring."""

    def __init__(
        self,
        df: pd.DataFrame,
        min_samples: int = DEFAULT_MIN_SAMPLES,
        models: Optional[List[str]] = None,
    ) -> None:
        self.df = df
        self.min_samples = min_samples
        self.models = models or NWP_MODELS
        self._level_tables: Dict[int, pd.DataFrame] = {}
        self._level_sample_counts: Dict[int, Dict[Tuple, int]] = {}
        self._precompute_all_levels()

    def _precompute_all_levels(self) -> None:
        """Precomputes skill tables and bucket row counts for all 4 hierarchy levels."""
        logger.info("Precomputing skill metric tables for all 4 hierarchy levels...")
        for level, cols, desc in HIERARCHY_LEVELS:
            # Count rows per bucket
            counts_series = self.df.groupby(cols, observed=True).size()
            counts_dict = counts_series.to_dict()
            self._level_sample_counts[level] = counts_dict

            # Compute model metrics per bucket
            table = compute_skill_table_for_level(self.df, group_cols=cols, models=self.models)
            self._level_tables[level] = table
            logger.info(
                f"Level {level} ({desc}): {len(counts_dict)} buckets precomputed "
                f"({len(table)} model-metric rows)."
            )

    def resolve_bucket(
        self,
        variable: str,
        lead_days: int,
        region: str,
        season: str,
        regime: str,
    ) -> Dict[str, Any]:
        """Resolves metrics for a target cell, falling back through the hierarchy if n < min_samples.

        Args:
            variable: Target weather variable.
            lead_days: Forecast lead day (1-7).
            region: Geographic region.
            season: Climatological season.
            regime: Synoptic regime.

        Returns:
            Dictionary with resolved bucket metadata, fallback level, sample size,
            and per-model metrics.
        """
        full_key_map = {
            "variable": variable,
            "lead_days": lead_days,
            "region": region,
            "season": season,
            "regime": regime,
        }

        # Try each hierarchy level in order
        for level, cols, desc in HIERARCHY_LEVELS:
            level_key = tuple(full_key_map[col] for col in cols)
            if len(cols) == 1:
                level_key = level_key[0]

            bucket_n = self._level_sample_counts[level].get(level_key, 0)

            # At Level 3 (root), we accept whatever sample size exists
            if bucket_n >= self.min_samples or level == 3:
                # Retrieve model metrics for this resolved bucket
                level_df = self._level_tables[level]
                mask = pd.Series(True, index=level_df.index)
                for col in cols:
                    mask &= (level_df[col] == full_key_map[col])

                matched = level_df[mask]
                model_metrics = {}
                for _, row in matched.iterrows():
                    m = row["model"]
                    model_metrics[m] = {
                        "mae": row["mae"],
                        "rmse": row["rmse"],
                        "bias": row["bias"],
                        "n": row["n"],
                    }

                return {
                    "query": full_key_map,
                    "resolved_level": level,
                    "resolved_level_desc": desc,
                    "resolved_dims": cols,
                    "n_samples": bucket_n,
                    "is_fallback": (level > 0),
                    "model_metrics": model_metrics,
                }

        raise RuntimeError(f"Fallback resolution failed unexpectedly for {full_key_map}")

    def build_resolved_skill_table(self) -> pd.DataFrame:
        """Builds a complete resolved skill score DataFrame for all Level 0 combinations."""
        # Find all unique Level 0 combinations present in the dataset
        l0_cols = HIERARCHY_LEVELS[0][1]
        unique_buckets = self.df[l0_cols].drop_duplicates().sort_values(l0_cols)

        logger.info(f"Resolving hierarchical fallback across {len(unique_buckets)} unique buckets...")
        rows = []

        for _, bucket in unique_buckets.iterrows():
            res = self.resolve_bucket(
                variable=bucket["variable"],
                lead_days=bucket["lead_days"],
                region=bucket["region"],
                season=bucket["season"],
                regime=bucket["regime"],
            )

            for m, metrics in res["model_metrics"].items():
                rows.append({
                    "variable": bucket["variable"],
                    "lead_days": bucket["lead_days"],
                    "region": bucket["region"],
                    "season": bucket["season"],
                    "regime": bucket["regime"],
                    "model": m,
                    "mae": metrics["mae"],
                    "rmse": metrics["rmse"],
                    "bias": metrics["bias"],
                    "n_model": metrics["n"],
                    "n_bucket": res["n_samples"],
                    "fallback_level": res["resolved_level"],
                    "fallback_desc": res["resolved_level_desc"],
                    "is_fallback": res["is_fallback"],
                })

        result_df = pd.DataFrame(rows)
        fallback_counts = result_df.groupby("fallback_level")["variable"].count() // len(self.models)
        logger.info(f"Fallback resolution summary (buckets per level):\n{fallback_counts}")
        return result_df
