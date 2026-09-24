"""Formulation B: Conservative Operational Promotion-Risk Margin with Regional Guardrail.

Authoritative source: AAGAM_MODEL_VERSIONING_DESIGN.md §K.1
                      AAGAM_MODEL_VERSIONING_ANTIGRAVITY_SPEC.md Phase 2

SAFETY AND ARCHITECTURAL RULE:
This calculation represents an operational promotion-risk margin. It is NOT
a standard error, confidence interval, statistical significance test, or
probability. It is an engineering threshold designed to prevent version flapping
and protect national and regional forecast quality.

Equations:
    required_margin = BASE_MARGIN * (1 + lambda_sample + lambda_inconsistency)

Where:
    BASE_MARGIN = 0.02 (absolute composite-score margin hurdle)
    lambda_sample = max(0.0, (1000 - N_total) / 1000)
    lambda_inconsistency = sum(n_s for strata where Y_s < 0) / N_total

Promotion requires BOTH:
    1. candidate composite advantage >= required_margin
    2. Every one of the 5 configured AAGAM regions satisfies:
       regional_score >= -0.01
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from pipeline.versioning.config import MarginConfig
from pipeline.versioning.scoring import WindowEvaluation


@dataclass
class MarginResult:
    passed: bool
    candidate_advantage: float
    required_margin: float
    base_margin: float
    lambda_sample: float
    lambda_inconsistency: float
    total_samples: int
    regional_guardrails_passed: bool
    regional_scores: Dict[str, float]
    failing_regions: List[str]
    decision: str
    reason: str


def calculate_required_margin(
    total_samples: int,
    degraded_samples: int,
    config: Optional[MarginConfig] = None,
) -> Tuple[float, float, float]:
    """Calculates Formulation B operational promotion-risk margin.

    Returns:
        (required_margin, lambda_sample, lambda_inconsistency)
    """
    cfg = config or MarginConfig()
    base = cfg.base_margin

    # Sample-size penalty (scales hurdle up if sample size < target)
    if total_samples < cfg.target_sample_volume:
        lambda_sample = max(0.0, (cfg.target_sample_volume - total_samples) / float(cfg.target_sample_volume))
    else:
        lambda_sample = 0.0

    # Inconsistency penalty (fraction of forecast volume where candidate was degraded)
    if total_samples > 0:
        lambda_inconsistency = max(0.0, float(degraded_samples) / float(total_samples))
    else:
        lambda_inconsistency = 0.0

    required_margin = base * (1.0 + lambda_sample + lambda_inconsistency)
    return required_margin, lambda_sample, lambda_inconsistency


def check_regional_guardrails(
    regional_scores: Dict[str, float],
    required_regions: Optional[List[str]] = None,
    limit: float = -0.01,
) -> Tuple[bool, List[str]]:
    """Verifies that all required regions are present and meet the non-regression limit."""
    req = required_regions or ["EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"]
    failing = []

    for r in req:
        score = regional_scores.get(r)
        if score is None:
            failing.append(f"{r} (missing)")
        elif score < limit:
            failing.append(f"{r} ({score:.4f} < {limit})")

    return len(failing) == 0, failing


def evaluate_promotion_margin(
    window_eval: WindowEvaluation,
    config: Optional[MarginConfig] = None,
    required_regions: Optional[List[str]] = None,
) -> MarginResult:
    """Evaluates whether candidate clears Formulation B operational margin and regional guardrail."""
    cfg = config or MarginConfig()
    req_regions = required_regions or ["EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"]

    # If evidence floors failed, promotion is blocked immediately with INSUFFICIENT_DATA
    if not window_eval.floors_met:
        return MarginResult(
            passed=False,
            candidate_advantage=window_eval.composite_score,
            required_margin=cfg.base_margin,
            base_margin=cfg.base_margin,
            lambda_sample=0.0,
            lambda_inconsistency=0.0,
            total_samples=window_eval.total_samples,
            regional_guardrails_passed=False,
            regional_scores=window_eval.regional_scores,
            failing_regions=[],
            decision="INSUFFICIENT_DATA",
            reason=f"Evidence floors not met: {window_eval.floor_failure_reason}",
        )

    # Calculate degraded samples from strata detail
    strata_list = window_eval.metrics_detail.get("strata", [])
    degraded_samples = sum(
        s.get("n", 0) for s in strata_list if s.get("stratum_score", 0.0) < 0.0
    )
    total_samples = window_eval.total_samples

    # Compute Formulation B operational margin
    req_margin, l_sample, l_inconsistency = calculate_required_margin(
        total_samples=total_samples,
        degraded_samples=degraded_samples,
        config=cfg,
    )

    candidate_adv = window_eval.composite_score

    # Check regional guardrails
    reg_passed, failing_regs = check_regional_guardrails(
        regional_scores=window_eval.regional_scores,
        required_regions=req_regions,
        limit=cfg.regional_non_regression_limit,
    )

    # Condition 1: Candidate advantage >= required margin
    margin_cleared = candidate_adv >= req_margin

    # Condition 2: All 5 regions satisfy regional non-regression limit
    both_conditions_met = margin_cleared and reg_passed

    if both_conditions_met:
        decision = "ELIGIBLE"
        reason = (
            f"Candidate composite advantage (+{candidate_adv:.4f}) cleared required operational margin "
            f"(+{req_margin:.4f} = base {cfg.base_margin:.4f} * [1 + sample_penalty {l_sample:.3f} + "
            f"inconsistency_penalty {l_inconsistency:.3f}]) and passed all 5 regional guardrails."
        )
    elif not margin_cleared:
        decision = "NO_IMPROVEMENT"
        reason = (
            f"Candidate composite advantage (+{candidate_adv:.4f}) failed to clear required operational margin "
            f"(+{req_margin:.4f} = base {cfg.base_margin:.4f} * [1 + sample_penalty {l_sample:.3f} + "
            f"inconsistency_penalty {l_inconsistency:.3f}])."
        )
    else:
        # Margin cleared, but regional guardrail violated
        decision = "REJECTED"
        reason = (
            f"Candidate cleared operational margin (+{candidate_adv:.4f} >= +{req_margin:.4f}), but "
            f"violated regional non-regression guardrail in region(s): {', '.join(failing_regs)}."
        )

    return MarginResult(
        passed=both_conditions_met,
        candidate_advantage=candidate_adv,
        required_margin=req_margin,
        base_margin=cfg.base_margin,
        lambda_sample=l_sample,
        lambda_inconsistency=l_inconsistency,
        total_samples=total_samples,
        regional_guardrails_passed=reg_passed,
        regional_scores=window_eval.regional_scores,
        failing_regions=failing_regs,
        decision=decision,
        reason=reason,
    )
