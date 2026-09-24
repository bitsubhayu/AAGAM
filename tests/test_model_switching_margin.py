"""Unit tests for Formulation B operational promotion-risk margin and scoring.

Authoritative source: AAGAM_MODEL_VERSIONING_DESIGN.md §H, §K.1
"""

from __future__ import annotations

import pytest

from pipeline.versioning.config import MarginConfig, ScoringWeights
from pipeline.versioning.margin import (
    calculate_required_margin,
    check_regional_guardrails,
    evaluate_promotion_margin,
)
from pipeline.versioning.scoring import (
    WindowEvaluation,
    compute_composite_score,
    compute_stratum_score,
)


class TestFormulationBMargin:
    """Tests Formulation B operational promotion-risk margin equation."""

    def test_exact_0812_vs_0814_case(self):
        """Case 1: Exact 0.812 vs 0.814 case.
        Advantage = 1 - (0.812 / 0.814) = +0.00246 (< 0.02 hurdle) => NO_IMPROVEMENT.
        """
        cand_stratum = {"mae": 0.812, "rmse": 1.0, "bias": 0.0, "variable": "rain_mm", "region": "EAST_NE", "lead_days": 1, "n": 200}
        ref_stratum = {"mae": 0.814, "rmse": 1.0, "bias": 0.0, "variable": "rain_mm", "region": "EAST_NE", "lead_days": 1, "n": 200}
        weights = ScoringWeights(w_mae=1.0, w_rmse=0.0, w_bias=0.0, w_csi=0.0)

        score, detail = compute_stratum_score(cand_stratum, ref_stratum, weights)
        advantage = score
        assert 0.002 < advantage < 0.003, f"Expected advantage around 0.0024, got {advantage}"

        # Evaluate against Formulation B margin
        req_margin, _, _ = calculate_required_margin(total_samples=1000, degraded_samples=0)
        assert req_margin == 0.02  # Base margin with N=1000 and 0 degraded

        window_eval = WindowEvaluation(
            window_type="longterm",
            window_start=None,
            window_end=None,
            composite_score=advantage,
            regional_scores={"EAST_NE": advantage, "SOUTH": advantage, "CENTRAL": advantage, "NW": advantage, "HIMALAYAN": advantage},
            strata_included=5,
            strata_excluded=0,
            total_samples=1000,
            sample_counts={"total_qualifying": 1000},
            metrics_detail={"strata": [{"n": 1000, "stratum_score": advantage}]},
            floors_met=True,
        )

        res = evaluate_promotion_margin(window_eval)
        assert res.passed is False
        assert res.decision == "NO_IMPROVEMENT"
        assert res.candidate_advantage < res.required_margin
        assert "failed to clear required operational margin" in res.reason

    def test_sample_penalty_behavior(self):
        """Case 2: Sample penalty scales up required margin when N < target_sample_volume."""
        cfg = MarginConfig(base_margin=0.02, target_sample_volume=1000)

        # Full sample size: N=1000 => lambda_sample = 0
        m1000, l_samp, _ = calculate_required_margin(1000, 0, cfg)
        assert l_samp == 0.0
        assert pytest.approx(m1000, rel=1e-5) == 0.02

        # Half sample size: N=500 => lambda_sample = 0.50 => margin = 0.02 * 1.50 = 0.03
        m500, l_samp500, _ = calculate_required_margin(500, 0, cfg)
        assert pytest.approx(l_samp500, rel=1e-5) == 0.50
        assert pytest.approx(m500, rel=1e-5) == 0.030

        # Minimum floor: N=150 => lambda_sample = 0.85 => margin = 0.02 * 1.85 = 0.037
        m150, l_samp150, _ = calculate_required_margin(150, 0, cfg)
        assert pytest.approx(l_samp150, rel=1e-5) == 0.85
        assert pytest.approx(m150, rel=1e-5) == 0.037

        # Over-sample: N=2000 => lambda_sample capped at 0.0
        m2000, l_samp2000, _ = calculate_required_margin(2000, 0, cfg)
        assert l_samp2000 == 0.0
        assert pytest.approx(m2000, rel=1e-5) == 0.02

    def test_inconsistency_penalty_behavior(self):
        """Case 3: Inconsistency penalty scales up required margin when strata are degraded."""
        cfg = MarginConfig(base_margin=0.02, target_sample_volume=1000)

        # 0% degraded => lambda_inconsistency = 0.0
        m0, _, l_incons0 = calculate_required_margin(1000, 0, cfg)
        assert l_incons0 == 0.0
        assert pytest.approx(m0, rel=1e-5) == 0.02

        # 25% degraded => lambda_inconsistency = 0.25 => margin = 0.02 * 1.25 = 0.025
        m25, _, l_incons25 = calculate_required_margin(1000, 250, cfg)
        assert pytest.approx(l_incons25, rel=1e-5) == 0.25
        assert pytest.approx(m25, rel=1e-5) == 0.025

        # Combined penalty: N=500 (l_sample=0.5) and 20% degraded (l_incons=0.2)
        # Margin = 0.02 * (1 + 0.5 + 0.2) = 0.02 * 1.7 = 0.034
        m_comb, l_s, l_i = calculate_required_margin(500, 100, cfg)
        assert pytest.approx(l_s, rel=1e-5) == 0.5
        assert pytest.approx(l_i, rel=1e-5) == 0.2
        assert pytest.approx(m_comb, rel=1e-5) == 0.034

    def test_regional_guardrail_failure(self):
        """Case 4: Candidate clears national margin but fails regional guardrail."""
        window_eval = WindowEvaluation(
            window_type="longterm",
            window_start=None,
            window_end=None,
            composite_score=0.045,  # High national advantage (+4.5%)
            regional_scores={
                "EAST_NE": 0.05,
                "SOUTH": 0.04,
                "CENTRAL": 0.04,
                "NW": 0.02,
                "HIMALAYAN": -0.015,  # VIOLATION: -1.5% < -1.0% limit
            },
            strata_included=5,
            strata_excluded=0,
            total_samples=1000,
            sample_counts={"total_qualifying": 1000},
            metrics_detail={
                "strata": [
                    {"region": "EAST_NE", "n": 200, "stratum_score": 0.05},
                    {"region": "SOUTH", "n": 200, "stratum_score": 0.04},
                    {"region": "CENTRAL", "n": 200, "stratum_score": 0.04},
                    {"region": "NW", "n": 200, "stratum_score": 0.02},
                    {"region": "HIMALAYAN", "n": 200, "stratum_score": -0.015},
                ]
            },
            floors_met=True,
        )

        res = evaluate_promotion_margin(window_eval)
        assert res.passed is False
        assert res.decision == "REJECTED"
        assert res.regional_guardrails_passed is False
        assert any("HIMALAYAN" in r for r in res.failing_regions)
        assert "violated regional non-regression guardrail" in res.reason

    def test_regional_guardrails_missing_region(self):
        """Missing a required region from regional_scores triggers guardrail rejection."""
        scores = {"EAST_NE": 0.05, "SOUTH": 0.04, "CENTRAL": 0.04, "NW": 0.02}  # Missing HIMALAYAN
        passed, failing = check_regional_guardrails(scores)
        assert passed is False
        assert any("HIMALAYAN (missing)" in f for f in failing)

    def test_zero_samples_margin_calculation(self):
        """Zero samples produces 0.0 inconsistency penalty."""
        req_margin, l_sample, l_incons = calculate_required_margin(total_samples=0, degraded_samples=0)
        assert l_incons == 0.0
        assert l_sample == 1.0
        assert req_margin == 0.04

    def test_stratum_score_epsilon_fallback(self):
        """When reference MAE/RMSE <= epsilon, skill is 0.0."""
        weights = ScoringWeights(w_mae=0.5, w_rmse=0.5, w_bias=0.0, w_csi=0.0)
        cand = {"mae": 0.1, "rmse": 0.1, "bias": 0.0}
        ref = {"mae": 0.0, "rmse": 0.0, "bias": 0.0}  # <= epsilon
        score, detail = compute_stratum_score(cand, ref, weights)
        assert detail["mae_skill"] == 0.0
        assert detail["rmse_skill"] == 0.0
        assert score == 0.0

    def test_compute_composite_score_floors_unmet(self):
        """compute_composite_score returns floors_met=False when candidate strata fail floors."""
        cand_strata = [{"variable": "rain_mm", "region": "EAST_NE", "lead_days": 1, "n": 10}]
        ref_strata = [{"variable": "rain_mm", "region": "EAST_NE", "lead_days": 1, "n": 10}]
        win_eval = compute_composite_score(cand_strata, ref_strata)
        assert win_eval.floors_met is False
        assert win_eval.composite_score == 0.0

    def test_regional_guardrails_all_pass(self):
        """All 5 regions meet non-regression limit and national advantage clears hurdle."""
        window_eval = WindowEvaluation(
            window_type="longterm",
            window_start=None,
            window_end=None,
            composite_score=0.035,
            regional_scores={
                "EAST_NE": 0.04,
                "SOUTH": 0.03,
                "CENTRAL": 0.03,
                "NW": 0.01,
                "HIMALAYAN": -0.005,  # -0.5% >= -1.0% non-regression limit
            },
            strata_included=5,
            strata_excluded=0,
            total_samples=1000,
            sample_counts={"total_qualifying": 1000},
            metrics_detail={
                "strata": [
                    {"region": "EAST_NE", "n": 200, "stratum_score": 0.04},
                    {"region": "SOUTH", "n": 200, "stratum_score": 0.03},
                    {"region": "CENTRAL", "n": 200, "stratum_score": 0.03},
                    {"region": "NW", "n": 200, "stratum_score": 0.01},
                    {"region": "HIMALAYAN", "n": 200, "stratum_score": -0.005},
                ]
            },
            floors_met=True,
        )

        res = evaluate_promotion_margin(window_eval)
        assert res.passed is True
        assert res.decision == "ELIGIBLE"
        assert res.regional_guardrails_passed is True
        assert len(res.failing_regions) == 0

    def test_missing_csi_metric_renormalization(self):
        """Verifies that missing CSI term is dropped and remaining continuous weights renormalize."""
        weights = ScoringWeights(w_mae=0.40, w_rmse=0.30, w_bias=0.15, w_csi=0.15)
        cand = {"mae": 1.8, "rmse": 2.5, "bias": 0.1, "csi": None, "events_count": 0}
        ref = {"mae": 2.0, "rmse": 3.0, "bias": 0.2, "csi": None, "events_count": 0}

        score, detail = compute_stratum_score(cand, ref, weights, min_csi_events=10)
        assert detail["csi_skill"] is None

        # Verify manual renormalization:
        mae_skill = 1.0 - (1.8 / 2.0)  # 0.10
        rmse_skill = 1.0 - (2.5 / 3.0)  # 0.166667
        bias_penalty = -abs(0.1 - 0.2) / (0.2 + 1e-4)  # -0.49975
        expected = (0.40 * mae_skill + 0.30 * rmse_skill + 0.15 * bias_penalty) / 0.85
        assert pytest.approx(score, rel=1e-4) == expected

    def test_valid_csi_inclusion_when_event_floor_met(self):
        """When event count >= 10, CSI skill is included in composite score."""
        weights = ScoringWeights(w_mae=0.40, w_rmse=0.30, w_bias=0.15, w_csi=0.15)
        cand = {"mae": 1.8, "rmse": 2.5, "bias": 0.1, "csi": 0.75, "events_count": 12}
        ref = {"mae": 2.0, "rmse": 3.0, "bias": 0.2, "csi": 0.65, "events_count": 12}

        score, detail = compute_stratum_score(cand, ref, weights, min_csi_events=10)
        assert detail["csi_skill"] == pytest.approx(0.10, rel=1e-4)
        assert score > 0.0

    def test_compute_composite_score_window_evaluation(self):
        """Verifies compute_composite_score matches paired strata and computes weighted mean."""
        cand_strata = [
            {"variable": "rain_mm", "region": "EAST_NE", "lead_days": 1, "n": 100, "mae": 1.9, "rmse": 2.8, "bias": 0.05, "csi": 0.70, "events_count": 15},
            {"variable": "tmax_c", "region": "SOUTH", "lead_days": 2, "n": 80, "mae": 1.1, "rmse": 1.5, "bias": 0.02, "csi": None, "events_count": 0},
            {"variable": "wind_max_kmh", "region": "CENTRAL", "lead_days": 3, "n": 90, "mae": 3.5, "rmse": 4.5, "bias": 0.10, "csi": None, "events_count": 0},
            {"variable": "rain_mm", "region": "NW", "lead_days": 4, "n": 70, "mae": 2.0, "rmse": 3.0, "bias": 0.08, "csi": None, "events_count": 0},
            {"variable": "tmax_c", "region": "HIMALAYAN", "lead_days": 5, "n": 60, "mae": 1.4, "rmse": 1.8, "bias": 0.03, "csi": None, "events_count": 0},
        ]
        ref_strata = [
            {"variable": "rain_mm", "region": "EAST_NE", "lead_days": 1, "n": 100, "mae": 2.0, "rmse": 3.0, "bias": 0.06, "csi": 0.60, "events_count": 15},
            {"variable": "tmax_c", "region": "SOUTH", "lead_days": 2, "n": 80, "mae": 1.2, "rmse": 1.7, "bias": 0.04, "csi": None, "events_count": 0},
            {"variable": "wind_max_kmh", "region": "CENTRAL", "lead_days": 3, "n": 90, "mae": 3.8, "rmse": 5.0, "bias": 0.15, "csi": None, "events_count": 0},
            {"variable": "rain_mm", "region": "NW", "lead_days": 4, "n": 70, "mae": 2.2, "rmse": 3.3, "bias": 0.10, "csi": None, "events_count": 0},
            {"variable": "tmax_c", "region": "HIMALAYAN", "lead_days": 5, "n": 60, "mae": 1.5, "rmse": 2.0, "bias": 0.05, "csi": None, "events_count": 0},
        ]

        win_eval = compute_composite_score(cand_strata, ref_strata, window_type="recent")
        assert win_eval.floors_met is True
        assert win_eval.composite_score > 0.0
        assert len(win_eval.regional_scores) == 5
        assert win_eval.strata_included == 5
        assert win_eval.total_samples == 400

    def test_compute_composite_score_filters_pending_and_low_sample_strata(self):
        """Filters out pending/degraded/low-n strata while keeping qualifying strata."""
        cand_strata = [
            {"variable": "rain_mm", "region": "EAST_NE", "lead_days": 1, "n": 100, "mae": 1.9, "rmse": 2.8, "bias": 0.05},
            {"variable": "tmax_c", "region": "SOUTH", "lead_days": 2, "n": 80, "mae": 1.1, "rmse": 1.5, "bias": 0.02},
            {"variable": "wind_max_kmh", "region": "CENTRAL", "lead_days": 3, "n": 90, "mae": 3.5, "rmse": 4.5, "bias": 0.10},
            {"variable": "rain_mm", "region": "NW", "lead_days": 4, "n": 70, "mae": 2.0, "rmse": 3.0, "bias": 0.08},
            {"variable": "tmax_c", "region": "HIMALAYAN", "lead_days": 5, "n": 60, "mae": 1.4, "rmse": 1.8, "bias": 0.03},
            # Strata to be filtered out:
            {"variable": "rain_mm", "region": "EAST_NE", "lead_days": 6, "n": 100, "mae": 1.9, "rmse": 2.8, "bias": 0.05, "outcome": "pending"},
            {"variable": "tmax_c", "region": "SOUTH", "lead_days": 7, "n": 80, "mae": 1.1, "rmse": 1.5, "bias": 0.02, "degraded": True},
            {"variable": "wind_max_kmh", "region": "CENTRAL", "lead_days": 0, "n": 10, "mae": 3.5, "rmse": 4.5, "bias": 0.10},  # < 30
        ]
        ref_strata = [
            {"variable": "rain_mm", "region": "EAST_NE", "lead_days": 1, "n": 100, "mae": 2.0, "rmse": 3.0, "bias": 0.06},
            {"variable": "tmax_c", "region": "SOUTH", "lead_days": 2, "n": 80, "mae": 1.2, "rmse": 1.7, "bias": 0.04},
            {"variable": "wind_max_kmh", "region": "CENTRAL", "lead_days": 3, "n": 90, "mae": 3.8, "rmse": 5.0, "bias": 0.15},
            {"variable": "rain_mm", "region": "NW", "lead_days": 4, "n": 70, "mae": 2.2, "rmse": 3.3, "bias": 0.10},
            {"variable": "tmax_c", "region": "HIMALAYAN", "lead_days": 5, "n": 60, "mae": 1.5, "rmse": 2.0, "bias": 0.05},
            {"variable": "rain_mm", "region": "EAST_NE", "lead_days": 6, "n": 100, "mae": 2.0, "rmse": 3.0, "bias": 0.06},
            {"variable": "tmax_c", "region": "SOUTH", "lead_days": 7, "n": 80, "mae": 1.2, "rmse": 1.7, "bias": 0.04},
            {"variable": "wind_max_kmh", "region": "CENTRAL", "lead_days": 0, "n": 10, "mae": 3.8, "rmse": 5.0, "bias": 0.15},
        ]

        win_eval = compute_composite_score(cand_strata, ref_strata, window_type="recent")
        assert win_eval.floors_met is True
        assert win_eval.strata_included == 5  # The 3 invalid strata were skipped
        assert win_eval.total_samples == 400


