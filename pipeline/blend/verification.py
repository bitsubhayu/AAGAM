"""Categorical Rainfall Verification Engine for AAGAM (Phase 4, PRD §6.7, FR-VER-2, §8.5).

Computes 2x2 contingency table verification metrics for rainfall:
  - Hits (H): Forecast >= T and Observed >= T
  - False Alarms (F): Forecast >= T and Observed < T
  - Misses (M): Forecast < T and Observed >= T
  - Correct Negatives (C): Forecast < T and Observed < T

Metrics:
  - Probability of Detection (POD) = H / (H + M)
  - False Alarm Ratio (FAR) = F / (H + F)
  - Critical Success Index (CSI) = H / (H + M + F)
  - Frequency Bias (FBIAS) = (H + F) / (H + M)

Evaluated at the 4 required thresholds:
  - 2.5 mm/day: "pending confirmation"
  - 15.6 mm/day: "pending confirmation"
  - 64.5 mm/day: "official IMD" (Heavy Rain)
  - 115.6 mm/day: "official IMD" (Very Heavy Rain)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("aagam.pipeline.blend.verification")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT_DIR / "data"

VERIFICATION_THRESHOLDS = [
    {"threshold_mm": 2.5, "label": "Moderate Rain", "status": "pending confirmation"},
    {"threshold_mm": 15.6, "label": "Rather Heavy Rain", "status": "pending confirmation"},
    {"threshold_mm": 64.5, "label": "Heavy Rain", "status": "official IMD"},
    {"threshold_mm": 115.6, "label": "Very Heavy Rain", "status": "official IMD"},
]


@dataclass
class ContingencyScorecard:
    threshold_mm: float
    threshold_label: str
    status: str
    candidate: str
    hits: int
    false_alarms: int
    misses: int
    correct_negatives: int
    total_samples: int
    pod: Optional[float]
    far: Optional[float]
    csi: Optional[float]
    bias: Optional[float]
    slice_type: str = "overall"
    slice_value: str = "all"

    def to_dict(self) -> dict:
        return asdict(self)


def compute_contingency_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    threshold: float,
    label: str,
    status: str,
    candidate: str,
    slice_type: str = "overall",
    slice_value: str = "all",
) -> ContingencyScorecard:
    """Computes H, F, M, C, POD, FAR, CSI, FBIAS for a single threshold & candidate."""
    # Filter out any paired NaNs (e.g. ICON at Lead 7)
    valid_mask = (~np.isnan(y_true)) & (~np.isnan(y_pred))
    yt = y_true[valid_mask]
    yp = y_pred[valid_mask]
    n = len(yt)

    if n == 0:
        return ContingencyScorecard(
            threshold_mm=threshold,
            threshold_label=label,
            status=status,
            candidate=candidate,
            hits=0,
            false_alarms=0,
            misses=0,
            correct_negatives=0,
            total_samples=0,
            pod=None,
            far=None,
            csi=None,
            bias=None,
            slice_type=slice_type,
            slice_value=slice_value,
        )

    obs_event = yt >= threshold
    fcst_event = yp >= threshold

    h = int(np.sum(obs_event & fcst_event))
    f = int(np.sum((~obs_event) & fcst_event))
    m = int(np.sum(obs_event & (~fcst_event)))
    c = int(np.sum((~obs_event) & (~fcst_event)))

    pod = round(h / (h + m), 4) if (h + m) > 0 else 0.0
    far = round(f / (h + f), 4) if (h + f) > 0 else 0.0
    csi = round(h / (h + m + f), 4) if (h + m + f) > 0 else 0.0
    fbias = round((h + f) / (h + m), 4) if (h + m) > 0 else 0.0

    return ContingencyScorecard(
        threshold_mm=threshold,
        threshold_label=label,
        status=status,
        candidate=candidate,
        hits=h,
        false_alarms=f,
        misses=m,
        correct_negatives=c,
        total_samples=n,
        pod=pod,
        far=far,
        csi=csi,
        bias=fbias,
        slice_type=slice_type,
        slice_value=str(slice_value),
    )


class RainVerificationEngine:
    """Executes FR-VER-2 categorical scorecard across test block."""

    def __init__(
        self,
        thresholds: Optional[List[dict]] = None,
    ) -> None:
        self.thresholds = thresholds or VERIFICATION_THRESHOLDS

    def evaluate_dataset(
        self,
        df: pd.DataFrame,
        candidate_cols: Optional[Dict[str, str]] = None,
    ) -> pd.DataFrame:
        """Evaluates POD, FAR, CSI across candidates in DataFrame.

        Parameters:
            df: DataFrame containing truth and candidate columns (rain_mm).
            candidate_cols: Dict mapping candidate name to column name.
        """
        if candidate_cols is None:
            candidate_cols = {
                "GFS": "f_gfs",
                "ECMWF IFS": "f_ecmwf_ifs",
                "ICON": "f_icon",
                "AIFS": "f_aifs",
                "Equal-Weight Mean": "equal_mean",
                "Ridge": "ridge",
                "Adaptive Blend": "blended",
            }

        df_rain = df[df["variable"] == "rain_mm"].copy()
        if len(df_rain) == 0:
            logger.warning("No rain_mm rows found in evaluation dataset.")
            return pd.DataFrame()

        y_true = df_rain["truth"].values.astype(float)
        scorecards: List[ContingencyScorecard] = []

        # 1. Overall evaluation
        for t_info in self.thresholds:
            thresh = float(t_info["threshold_mm"])
            lbl = t_info["label"]
            st = t_info["status"]

            for cand_name, col in candidate_cols.items():
                if col not in df_rain.columns:
                    continue
                yp = df_rain[col].values.astype(float)
                sc = compute_contingency_metrics(
                    y_true=y_true,
                    y_pred=yp,
                    threshold=thresh,
                    label=lbl,
                    status=st,
                    candidate=cand_name,
                    slice_type="overall",
                    slice_value="all",
                )
                scorecards.append(sc)

        # 2. Evaluation by lead day
        for lead_d, lead_group in df_rain.groupby("lead_days"):
            yt_lead = lead_group["truth"].values.astype(float)

            for t_info in self.thresholds:
                thresh = float(t_info["threshold_mm"])
                lbl = t_info["label"]
                st = t_info["status"]

                for cand_name, col in candidate_cols.items():
                    if col not in lead_group.columns:
                        continue
                    yp_lead = lead_group[col].values.astype(float)
                    sc = compute_contingency_metrics(
                        y_true=yt_lead,
                        y_pred=yp_lead,
                        threshold=thresh,
                        label=lbl,
                        status=st,
                        candidate=cand_name,
                        slice_type="lead_days",
                        slice_value=str(lead_d),
                    )
                    scorecards.append(sc)

        res_df = pd.DataFrame([s.to_dict() for s in scorecards])
        return res_df

    def save_results(
        self,
        results_df: pd.DataFrame,
        parquet_path: Optional[Path] = None,
        json_path: Optional[Path] = None,
    ) -> Tuple[Path, Path]:
        """Saves verification scorecards to parquet and JSON."""
        p_out = parquet_path or (DATA_DIR / "rainfall_categorical_verification.parquet")
        j_out = json_path or (DATA_DIR / "rainfall_categorical_verification.json")

        results_df.to_parquet(p_out, index=False)

        # Structure JSON summary
        overall_sub = results_df[results_df["slice_type"] == "overall"]
        summary = {
            "evaluation_period": "2026-06-21 to 2026-09-18",
            "thresholds_evaluated": self.thresholds,
            "overall_metrics": overall_sub.to_dict(orient="records"),
        }
        with open(j_out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        logger.info(f"Saved categorical verification to {p_out} and {j_out}")
        return p_out, j_out
