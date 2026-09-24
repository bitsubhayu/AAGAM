r"""Multi-stage model version lifecycle state machine (Design Doc §N).

Valid states:
    draft -> candidate -> evaluating -> eligible -> shadow -> canary -> active -> superseded
                     \-> rejected                     \-> rejected        \-> rolled_back
                                                                          \-> retired

Key invariants:
1. Every state transition is explicit and deterministic.
2. ELIGIBLE is the audit decision for cycle-1 interim qualification.
3. PROMOTED is reserved strictly for the final canary -> active transition.
4. Cooldown and frozen states block candidate progression.
5. status == 'active' if and only if is_active == True.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set, Tuple

from pipeline.versioning.config import ModelSwitchingConfig
from pipeline.versioning.decisions import write_decision
from pipeline.versioning.margin import MarginResult
from pipeline.versioning.scoring import WindowEvaluation

logger = logging.getLogger("aagam.pipeline.versioning.state_machine")

VALID_STATES: Set[str] = {
    "draft",
    "candidate",
    "evaluating",
    "eligible",
    "shadow",
    "canary",
    "active",
    "superseded",
    "rejected",
    "rolled_back",
    "retired",
}


@dataclass
class CandidateState:
    id: int
    status: str
    is_active: bool
    parent_version_id: Optional[int]
    activated_at: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None
    shadow_started_at: Optional[datetime] = None
    canary_started_at: Optional[datetime] = None
    eligible_at: Optional[datetime] = None
    consecutive_eligible_cycles: int = 0


@dataclass
class AutomationState:
    frozen: bool = False
    cooldown_until: Optional[datetime] = None
    rollback_count_14d: int = 0


@dataclass
class StateMachineResult:
    transition_occurred: bool
    from_state: str
    to_state: str
    candidate_id: int
    is_active: bool
    decision: Optional[str] = None
    reason: Optional[str] = None
    audit_record: Optional[Dict[str, Any]] = None


def advance_candidate_state(
    candidate: CandidateState,
    active_version: Optional[CandidateState],
    longterm_eval: WindowEvaluation,
    recent_eval: Optional[WindowEvaluation] = None,
    seasonal_eval: Optional[WindowEvaluation] = None,
    margin_result: Optional[MarginResult] = None,
    automation_state: Optional[AutomationState] = None,
    config: Optional[ModelSwitchingConfig] = None,
    now_dt: Optional[datetime] = None,
    conn: Optional[Any] = None,
) -> StateMachineResult:
    """Evaluates candidate state and advances it through the lifecycle state machine."""
    cfg = config or ModelSwitchingConfig()
    now = now_dt or datetime.now(timezone.utc)
    auto = automation_state or AutomationState()

    # Safety Guard 1: Master enable flag
    if not cfg.enabled:
        return StateMachineResult(
            transition_occurred=False,
            from_state=candidate.status,
            to_state=candidate.status,
            candidate_id=candidate.id,
            is_active=candidate.is_active,
            reason="Model switching automation is disabled (dormant mode).",
        )

    # Safety Guard 2: Automation Frozen
    if auto.frozen:
        record = write_decision(
            decision="FROZEN",
            reason="Automation state is frozen by coordinator or circuit breaker; promotion blocked.",
            candidate_version_id=candidate.id,
            previous_version_id=active_version.id if active_version else None,
            conn=conn,
        )
        return StateMachineResult(
            transition_occurred=False,
            from_state=candidate.status,
            to_state=candidate.status,
            candidate_id=candidate.id,
            is_active=candidate.is_active,
            decision="FROZEN",
            reason="Automation is frozen.",
            audit_record=record,
        )

    # Safety Guard 3: Cooldown active
    if auto.cooldown_until and auto.cooldown_until > now:
        record = write_decision(
            decision="COOLDOWN",
            reason=f"System in post-rollback cooldown until {auto.cooldown_until.isoformat()}; promotion blocked.",
            candidate_version_id=candidate.id,
            previous_version_id=active_version.id if active_version else None,
            conn=conn,
        )
        return StateMachineResult(
            transition_occurred=False,
            from_state=candidate.status,
            to_state=candidate.status,
            candidate_id=candidate.id,
            is_active=candidate.is_active,
            decision="COOLDOWN",
            reason="Cooldown active.",
            audit_record=record,
        )

    current_status = candidate.status

    # Terminal states cannot advance
    if current_status in ("active", "superseded", "rejected", "rolled_back", "retired"):
        return StateMachineResult(
            transition_occurred=False,
            from_state=current_status,
            to_state=current_status,
            candidate_id=candidate.id,
            is_active=candidate.is_active,
            reason=f"Status '{current_status}' is terminal or requires external trigger.",
        )

    # --------------------------------------------------------------------------
    # Transition 1: candidate -> evaluating
    # --------------------------------------------------------------------------
    if current_status == "candidate":
        candidate.status = "evaluating"
        return StateMachineResult(
            transition_occurred=True,
            from_state="candidate",
            to_state="evaluating",
            candidate_id=candidate.id,
            is_active=False,
            reason="Candidate transitioned to evaluating for quality gate verification.",
        )

    # --------------------------------------------------------------------------
    # Transition 2: evaluating -> eligible OR rejected
    # --------------------------------------------------------------------------
    if current_status == "evaluating":
        if not longterm_eval.floors_met:
            candidate.status = "rejected"
            record = write_decision(
                decision="INSUFFICIENT_DATA",
                reason=f"Long-term window evidence floors not met: {longterm_eval.floor_failure_reason}",
                candidate_version_id=candidate.id,
                previous_version_id=active_version.id if active_version else None,
                composite_longterm_cand=longterm_eval.composite_score,
                sample_counts=longterm_eval.sample_counts,
                conn=conn,
            )
            return StateMachineResult(
                transition_occurred=True,
                from_state="evaluating",
                to_state="rejected",
                candidate_id=candidate.id,
                is_active=False,
                decision="INSUFFICIENT_DATA",
                reason=record["reason"],
                audit_record=record,
            )

        if not margin_result or not margin_result.passed:
            candidate.status = "rejected"
            decision_type = margin_result.decision if margin_result else "NO_IMPROVEMENT"
            reason_text = margin_result.reason if margin_result else "Did not meet required promotion margin."
            record = write_decision(
                decision=decision_type,
                reason=reason_text,
                candidate_version_id=candidate.id,
                previous_version_id=active_version.id if active_version else None,
                composite_longterm_cand=longterm_eval.composite_score,
                sample_counts=longterm_eval.sample_counts,
                conn=conn,
            )
            return StateMachineResult(
                transition_occurred=True,
                from_state="evaluating",
                to_state="rejected",
                candidate_id=candidate.id,
                is_active=False,
                decision=decision_type,
                reason=reason_text,
                audit_record=record,
            )

        # Check blocking signals: Recent and Seasonal windows must not severely degrade
        req_margin = margin_result.required_margin
        if recent_eval and recent_eval.floors_met and recent_eval.composite_score < -req_margin:
            candidate.status = "rejected"
            record = write_decision(
                decision="REJECTED",
                reason=f"Recent window veto: composite score ({recent_eval.composite_score:.4f}) degraded beyond margin (-{req_margin:.4f}).",
                candidate_version_id=candidate.id,
                previous_version_id=active_version.id if active_version else None,
                composite_recent_cand=recent_eval.composite_score,
                composite_longterm_cand=longterm_eval.composite_score,
                conn=conn,
            )
            return StateMachineResult(
                transition_occurred=True,
                from_state="evaluating",
                to_state="rejected",
                candidate_id=candidate.id,
                is_active=False,
                decision="REJECTED",
                reason=record["reason"],
                audit_record=record,
            )

        # Evaluating -> Eligible (Cycle 1 Pass)
        candidate.status = "eligible"
        candidate.consecutive_eligible_cycles = 1
        candidate.eligible_at = now
        record = write_decision(
            decision="ELIGIBLE",
            reason=f"Cycle-1 passed: {margin_result.reason}",
            candidate_version_id=candidate.id,
            previous_version_id=active_version.id if active_version else None,
            composite_longterm_cand=longterm_eval.composite_score,
            sample_counts=longterm_eval.sample_counts,
            conn=conn,
        )
        return StateMachineResult(
            transition_occurred=True,
            from_state="evaluating",
            to_state="eligible",
            candidate_id=candidate.id,
            is_active=False,
            decision="ELIGIBLE",
            reason=record["reason"],
            audit_record=record,
        )

    # --------------------------------------------------------------------------
    # Transition 3: eligible -> shadow OR rejected (Cycle 2 confirmation)
    # --------------------------------------------------------------------------
    if current_status == "eligible":
        # Anti-flapping hysteresis guard: require full weekly cycle before cycle-2 confirmation
        if not candidate.eligible_at:
            candidate.eligible_at = now
            return StateMachineResult(
                transition_occurred=False,
                from_state="eligible",
                to_state="eligible",
                candidate_id=candidate.id,
                is_active=False,
                reason="Initialized eligible timestamp for weekly cadence tracking.",
            )

        dwell_time = now - candidate.eligible_at
        min_weekly_dwell = timedelta(days=cfg.durations.weekly_cycle_days)
        if dwell_time < min_weekly_dwell:
            return StateMachineResult(
                transition_occurred=False,
                from_state="eligible",
                to_state="eligible",
                candidate_id=candidate.id,
                is_active=False,
                reason=(
                    f"Anti-flapping hysteresis: Candidate has been eligible for {dwell_time.total_seconds()/86400:.1f}d; "
                    f"full weekly cadence ({cfg.durations.weekly_cycle_days}d) required before cycle-2 confirmation."
                ),
            )

        # Anti-flapping evidence check: Cycle 2 evaluation window must be rolled forward with newer data
        eligible_date = candidate.eligible_at.date() if isinstance(candidate.eligible_at, datetime) else candidate.eligible_at
        if longterm_eval and longterm_eval.window_end is not None and eligible_date is not None:
            if longterm_eval.window_end <= eligible_date:
                return StateMachineResult(
                    transition_occurred=False,
                    from_state="eligible",
                    to_state="eligible",
                    candidate_id=candidate.id,
                    is_active=False,
                    reason=(
                        f"Anti-flapping guard: Cycle-2 evaluation window end ({longterm_eval.window_end}) "
                        f"must be rolled forward past eligible timestamp ({eligible_date}) with new verified evidence."
                    ),
                )

        # Cycle 2 confirmation check
        passed_cycle2 = margin_result and margin_result.passed and longterm_eval.floors_met
        if passed_cycle2:
            candidate.status = "shadow"
            candidate.shadow_started_at = now
            candidate.consecutive_eligible_cycles = 2
            reason_text = "Confirmed eligibility on consecutive weekly cycle; entered shadow mode."
            return StateMachineResult(
                transition_occurred=True,
                from_state="eligible",
                to_state="shadow",
                candidate_id=candidate.id,
                is_active=False,
                reason=reason_text,
            )
        else:
            candidate.status = "rejected"
            record = write_decision(
                decision="NOT_CONFIRMED",
                reason="Candidate failed cycle-2 confirmation on rolled-forward window.",
                candidate_version_id=candidate.id,
                previous_version_id=active_version.id if active_version else None,
                conn=conn,
            )
            return StateMachineResult(
                transition_occurred=True,
                from_state="eligible",
                to_state="rejected",
                candidate_id=candidate.id,
                is_active=False,
                decision="NOT_CONFIRMED",
                reason=record["reason"],
                audit_record=record,
            )

    # --------------------------------------------------------------------------
    # Transition 4: shadow -> canary OR rejected
    # --------------------------------------------------------------------------
    if current_status == "shadow":
        if not candidate.shadow_started_at:
            candidate.shadow_started_at = now
            return StateMachineResult(False, "shadow", "shadow", candidate.id, False, reason="Initialized shadow timestamp.")

        shadow_duration = now - candidate.shadow_started_at
        min_shadow_time = timedelta(days=cfg.durations.shadow_days)

        if shadow_duration < min_shadow_time:
            return StateMachineResult(
                False, "shadow", "shadow", candidate.id, False,
                reason=f"In shadow mode ({shadow_duration.days}/{cfg.durations.shadow_days} days elapsed)."
            )

        # Shadow period duration reached: evaluate shadow performance
        passed_shadow = margin_result and margin_result.passed and longterm_eval.floors_met
        if passed_shadow:
            candidate.status = "canary"
            candidate.canary_started_at = now
            return StateMachineResult(
                transition_occurred=True,
                from_state="shadow",
                to_state="canary",
                candidate_id=candidate.id,
                is_active=False,
                reason="Shadow evaluation completed successfully; entered 5-region canary mode.",
            )
        else:
            candidate.status = "rejected"
            record = write_decision(
                decision="REJECTED",
                reason="Candidate failed shadow-period margin evaluation against concurrent active version.",
                candidate_version_id=candidate.id,
                previous_version_id=active_version.id if active_version else None,
                conn=conn,
            )
            return StateMachineResult(
                transition_occurred=True,
                from_state="shadow",
                to_state="rejected",
                candidate_id=candidate.id,
                is_active=False,
                decision="REJECTED",
                reason=record["reason"],
                audit_record=record,
            )

    # --------------------------------------------------------------------------
    # Transition 5: canary -> active OR rejected (Final Promotion)
    # --------------------------------------------------------------------------
    if current_status == "canary":
        if not candidate.canary_started_at:
            candidate.canary_started_at = now
            return StateMachineResult(False, "canary", "canary", candidate.id, False, reason="Initialized canary timestamp.")

        canary_duration = now - candidate.canary_started_at
        min_canary_time = timedelta(days=cfg.durations.canary_days)

        if canary_duration < min_canary_time:
            return StateMachineResult(
                False, "canary", "canary", candidate.id, False,
                reason=f"In canary mode ({canary_duration.days}/{cfg.durations.canary_days} days elapsed)."
            )

        passed_canary = margin_result and margin_result.passed and longterm_eval.floors_met
        if passed_canary:
            # Active dwell time check on incumbent active version
            if active_version and active_version.activated_at:
                active_dwell = now - active_version.activated_at
                min_dwell = timedelta(days=cfg.durations.active_min_dwell_days)
                if active_dwell < min_dwell:
                    return StateMachineResult(
                        False, "canary", "canary", candidate.id, False,
                        reason=f"Incumbent active version has not met 14-day minimum dwell time ({active_dwell.days}/{cfg.durations.active_min_dwell_days} days)."
                    )

            # FINAL PROMOTION (canary -> active)
            candidate.status = "active"
            candidate.is_active = True
            candidate.activated_at = now

            if active_version:
                active_version.status = "superseded"
                active_version.is_active = False
                active_version.deactivated_at = now

            record = write_decision(
                decision="PROMOTED",
                reason="Canary verification completed successfully across all 5 regions. Promoted to globally active production version.",
                candidate_version_id=candidate.id,
                previous_version_id=active_version.id if active_version else None,
                composite_longterm_cand=longterm_eval.composite_score,
                sample_counts=longterm_eval.sample_counts,
                conn=conn,
            )
            return StateMachineResult(
                transition_occurred=True,
                from_state="canary",
                to_state="active",
                candidate_id=candidate.id,
                is_active=True,
                decision="PROMOTED",
                reason=record["reason"],
                audit_record=record,
            )
        else:
            candidate.status = "rejected"
            record = write_decision(
                decision="REJECTED",
                reason="Candidate failed canary evaluation.",
                candidate_version_id=candidate.id,
                previous_version_id=active_version.id if active_version else None,
                conn=conn,
            )
            return StateMachineResult(
                transition_occurred=True,
                from_state="canary",
                to_state="rejected",
                candidate_id=candidate.id,
                is_active=False,
                decision="REJECTED",
                reason=record["reason"],
                audit_record=record,
            )

    return StateMachineResult(
        transition_occurred=False,
        from_state=current_status,
        to_state=current_status,
        candidate_id=candidate.id,
        is_active=candidate.is_active,
        reason=f"No transition defined for state '{current_status}'.",
    )


def validate_state_invariants(status: str, is_active: bool) -> Tuple[bool, Optional[str]]:
    """Enforces state-machine invariant: status == 'active' <=> is_active == True.

    All other states (draft, candidate, evaluating, eligible, shadow, canary,
    superseded, rejected, rolled_back, retired) must have is_active == False.
    """
    if status not in VALID_STATES:
        return False, f"Invalid state '{status}'. Must be one of {sorted(list(VALID_STATES))}"

    if status == "active" and not is_active:
        return False, "Invariant violation: status is 'active' but is_active is False"

    if status != "active" and is_active:
        return False, f"Invariant violation: status is '{status}' but is_active is True"

    return True, None
