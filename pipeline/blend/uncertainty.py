"""Historical Spread & High Uncertainty Engine for AAGAM (Phase 4, PRD §6.5, FR-EXT-3, §8.4).

Computes historical ensemble spread distribution on training data:
  - Spread = row-wise standard deviation across available NWP forecasts:
    std(f_gfs, f_ecmwf_ifs, f_icon, f_aifs)
  - P90 Threshold = 90th percentile of historical spread per bucket
  - High Uncertainty Flag = True when forecast spread > historical P90
  - Employs hierarchical fallback if bucket sample size < n_min (300).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pipeline.skill.fallback import HierarchicalFallbackEngine
from pipeline.skill.scoring import MODEL_COLS, NWP_MODELS

logger = logging.getLogger("aagam.pipeline.blend.uncertainty")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT_DIR / "data"

DEFAULT_PERCENTILE = 90.0
DEFAULT_N_MIN = 300


@dataclass
class BucketSpreadThreshold:
    variable: str
    lead_days: int
    region: str
    season: str
    regime: str
    p90_spread: float
    fallback_level: int
    fallback_desc: str
    n_samples: int


class HighUncertaintyEngine:
    """Calculates and evaluates high uncertainty thresholds based on historical model spread."""

    def __init__(
        self,
        thresholds_df: Optional[pd.DataFrame] = None,
        percentile: float = DEFAULT_PERCENTILE,
    ) -> None:
        self.percentile = percentile
        self.bucket_thresholds: Dict[Tuple[str, int, str, str, str], BucketSpreadThreshold] = {}
        if thresholds_df is not None:
            self._load_from_df(thresholds_df)

    def _load_from_df(self, df: pd.DataFrame) -> None:
        """Loads threshold lookup dictionary from DataFrame."""
        for _, row in df.iterrows():
            key = (
                str(row["variable"]),
                int(row["lead_days"]),
                str(row["region"]),
                str(row["season"]),
                str(row["regime"]),
            )
            self.bucket_thresholds[key] = BucketSpreadThreshold(
                variable=str(row["variable"]),
                lead_days=int(row["lead_days"]),
                region=str(row["region"]),
                season=str(row["season"]),
                regime=str(row["regime"]),
                p90_spread=float(row["p90_spread"]),
                fallback_level=int(row["fallback_level"]),
                fallback_desc=str(row["fallback_desc"]),
                n_samples=int(row["n_samples"]),
            )

    def compute_from_training_data(
        self,
        train_df: pd.DataFrame,
        fallback_engine: Optional[HierarchicalFallbackEngine] = None,
        n_min: int = DEFAULT_N_MIN,
    ) -> pd.DataFrame:
        """Computes P90 spread thresholds per bucket from the historical training dataset.

        Uses HierarchicalFallbackEngine to ensure all 1,094 operational buckets
        have robust sample size (n >= n_min).
        """
        logger.info("Computing historical ensemble spread distribution on training dataset...")
        df = train_df.copy()

        # Compute spread across available model forecasts
        model_cols = [MODEL_COLS[m] for m in NWP_MODELS if MODEL_COLS[m] in df.columns]
        df["calc_spread"] = df[model_cols].std(axis=1, ddof=1)

        if fallback_engine is None:
            fallback_engine = HierarchicalFallbackEngine(df, min_samples=n_min)

        l0_cols = ["variable", "lead_days", "region", "season", "regime"]
        unique_buckets = df[l0_cols].drop_duplicates().sort_values(l0_cols)

        # Cache slice P90s by (level, query_dims_tuple)
        slice_cache: Dict[Tuple[int, Tuple], Tuple[float, int]] = {}
        records: List[dict] = []

        for _, b in unique_buckets.iterrows():
            var, lead, reg, seas, regime = (
                b["variable"],
                b["lead_days"],
                b["region"],
                b["season"],
                b["regime"],
            )

            res = fallback_engine.resolve_bucket(var, lead, reg, seas, regime)
            res_level = res["resolved_level"]
            res_dims = res["resolved_dims"]
            res_desc = res["resolved_level_desc"]
            cache_key = (res_level, tuple(res["query"][col] for col in res_dims))

            if cache_key in slice_cache:
                p90, n_s = slice_cache[cache_key]
            else:
                mask = pd.Series(True, index=df.index)
                for col in res_dims:
                    mask &= (df[col] == res["query"][col])
                spreads = df.loc[mask, "calc_spread"].dropna()
                n_s = len(spreads)
                if n_s > 0:
                    p90 = float(np.percentile(spreads, self.percentile))
                else:
                    # Generic fallback if empty
                    p90 = 5.0
                slice_cache[cache_key] = (p90, n_s)

            records.append({
                "variable": var,
                "lead_days": lead,
                "region": reg,
                "season": seas,
                "regime": regime,
                "p90_spread": round(p90, 4),
                "fallback_level": res_level,
                "fallback_desc": res_desc,
                "n_samples": n_s,
            })

        thresholds_df = pd.DataFrame(records)
        self._load_from_df(thresholds_df)
        return thresholds_df

    def evaluate_uncertainty(
        self,
        variable: str,
        lead_days: int,
        region: str,
        season: str,
        regime: str,
        spread: float,
    ) -> Tuple[bool, float, str]:
        """Evaluates whether the given spread triggers high uncertainty (FR-EXT-3).

        Returns:
            Tuple of (is_high_uncertainty, p90_threshold, bucket_desc).
        """
        key = (variable, lead_days, region, season, regime)
        obj = self.bucket_thresholds.get(key)
        if obj is not None:
            p90 = obj.p90_spread
            desc = f"{obj.fallback_desc} (n={obj.n_samples})"
        else:
            # Fallback P90 default
            p90 = 5.0
            desc = "global_default"

        is_high = bool(spread > p90) if not pd.isna(spread) else False
        return is_high, p90, desc

    def evaluate_dataframe(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Adds p90_spread, bucket_used, and high_uncertainty columns to a DataFrame."""
        out = df.copy()
        is_high_list = []
        p90_list = []
        desc_list = []

        for _, row in out.iterrows():
            spread_val = row.get("spread")
            if spread_val is None or pd.isna(spread_val):
                # Calculate from models
                m_vals = [row.get(MODEL_COLS[m]) for m in NWP_MODELS if row.get(MODEL_COLS[m]) is not None]
                m_valid = [v for v in m_vals if not pd.isna(v)]
                spread_val = float(np.std(m_valid, ddof=1)) if len(m_valid) > 1 else 0.0

            is_high, p90, desc = self.evaluate_uncertainty(
                variable=str(row["variable"]),
                lead_days=int(row["lead_days"]),
                region=str(row["region"]),
                season=str(row["season"]),
                regime=str(row["regime"]),
                spread=float(spread_val),
            )
            is_high_list.append(is_high)
            p90_list.append(p90)
            desc_list.append(desc)

        out["p90_spread"] = p90_list
        out["bucket_used"] = desc_list
        out["high_uncertainty"] = is_high_list
        return out

    def save(self, output_path: Optional[Path] = None) -> Path:
        """Saves threshold lookup table to parquet."""
        out = output_path or (DATA_DIR / "historical_spread_p90.parquet")
        records = [
            {
                "variable": obj.variable,
                "lead_days": obj.lead_days,
                "region": obj.region,
                "season": obj.season,
                "regime": obj.regime,
                "p90_spread": obj.p90_spread,
                "fallback_level": obj.fallback_level,
                "fallback_desc": obj.fallback_desc,
                "n_samples": obj.n_samples,
            }
            for obj in self.bucket_thresholds.values()
        ]
        df = pd.DataFrame(records).sort_values(["variable", "lead_days", "region", "season", "regime"])
        df.to_parquet(out, index=False)
        logger.info(f"Saved {len(df):,} historical P90 spread thresholds to {out}")
        return out


def load_or_build_uncertainty_engine(
    recompute: bool = False,
    data_dir: Optional[Path] = None,
) -> HighUncertaintyEngine:
    """Loads existing P90 spread thresholds or computes them from training dataset."""
    d_dir = data_dir or DATA_DIR
    target_path = d_dir / "historical_spread_p90.parquet"

    engine = HighUncertaintyEngine()
    if target_path.exists() and not recompute:
        df = pd.read_parquet(target_path)
        engine._load_from_df(df)
        return engine

    train_path = d_dir / "training_dataset.parquet"
    if not train_path.exists():
        raise FileNotFoundError(f"Training dataset not found: {train_path}")

    df_full = pd.read_parquet(train_path)
    # Strictly training block only: 2024-01-20 to 2026-03-22
    df_train = df_full[df_full["valid_date"] <= pd.to_datetime("2026-03-22").date()]

    engine.compute_from_training_data(df_train)
    engine.save(target_path)
    return engine
