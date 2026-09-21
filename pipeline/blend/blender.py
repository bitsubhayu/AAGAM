"""Adaptive Blending Engine for AAGAM (Phase 3, FR-BLEND-1, FR-BLEND-3, FR-BLEND-4).

Produces required forecast fields for every cell:
  - blended: Final selected blend (Ridge, LightGBM, or 50/50 average)
  - ridge: Ridge stacking forecast
  - lgbm: LightGBM forecast
  - equal_mean: Arithmetic mean across available models
  - spread: Standard deviation across the 4 model forecasts
  - models_over_threshold: Count of models exceeding authoritative advisory thresholds
  - degraded: True if any model forecast is NaN, False otherwise
  - selected_engine: 'ridge', 'lgbm', or 'average'
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

from pipeline.models.select import SelectionDecision
from pipeline.skill.scoring import MODEL_COLS, NWP_MODELS

logger = logging.getLogger("aagam.pipeline.blend.blender")

THRESHOLDS_CONFIG_PATH = Path("config/thresholds.yaml")

DEFAULT_ADVISORY_THRESHOLDS = {
    "rain_mm": 64.5,      # mm/day (IMD heavy rainfall)
    "tmax_c": 40.0,       # °C (IMD plains heat wave threshold)
    "wind_max_kmh": 50.0, # km/h (Beaufort moderate gale)
}


def load_advisory_thresholds(config_path: Path = THRESHOLDS_CONFIG_PATH) -> Dict[str, float]:
    """Loads authoritative advisory thresholds from config/thresholds.yaml."""
    thresholds = dict(DEFAULT_ADVISORY_THRESHOLDS)
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            if "rain" in cfg and "alert_levels" in cfg["rain"]:
                thresholds["rain_mm"] = float(cfg["rain"]["alert_levels"]["advisory"].get("min_single_model", 64.5))
            if "heatwave" in cfg and "thresholds_by_terrain" in cfg["heatwave"]:
                thresholds["tmax_c"] = float(cfg["heatwave"]["thresholds_by_terrain"]["plains"].get("absolute_min_tmax", 40.0))
            if "wind" in cfg:
                thresholds["wind_max_kmh"] = float(cfg["wind"].get("advisory", 50.0))
        except Exception as e:
            logger.warning(f"Could not parse {config_path}, using defaults: {e}")
    return thresholds


class AagamBlender:
    """Combines Ridge, LightGBM, and NWP candidates into authoritative blended forecasts."""

    def __init__(
        self,
        selection_decisions: Dict[Tuple[str, int], SelectionDecision],
        models: Optional[List[str]] = None,
        thresholds: Optional[Dict[str, float]] = None,
    ) -> None:
        self.selection_decisions = selection_decisions
        self.models = models or NWP_MODELS
        self.model_cols = [MODEL_COLS[m] for m in self.models]
        self.thresholds = thresholds or load_advisory_thresholds()

    def blend_dataframe(
        self,
        df: pd.DataFrame,
        pred_ridge: np.ndarray,
        pred_lgbm: np.ndarray,
        degraded_ridge: Optional[np.ndarray] = None,
    ) -> pd.DataFrame:
        """Assembles all FR-BLEND-1 output columns for the provided DataFrame.

        Args:
            df: Input DataFrame containing model forecast columns.
            pred_ridge: Array of Ridge predictions.
            pred_lgbm: Array of LightGBM predictions.
            degraded_ridge: Optional array of boolean degraded flags from Ridge engine.

        Returns:
            DataFrame with [blended, ridge, lgbm, equal_mean, spread,
                            models_over_threshold, degraded, selected_engine].
        """
        out_df = df.copy()
        out_df["ridge"] = pred_ridge
        out_df["lgbm"] = pred_lgbm

        # 1. Equal-Weight Mean
        out_df["equal_mean"] = out_df[self.model_cols].mean(axis=1, skipna=True)

        # 2. Spread (std across the 4 model forecasts)
        out_df["spread"] = out_df[self.model_cols].std(axis=1, skipna=True)

        # 3. Degraded Flag (FR-BLEND-4)
        if degraded_ridge is not None:
            out_df["degraded"] = degraded_ridge
        else:
            out_df["degraded"] = out_df[self.model_cols].isna().any(axis=1)

        # 4. Models Over Threshold
        # Count models exceeding advisory threshold for the row's variable
        models_over_list = []
        for _, row in out_df[["variable"] + self.model_cols].iterrows():
            var = row["variable"]
            thresh = self.thresholds.get(var, float("inf"))
            count = 0
            for col in self.model_cols:
                val = row[col]
                if not pd.isna(val) and val >= thresh:
                    count += 1
            models_over_list.append(count)
        out_df["models_over_threshold"] = models_over_list

        # 5. Final Selected Blend (FR-BLEND-2)
        blended_series = np.empty(len(out_df), dtype=float)
        selected_engine_series = []

        var_leads = zip(out_df["variable"], out_df["lead_days"])
        for idx, (var, lead) in enumerate(var_leads):
            dec = self.selection_decisions.get((var, int(lead)))
            r_val = pred_ridge[idx]
            l_val = pred_lgbm[idx]

            if dec is None:
                # Default to 50/50 average
                engine = "average"
                b_val = 0.5 * (r_val + l_val)
            elif dec.selected_engine == "ridge":
                engine = "ridge"
                b_val = r_val
            elif dec.selected_engine == "lgbm":
                engine = "lgbm"
                b_val = l_val
            else:  # "average"
                engine = "average"
                b_val = 0.5 * (r_val + l_val)

            # Physical non-negativity constraint for rain and wind
            if var in ["rain_mm", "wind_max_kmh"] and not np.isnan(b_val):
                b_val = max(0.0, b_val)

            blended_series[idx] = b_val
            selected_engine_series.append(engine)

        out_df["blended"] = blended_series
        out_df["selected_engine"] = selected_engine_series

        logger.info(
            f"Assembled blended forecasts for {len(out_df):,} rows "
            f"({out_df['degraded'].sum():,} degraded rows)."
        )
        return out_df
