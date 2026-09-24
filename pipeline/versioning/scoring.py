"""Normalized, multi-metric composite scoring engine (Design Doc §H).

Computes normalized stratum scores and window-level composite scores
comparing candidate model versions to active reference versions across:
- MAE skill: 1 - (cand_mae / ref_mae)
- RMSE skill: 1 - (cand_rmse / ref_rmse)
- Bias penalty: -abs(cand_bias - ref_bias) / (abs(ref_bias) + epsilon)
- CSI skill: cand_csi - ref_csi (for rain hazard thresholds)

Handles missing CSI metrics by dropping the CSI term and renormalizing continuous weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from pipeline.versioning.config import FloorsConfig, MarginConfig, ScoringWeights
from pipeline.versioning.floors import check_csi_event_floor, evaluate_window_floors


@dataclass
class WindowEvaluation:
    window_type: str
    window_start: Optional[date]
    window_end: Optional[date]
    composite_score: float
    regional_scores: Dict[str, float]
    strata_included: int
    strata_excluded: int
    total_samples: int
    sample_counts: Dict[str, Any]
    metrics_detail: Dict[str, Any]
    floors_met: bool
    floor_failure_reason: Optional[str] = None


def compute_stratum_score(
    cand_stratum: Dict[str, Any],
    ref_stratum: Dict[str, Any],
    weights: ScoringWeights,
    min_csi_events: int = 10,
    epsilon: float = 1e-4,
) -> Tuple[float, Dict[str, Any]]:
    """Computes normalized composite score for a single stratum comparing candidate vs reference.

    Returns:
        (stratum_score, detail_dict)
    """
    cand_mae = float(cand_stratum.get("mae", 0.0))
    ref_mae = float(ref_stratum.get("mae", 0.0))

    cand_rmse = float(cand_stratum.get("rmse", 0.0))
    ref_rmse = float(ref_stratum.get("rmse", 0.0))

    cand_bias = float(cand_stratum.get("bias", 0.0))
    ref_bias = float(ref_stratum.get("bias", 0.0))

    cand_csi = cand_stratum.get("csi")
    ref_csi = ref_stratum.get("csi")
    csi_events = cand_stratum.get("events_count") or cand_stratum.get("event_count") or 0

    # 1. MAE Skill
    if ref_mae > epsilon:
        mae_skill = 1.0 - (cand_mae / ref_mae)
    else:
        mae_skill = 0.0

    # 2. RMSE Skill
    if ref_rmse > epsilon:
        rmse_skill = 1.0 - (cand_rmse / ref_rmse)
    else:
        rmse_skill = 0.0

    # 3. Bias Penalty (normalized relative penalty)
    bias_denom = abs(ref_bias) + epsilon
    bias_penalty = -abs(cand_bias - ref_bias) / bias_denom

    # 4. CSI Skill (rain hazard thresholds only, if event floor met)
    has_valid_csi = (
        cand_csi is not None
        and ref_csi is not None
        and check_csi_event_floor(int(csi_events), min_csi_events)
    )

    if has_valid_csi:
        csi_skill = float(cand_csi) - float(ref_csi)
        w_m = weights.w_mae
        w_r = weights.w_rmse
        w_b = weights.w_bias
        w_c = weights.w_csi
        total_w = w_m + w_r + w_b + w_c
        stratum_score = (w_m * mae_skill + w_r * rmse_skill + w_b * bias_penalty + w_c * csi_skill) / total_w
    else:
        # Renormalize without CSI
        csi_skill = None
        w_m = weights.w_mae
        w_r = weights.w_rmse
        w_b = weights.w_bias
        total_w = w_m + w_r + w_b
        stratum_score = (w_m * mae_skill + w_r * rmse_skill + w_b * bias_penalty) / total_w

    detail = {
        "variable": cand_stratum.get("variable"),
        "region": cand_stratum.get("region"),
        "lead_days": cand_stratum.get("lead_days"),
        "n": cand_stratum.get("n", 0),
        "mae_cand": cand_mae,
        "mae_ref": ref_mae,
        "mae_skill": mae_skill,
        "rmse_cand": cand_rmse,
        "rmse_ref": ref_rmse,
        "rmse_skill": rmse_skill,
        "bias_cand": cand_bias,
        "bias_ref": ref_bias,
        "bias_penalty": bias_penalty,
        "csi_cand": cand_csi,
        "csi_ref": ref_csi,
        "csi_skill": csi_skill,
        "stratum_score": stratum_score,
    }

    return stratum_score, detail


def compute_composite_score(
    cand_strata: List[Dict[str, Any]],
    ref_strata: List[Dict[str, Any]],
    weights: Optional[ScoringWeights] = None,
    floors_config: Optional[FloorsConfig] = None,
    margin_config: Optional[MarginConfig] = None,
    window_type: str = "longterm",
    window_start: Optional[date] = None,
    window_end: Optional[date] = None,
) -> WindowEvaluation:
    """Evaluates all strata in an evaluation window and computes national & regional composite scores."""
    cfg_w = weights or ScoringWeights()
    cfg_f = floors_config or FloorsConfig()
    cfg_m = margin_config or MarginConfig()

    # Match candidate and reference strata by (variable, region, lead_days)
    ref_map = {
        (s.get("variable"), s.get("region"), s.get("lead_days")): s
        for s in ref_strata
    }

    paired_strata = []
    for cand_s in cand_strata:
        key = (cand_s.get("variable"), cand_s.get("region"), cand_s.get("lead_days"))
        ref_s = ref_map.get(key)
        if ref_s:
            paired_strata.append((cand_s, ref_s))

    # Evaluate floors first on candidate strata
    candidate_strata_list = [p[0] for p in paired_strata]
    floors_result = evaluate_window_floors(
        candidate_strata_list,
        floors_config=cfg_f,
        margin_config=cfg_m,
    )

    if not floors_result.floors_met:
        return WindowEvaluation(
            window_type=window_type,
            window_start=window_start,
            window_end=window_end,
            composite_score=0.0,
            regional_scores={},
            strata_included=0,
            strata_excluded=len(cand_strata),
            total_samples=floors_result.total_samples,
            sample_counts={
                "total_qualifying": floors_result.total_samples,
                "qualifying_strata": floors_result.qualifying_strata_count,
                "excluded_strata": floors_result.excluded_strata_count,
                "regions_represented": floors_result.regions_represented,
            },
            metrics_detail={"failure_reasons": floors_result.failure_reasons},
            floors_met=False,
            floor_failure_reason=floors_result.primary_failure_reason,
        )

    # Compute scores for qualifying strata
    qualifying_scores = []
    qualifying_weights = []
    strata_details = []
    regional_aggregates: Dict[str, Dict[str, float]] = {}

    for cand_s, ref_s in paired_strata:
        if cand_s.get("outcome") in ("pending", "unverifiable") or cand_s.get("degraded") is True:
            continue
        n_samples = cand_s.get("n", 0)
        if n_samples < cfg_f.min_samples_per_stratum:
            continue

        score, detail = compute_stratum_score(
            cand_s, ref_s, cfg_w, min_csi_events=cfg_f.min_csi_events
        )
        qualifying_scores.append(score)
        qualifying_weights.append(n_samples)
        strata_details.append(detail)

        # Regional tracking
        region = cand_s.get("region", "UNKNOWN")
        if region not in regional_aggregates:
            regional_aggregates[region] = {"score_sum": 0.0, "weight_sum": 0.0}
        regional_aggregates[region]["score_sum"] += score * n_samples
        regional_aggregates[region]["weight_sum"] += n_samples

    total_weight = sum(qualifying_weights)
    if total_weight > 0:
        composite_score = sum(s * w for s, w in zip(qualifying_scores, qualifying_weights)) / total_weight
    else:
        composite_score = 0.0

    # Regional composite scores
    regional_scores = {}
    for region, data in regional_aggregates.items():
        if data["weight_sum"] > 0:
            regional_scores[region] = data["score_sum"] / data["weight_sum"]
        else:
            regional_scores[region] = 0.0

    return WindowEvaluation(
        window_type=window_type,
        window_start=window_start,
        window_end=window_end,
        composite_score=composite_score,
        regional_scores=regional_scores,
        strata_included=len(qualifying_scores),
        strata_excluded=floors_result.excluded_strata_count,
        total_samples=total_weight,
        sample_counts={
            "total_qualifying": total_weight,
            "qualifying_strata": len(qualifying_scores),
            "excluded_strata": floors_result.excluded_strata_count,
            "regions_represented": floors_result.regions_represented,
        },
        metrics_detail={
            "strata": strata_details,
            "regional_scores": regional_scores,
        },
        floors_met=True,
        floor_failure_reason=None,
    )
