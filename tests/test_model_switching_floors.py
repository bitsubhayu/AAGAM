"""Unit tests for evidence and sample floors in model switching.

Authoritative source: AAGAM_MODEL_VERSIONING_DESIGN.md §I
"""

from __future__ import annotations

from pipeline.versioning.floors import (
    check_csi_event_floor,
    check_min_lead_days,
    check_min_regions_represented,
    check_min_samples_per_stratum,
    check_min_strata,
    evaluate_window_floors,
)
from pipeline.versioning.margin import evaluate_promotion_margin
from pipeline.versioning.scoring import WindowEvaluation


class TestEvidenceFloors:
    """Tests sample size, regional coverage, and evidence floor rules."""

    def test_min_samples_per_stratum(self):
        """Strata with < 30 samples fail stratum floor."""
        assert check_min_samples_per_stratum(30, min_samples=30) is True
        assert check_min_samples_per_stratum(45, min_samples=30) is True
        assert check_min_samples_per_stratum(29, min_samples=30) is False
        assert check_min_samples_per_stratum(0, min_samples=30) is False

    def test_min_strata_count(self):
        """Evaluation requires at least 5 qualifying strata."""
        assert check_min_strata(5, min_strata=5) is True
        assert check_min_strata(8, min_strata=5) is True
        assert check_min_strata(4, min_strata=5) is False

    def test_all_five_regions_required(self):
        """Case 5: All 5 configured AAGAM regions must contribute qualifying strata."""
        all_five = {"EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"}
        passed, missing = check_min_regions_represented(all_five)
        assert passed is True
        assert missing == []

        # Missing HIMALAYAN
        four_regions = {"EAST_NE", "SOUTH", "CENTRAL", "NW"}
        passed, missing = check_min_regions_represented(four_regions)
        assert passed is False
        assert missing == ["HIMALAYAN"]

    def test_min_lead_days(self):
        """Evaluation requires at least 4 distinct lead days represented."""
        assert check_min_lead_days({0, 1, 2, 3}, min_leads=4) is True
        assert check_min_lead_days({0, 2, 4, 6, 7}, min_leads=4) is True
        assert check_min_lead_days({0, 1, 2}, min_leads=4) is False

    def test_csi_event_floor(self):
        """CSI term requires >= 10 verified threshold events."""
        assert check_csi_event_floor(10, min_events=10) is True
        assert check_csi_event_floor(15, min_events=10) is True
        assert check_csi_event_floor(9, min_events=10) is False

    def test_exclude_pending_unverifiable_degraded_rows(self):
        """Pending, unverifiable, and degraded rows are excluded from floor counts."""
        strata = [
            {"region": "EAST_NE", "lead_days": 1, "n": 50, "outcome": "verified"},
            {"region": "SOUTH", "lead_days": 2, "n": 40, "outcome": "pending"},  # Excluded
            {"region": "CENTRAL", "lead_days": 3, "n": 60, "outcome": "unverifiable"},  # Excluded
            {"region": "NW", "lead_days": 4, "n": 45, "degraded": True},  # Excluded
            {"region": "HIMALAYAN", "lead_days": 5, "n": 35, "outcome": "verified"},
        ]
        res = evaluate_window_floors(strata)
        assert res.qualifying_strata_count == 2  # Only EAST_NE and HIMALAYAN qualify
        assert res.excluded_strata_count == 3
        assert res.floors_met is False
        assert any("Missing required regions" in r for r in res.failure_reasons)

    def test_insufficient_evidence_blocks_promotion(self):
        """Case 6: Insufficient evidence produces INSUFFICIENT_DATA decision, blocking promotion."""
        # Under-sampled window (e.g. total samples = 100 < 150 floor)
        strata = [
            {"region": "EAST_NE", "lead_days": 1, "n": 20},  # < 30 excluded
            {"region": "SOUTH", "lead_days": 2, "n": 20},
            {"region": "CENTRAL", "lead_days": 3, "n": 20},
            {"region": "NW", "lead_days": 4, "n": 20},
            {"region": "HIMALAYAN", "lead_days": 5, "n": 20},
        ]
        floors_res = evaluate_window_floors(strata)
        assert floors_res.floors_met is False
        assert floors_res.qualifying_strata_count == 0

        window_eval = WindowEvaluation(
            window_type="longterm",
            window_start=None,
            window_end=None,
            composite_score=0.10,  # High nominal advantage
            regional_scores={},
            strata_included=0,
            strata_excluded=5,
            total_samples=0,
            sample_counts={"total_qualifying": 0},
            metrics_detail={"failure_reasons": floors_res.failure_reasons},
            floors_met=False,
            floor_failure_reason=floors_res.primary_failure_reason,
        )

        margin_res = evaluate_promotion_margin(window_eval)
        assert margin_res.passed is False
        assert margin_res.decision == "INSUFFICIENT_DATA"
        assert "Evidence floors not met" in margin_res.reason
