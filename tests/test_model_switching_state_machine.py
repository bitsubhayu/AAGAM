"""Unit tests for the multi-stage model version lifecycle state machine.

Authoritative source: AAGAM_MODEL_VERSIONING_DESIGN.md §N
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pipeline.versioning.config import ModelSwitchingConfig
from pipeline.versioning.margin import MarginResult
from pipeline.versioning.scoring import WindowEvaluation
from pipeline.versioning.state_machine import (
    AutomationState,
    CandidateState,
    advance_candidate_state,
    validate_state_invariants,
)


def _make_passing_window_eval(score: float = 0.04) -> WindowEvaluation:
    return WindowEvaluation(
        window_type="longterm",
        window_start=None,
        window_end=None,
        composite_score=score,
        regional_scores={"EAST_NE": score, "SOUTH": score, "CENTRAL": score, "NW": score, "HIMALAYAN": score},
        strata_included=5,
        strata_excluded=0,
        total_samples=1000,
        sample_counts={"total_qualifying": 1000},
        metrics_detail={"strata": [{"region": r, "n": 200, "stratum_score": score} for r in ["EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"]]},
        floors_met=True,
    )


def _make_passing_margin_result(advantage: float = 0.04) -> MarginResult:
    return MarginResult(
        passed=True,
        candidate_advantage=advantage,
        required_margin=0.02,
        base_margin=0.02,
        lambda_sample=0.0,
        lambda_inconsistency=0.0,
        total_samples=1000,
        regional_guardrails_passed=True,
        regional_scores={"EAST_NE": advantage, "SOUTH": advantage, "CENTRAL": advantage, "NW": advantage, "HIMALAYAN": advantage},
        failing_regions=[],
        decision="ELIGIBLE",
        reason="Cleared margin and passed regional guardrail.",
    )


def _make_failing_margin_result(decision: str = "NO_IMPROVEMENT") -> MarginResult:
    return MarginResult(
        passed=False,
        candidate_advantage=0.002,
        required_margin=0.02,
        base_margin=0.02,
        lambda_sample=0.0,
        lambda_inconsistency=0.0,
        total_samples=1000,
        regional_guardrails_passed=True,
        regional_scores={},
        failing_regions=[],
        decision=decision,
        reason="Failed margin.",
    )


class TestStateMachine:
    """Tests lifecycle states, hysteresis, and safety guards."""

    def test_engine_dormant_by_default(self):
        """When enabled=False, state machine does not advance."""
        cfg = ModelSwitchingConfig(enabled=False)
        cand = CandidateState(id=10, status="candidate", is_active=False, parent_version_id=2)
        eval_win = _make_passing_window_eval()
        margin_res = _make_passing_margin_result()

        res = advance_candidate_state(cand, None, eval_win, margin_result=margin_res, config=cfg)
        assert res.transition_occurred is False
        assert res.to_state == "candidate"
        assert "disabled (dormant mode)" in res.reason

    def test_candidate_to_evaluating(self):
        """Candidate transitions to evaluating immediately upon processing."""
        cfg = ModelSwitchingConfig(enabled=True)
        cand = CandidateState(id=10, status="candidate", is_active=False, parent_version_id=2)
        eval_win = _make_passing_window_eval()

        res = advance_candidate_state(cand, None, eval_win, config=cfg)
        assert res.transition_occurred is True
        assert res.from_state == "candidate"
        assert res.to_state == "evaluating"
        assert cand.status == "evaluating"
        assert cand.is_active is False

    def test_eligible_is_not_promoted(self):
        """Case 7: Evaluating -> Eligible (Cycle 1 Pass) writes ELIGIBLE, not PROMOTED, is_active remains False."""
        cfg = ModelSwitchingConfig(enabled=True)
        cand = CandidateState(id=10, status="evaluating", is_active=False, parent_version_id=2)
        eval_win = _make_passing_window_eval()
        margin_res = _make_passing_margin_result()

        res = advance_candidate_state(cand, None, eval_win, margin_result=margin_res, config=cfg)
        assert res.transition_occurred is True
        assert res.from_state == "evaluating"
        assert res.to_state == "eligible"
        assert res.decision == "ELIGIBLE"
        assert res.decision != "PROMOTED"
        assert cand.status == "eligible"
        assert cand.is_active is False
        assert cand.consecutive_eligible_cycles == 1

    def test_candidate_fails_cycle2_becomes_rejected(self):
        """Case 8: Candidate passing cycle 1 but failing cycle 2 becomes REJECTED with NOT_CONFIRMED."""
        cfg = ModelSwitchingConfig(enabled=True)
        now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        cand = CandidateState(
            id=10, status="eligible", is_active=False, parent_version_id=2,
            consecutive_eligible_cycles=1, eligible_at=now - timedelta(days=7),
        )
        eval_win = _make_passing_window_eval()
        failing_margin = _make_failing_margin_result()

        res = advance_candidate_state(cand, None, eval_win, margin_result=failing_margin, config=cfg, now_dt=now)
        assert res.transition_occurred is True
        assert res.from_state == "eligible"
        assert res.to_state == "rejected"
        assert res.decision == "NOT_CONFIRMED"
        assert cand.status == "rejected"
        assert cand.is_active is False

    def test_candidate_passes_cycle2_enters_shadow(self):
        """Candidate confirming on cycle 2 enters shadow mode."""
        cfg = ModelSwitchingConfig(enabled=True)
        now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        cand = CandidateState(
            id=10, status="eligible", is_active=False, parent_version_id=2,
            consecutive_eligible_cycles=1, eligible_at=now - timedelta(days=7),
        )
        eval_win = _make_passing_window_eval()
        passing_margin = _make_passing_margin_result()

        res = advance_candidate_state(cand, None, eval_win, margin_result=passing_margin, config=cfg, now_dt=now)
        assert res.transition_occurred is True
        assert res.from_state == "eligible"
        assert res.to_state == "shadow"
        assert cand.status == "shadow"
        assert cand.shadow_started_at == now
        assert cand.consecutive_eligible_cycles == 2

    def test_shadow_failure_becomes_rejected(self):
        """Case 9: Shadow failure after duration elapsed transitions to REJECTED."""
        cfg = ModelSwitchingConfig(enabled=True)
        t0 = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        t_now = t0 + timedelta(days=8)  # > 7 days shadow duration
        cand = CandidateState(id=10, status="shadow", is_active=False, parent_version_id=2, shadow_started_at=t0)
        eval_win = _make_passing_window_eval()
        failing_margin = _make_failing_margin_result()

        res = advance_candidate_state(cand, None, eval_win, margin_result=failing_margin, config=cfg, now_dt=t_now)
        assert res.transition_occurred is True
        assert res.from_state == "shadow"
        assert res.to_state == "rejected"
        assert res.decision == "REJECTED"
        assert cand.status == "rejected"
        assert cand.is_active is False

    def test_full_progression_to_promoted(self):
        """Happy path: candidate -> evaluating -> eligible -> shadow -> canary -> active (PROMOTED)."""
        cfg = ModelSwitchingConfig(enabled=True)
        t0 = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        incumbent = CandidateState(id=2, status="active", is_active=True, parent_version_id=1, activated_at=t0 - timedelta(days=20))
        cand = CandidateState(id=3, status="canary", is_active=False, parent_version_id=2, canary_started_at=t0)

        # 15 days later (> 14 days canary duration, incumbent dwell > 14 days)
        t_now = t0 + timedelta(days=15)
        eval_win = _make_passing_window_eval()
        passing_margin = _make_passing_margin_result()

        res = advance_candidate_state(cand, incumbent, eval_win, margin_result=passing_margin, config=cfg, now_dt=t_now)
        assert res.transition_occurred is True
        assert res.from_state == "canary"
        assert res.to_state == "active"
        assert res.decision == "PROMOTED"
        assert cand.status == "active"
        assert cand.is_active is True
        assert cand.activated_at == t_now

        # Invariant: Incumbent is superseded
        assert incumbent.status == "superseded"
        assert incumbent.is_active is False
        assert incumbent.deactivated_at == t_now

    def test_state_invariants_validator(self):
        """State invariant: status == 'active' <=> is_active == True."""
        assert validate_state_invariants("active", True)[0] is True
        assert validate_state_invariants("active", False)[0] is False  # Inconsistent
        assert validate_state_invariants("candidate", False)[0] is True
        assert validate_state_invariants("candidate", True)[0] is False  # Inconsistent
        assert validate_state_invariants("eligible", False)[0] is True
        assert validate_state_invariants("shadow", False)[0] is True
        assert validate_state_invariants("canary", False)[0] is True
        assert validate_state_invariants("superseded", False)[0] is True
        assert validate_state_invariants("rejected", False)[0] is True
        assert validate_state_invariants("bogus_state", False)[0] is False

    def test_automation_frozen_blocks_progression(self):
        """When automation is frozen, candidate progression is blocked with FROZEN decision."""
        cfg = ModelSwitchingConfig(enabled=True)
        cand = CandidateState(id=10, status="candidate", is_active=False, parent_version_id=2)
        eval_win = _make_passing_window_eval()
        auto = AutomationState(frozen=True)

        res = advance_candidate_state(cand, None, eval_win, automation_state=auto, config=cfg)
        assert res.transition_occurred is False
        assert res.decision == "FROZEN"
        assert cand.status == "candidate"

    def test_cooldown_blocks_progression(self):
        """When system is in post-rollback cooldown, candidate progression is blocked with COOLDOWN decision."""
        cfg = ModelSwitchingConfig(enabled=True)
        t_now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        cand = CandidateState(id=10, status="candidate", is_active=False, parent_version_id=2)
        eval_win = _make_passing_window_eval()
        auto = AutomationState(cooldown_until=t_now + timedelta(days=3))

        res = advance_candidate_state(cand, None, eval_win, automation_state=auto, config=cfg, now_dt=t_now)
        assert res.transition_occurred is False
        assert res.decision == "COOLDOWN"
        assert cand.status == "candidate"

    def test_terminal_state_cannot_advance(self):
        """Terminal states (rejected, superseded, rolled_back) do not advance."""
        cfg = ModelSwitchingConfig(enabled=True)
        cand = CandidateState(id=10, status="rejected", is_active=False, parent_version_id=2)
        eval_win = _make_passing_window_eval()

        res = advance_candidate_state(cand, None, eval_win, config=cfg)
        assert res.transition_occurred is False
        assert res.from_state == "rejected"
        assert res.to_state == "rejected"

    def test_evaluating_rejected_due_to_floors(self):
        """Candidate in evaluating transitions to rejected if floors not met."""
        cfg = ModelSwitchingConfig(enabled=True)
        cand = CandidateState(id=10, status="evaluating", is_active=False, parent_version_id=2)
        failing_win = WindowEvaluation(
            window_type="longterm",
            window_start=None,
            window_end=None,
            composite_score=0.05,
            regional_scores={},
            strata_included=0,
            strata_excluded=5,
            total_samples=0,
            sample_counts={},
            metrics_detail={},
            floors_met=False,
            floor_failure_reason="Qualifying strata count below floor",
        )

        res = advance_candidate_state(cand, None, failing_win, config=cfg)
        assert res.transition_occurred is True
        assert res.to_state == "rejected"
        assert res.decision == "INSUFFICIENT_DATA"

    def test_evaluating_rejected_due_to_recent_window_veto(self):
        """Recent window severe degradation vetoes promotion."""
        cfg = ModelSwitchingConfig(enabled=True)
        cand = CandidateState(id=10, status="evaluating", is_active=False, parent_version_id=2)
        eval_win = _make_passing_window_eval(score=0.04)
        margin_res = _make_passing_margin_result(advantage=0.04)

        # Recent window severely degraded beyond -required_margin (-0.03 < -0.02)
        recent_win = _make_passing_window_eval(score=-0.03)

        res = advance_candidate_state(cand, None, eval_win, recent_eval=recent_win, margin_result=margin_res, config=cfg)
        assert res.transition_occurred is True
        assert res.to_state == "rejected"
        assert res.decision == "REJECTED"
        assert "Recent window veto" in res.reason

    def test_shadow_dwell_unelapsed_holds(self):
        """Candidate in shadow mode holds until shadow duration elapses."""
        cfg = ModelSwitchingConfig(enabled=True)
        t0 = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        cand = CandidateState(id=10, status="shadow", is_active=False, parent_version_id=2, shadow_started_at=t0)
        eval_win = _make_passing_window_eval()
        t_now = t0 + timedelta(days=3)  # Only 3 days elapsed (< 7 days)

        res = advance_candidate_state(cand, None, eval_win, config=cfg, now_dt=t_now)
        assert res.transition_occurred is False
        assert res.to_state == "shadow"
        assert "3/7 days elapsed" in res.reason

    def test_canary_dwell_unelapsed_holds(self):
        """Candidate in canary mode holds until canary duration elapses."""
        cfg = ModelSwitchingConfig(enabled=True)
        t0 = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        cand = CandidateState(id=10, status="canary", is_active=False, parent_version_id=2, canary_started_at=t0)
        eval_win = _make_passing_window_eval()
        t_now = t0 + timedelta(days=10)  # Only 10 days elapsed (< 14 days)

        res = advance_candidate_state(cand, None, eval_win, config=cfg, now_dt=t_now)
        assert res.transition_occurred is False
        assert res.to_state == "canary"
        assert "10/14 days elapsed" in res.reason

    def test_incumbent_active_dwell_unelapsed_holds(self):
        """Incumbent active version must dwell at least 14 days before replacement."""
        cfg = ModelSwitchingConfig(enabled=True)
        t_now = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)
        # Incumbent activated only 5 days ago!
        incumbent = CandidateState(id=2, status="active", is_active=True, parent_version_id=1, activated_at=t_now - timedelta(days=5))
        cand = CandidateState(id=3, status="canary", is_active=False, parent_version_id=2, canary_started_at=t_now - timedelta(days=16))
        eval_win = _make_passing_window_eval()
        margin_res = _make_passing_margin_result()

        res = advance_candidate_state(cand, incumbent, eval_win, margin_result=margin_res, config=cfg, now_dt=t_now)
        assert res.transition_occurred is False
        assert res.to_state == "canary"
        assert "minimum dwell time" in res.reason

    def test_canary_failure_becomes_rejected(self):
        """Canary failure after 14 days transitions to rejected."""
        cfg = ModelSwitchingConfig(enabled=True)
        t0 = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        incumbent = CandidateState(id=2, status="active", is_active=True, parent_version_id=1, activated_at=t0 - timedelta(days=30))
        cand = CandidateState(id=3, status="canary", is_active=False, parent_version_id=2, canary_started_at=t0)
        t_now = t0 + timedelta(days=15)
        eval_win = _make_passing_window_eval()
        failing_margin = _make_failing_margin_result()

        res = advance_candidate_state(cand, incumbent, eval_win, margin_result=failing_margin, config=cfg, now_dt=t_now)
        assert res.transition_occurred is True
        assert res.to_state == "rejected"
        assert res.decision == "REJECTED"
        assert cand.status == "rejected"

    def test_evaluating_rejected_when_margin_result_none(self):
        """Evaluating transitions to rejected if margin_result is None."""
        cfg = ModelSwitchingConfig(enabled=True)
        cand = CandidateState(id=10, status="evaluating", is_active=False, parent_version_id=2)
        eval_win = _make_passing_window_eval()

        res = advance_candidate_state(cand, None, eval_win, margin_result=None, config=cfg)
        assert res.transition_occurred is True
        assert res.to_state == "rejected"
        assert res.decision == "NO_IMPROVEMENT"

    def test_shadow_initializes_timestamp_when_none(self):
        """Shadow mode initializes shadow_started_at if not set."""
        cfg = ModelSwitchingConfig(enabled=True)
        t_now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        cand = CandidateState(id=10, status="shadow", is_active=False, parent_version_id=2, shadow_started_at=None)
        eval_win = _make_passing_window_eval()

        res = advance_candidate_state(cand, None, eval_win, config=cfg, now_dt=t_now)
        assert res.transition_occurred is False
        assert cand.shadow_started_at == t_now
        assert "Initialized shadow timestamp" in res.reason

    def test_shadow_passes_to_canary(self):
        """Shadow mode transitions to canary when duration elapses and margin passes."""
        cfg = ModelSwitchingConfig(enabled=True)
        t0 = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        cand = CandidateState(id=10, status="shadow", is_active=False, parent_version_id=2, shadow_started_at=t0)
        t_now = t0 + timedelta(days=8)  # 8 days > 7 days
        eval_win = _make_passing_window_eval()
        margin_res = _make_passing_margin_result()

        res = advance_candidate_state(cand, None, eval_win, margin_result=margin_res, config=cfg, now_dt=t_now)
        assert res.transition_occurred is True
        assert res.from_state == "shadow"
        assert res.to_state == "canary"
        assert cand.status == "canary"
        assert cand.canary_started_at == t_now

    def test_canary_initializes_timestamp_when_none(self):
        """Canary mode initializes canary_started_at if not set."""
        cfg = ModelSwitchingConfig(enabled=True)
        t_now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        cand = CandidateState(id=10, status="canary", is_active=False, parent_version_id=2, canary_started_at=None)
        eval_win = _make_passing_window_eval()

        res = advance_candidate_state(cand, None, eval_win, config=cfg, now_dt=t_now)
        assert res.transition_occurred is False
        assert cand.canary_started_at == t_now
        assert "Initialized canary timestamp" in res.reason

    def test_unhandled_state_returns_no_transition(self):
        """Unknown or unhandled state returns transition_occurred=False."""
        cfg = ModelSwitchingConfig(enabled=True)
        cand = CandidateState(id=10, status="unknown_state", is_active=False, parent_version_id=2)
        eval_win = _make_passing_window_eval()

        res = advance_candidate_state(cand, None, eval_win, config=cfg)
        assert res.transition_occurred is False
        assert "No transition defined" in res.reason


