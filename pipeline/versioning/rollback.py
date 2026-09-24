"""Rollback trigger evaluation, cooldowns, and circuit breakers (Design Doc §O).

Monitors active and canary versions for operational degradation:
1. Sudden MAE degradation: trailing-3-day MAE worse by > 25% vs baseline (min 20 samples)
2. Bias explosion: abs(bias) > 3.0 * abs(baseline_bias) (min 20 samples)
3. CSI collapse: CSI drops by > 0.15 absolute vs baseline (min 3 real events)
4. Pipeline error rate: 3 consecutive failed cycles (18h)
5. Missing coverage: > 50% locations degraded for 2 consecutive cycles

Rollback target is strictly parent_version_id (or nearest un-rolled-back ancestor).
Circuit breaker: 2 rollbacks within rolling 14 days freezes automation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from pipeline.versioning.config import RollbackConfig

logger = logging.getLogger("aagam.pipeline.versioning.rollback")


@dataclass
class RollbackTriggerEvaluation:
    triggered: bool
    trigger_name: Optional[str] = None
    metric_value: Optional[float] = None
    baseline_value: Optional[float] = None
    threshold: Optional[float] = None
    sample_count: int = 0
    reason: Optional[str] = None


@dataclass
class RollbackResult:
    should_rollback: bool
    target_version_id: Optional[int]
    trigger_name: Optional[str]
    reason: Optional[str]
    circuit_breaker_triggered: bool = False
    cooldown_until: Optional[datetime] = None


def check_mae_degradation_trigger(
    current_mae: float,
    baseline_mae: float,
    sample_count: int,
    config: Optional[RollbackConfig] = None,
) -> RollbackTriggerEvaluation:
    """Checks if trailing-3-day MAE degraded by more than configured threshold (> 25%)."""
    cfg = config or RollbackConfig()
    if sample_count < cfg.min_samples_mae_trigger:
        return RollbackTriggerEvaluation(
            triggered=False,
            sample_count=sample_count,
            reason=f"Insufficient samples ({sample_count} < {cfg.min_samples_mae_trigger}) for MAE trigger",
        )

    if baseline_mae <= 0:
        return RollbackTriggerEvaluation(triggered=False, sample_count=sample_count)

    degradation = (current_mae - baseline_mae) / baseline_mae
    triggered = degradation > cfg.mae_degradation_pct

    return RollbackTriggerEvaluation(
        triggered=triggered,
        trigger_name="sudden_mae_degradation" if triggered else None,
        metric_value=current_mae,
        baseline_value=baseline_mae,
        threshold=cfg.mae_degradation_pct,
        sample_count=sample_count,
        reason=(
            f"Trailing MAE ({current_mae:.4f}) degraded by {degradation*100:.1f}% vs baseline "
            f"({baseline_mae:.4f}), exceeding threshold ({cfg.mae_degradation_pct*100:.1f}%)"
            if triggered else None
        ),
    )


def check_bias_explosion_trigger(
    current_bias: float,
    baseline_bias: float,
    sample_count: int,
    config: Optional[RollbackConfig] = None,
    epsilon: float = 0.05,
) -> RollbackTriggerEvaluation:
    """Checks if absolute bias tripled versus baseline (min 20 samples)."""
    cfg = config or RollbackConfig()
    if sample_count < cfg.min_samples_bias_trigger:
        return RollbackTriggerEvaluation(
            triggered=False,
            sample_count=sample_count,
            reason=f"Insufficient samples ({sample_count} < {cfg.min_samples_bias_trigger}) for bias trigger",
        )

    base_mag = max(abs(baseline_bias), epsilon)
    curr_mag = abs(current_bias)
    ratio = curr_mag / base_mag
    triggered = ratio > cfg.bias_explosion_factor

    return RollbackTriggerEvaluation(
        triggered=triggered,
        trigger_name="bias_explosion" if triggered else None,
        metric_value=current_bias,
        baseline_value=baseline_bias,
        threshold=cfg.bias_explosion_factor,
        sample_count=sample_count,
        reason=(
            f"Absolute bias ({curr_mag:.4f}) is {ratio:.1f}x baseline ({base_mag:.4f}), "
            f"exceeding explosion factor ({cfg.bias_explosion_factor}x)"
            if triggered else None
        ),
    )


def check_csi_collapse_trigger(
    current_csi: float,
    baseline_csi: float,
    event_count: int,
    config: Optional[RollbackConfig] = None,
) -> RollbackTriggerEvaluation:
    """Checks if rain CSI dropped by more than 0.15 absolute with at least 3 events."""
    cfg = config or RollbackConfig()
    if event_count < cfg.min_events_csi_trigger:
        return RollbackTriggerEvaluation(
            triggered=False,
            sample_count=event_count,
            reason=f"Insufficient extreme events ({event_count} < {cfg.min_events_csi_trigger}) for CSI trigger",
        )

    drop = baseline_csi - current_csi
    triggered = drop > cfg.csi_drop_absolute

    return RollbackTriggerEvaluation(
        triggered=triggered,
        trigger_name="csi_collapse" if triggered else None,
        metric_value=current_csi,
        baseline_value=baseline_csi,
        threshold=cfg.csi_drop_absolute,
        sample_count=event_count,
        reason=(
            f"Rain CSI ({current_csi:.4f}) dropped by {drop:.4f} absolute vs baseline "
            f"({baseline_csi:.4f}), exceeding threshold ({cfg.csi_drop_absolute:.4f})"
            if triggered else None
        ),
    )


def check_pipeline_failure_trigger(
    consecutive_failures: int,
    config: Optional[RollbackConfig] = None,
) -> RollbackTriggerEvaluation:
    """Checks if pipeline had 3 consecutive failed cycles (18h)."""
    cfg = config or RollbackConfig()
    triggered = consecutive_failures >= cfg.pipeline_consecutive_failures
    return RollbackTriggerEvaluation(
        triggered=triggered,
        trigger_name="pipeline_error_rate" if triggered else None,
        metric_value=float(consecutive_failures),
        threshold=float(cfg.pipeline_consecutive_failures),
        reason=(
            f"Pipeline blend raised errors for {consecutive_failures} consecutive cycles (>= {cfg.pipeline_consecutive_failures})"
            if triggered else None
        ),
    )


def check_coverage_degraded_trigger(
    consecutive_degraded_cycles: int,
    degraded_fraction: float,
    config: Optional[RollbackConfig] = None,
) -> RollbackTriggerEvaluation:
    """Checks if > 50% locations degraded for 2 consecutive cycles."""
    cfg = config or RollbackConfig()
    triggered = (
        consecutive_degraded_cycles >= cfg.coverage_consecutive_cycles
        and degraded_fraction > cfg.coverage_degraded_threshold
    )
    return RollbackTriggerEvaluation(
        triggered=triggered,
        trigger_name="missing_forecast_coverage" if triggered else None,
        metric_value=degraded_fraction,
        threshold=cfg.coverage_degraded_threshold,
        reason=(
            f"Degraded forecast coverage ({degraded_fraction*100:.1f}%) for {consecutive_degraded_cycles} cycles "
            f"(threshold: >{cfg.coverage_degraded_threshold*100:.0f}% for {cfg.coverage_consecutive_cycles} cycles)"
            if triggered else None
        ),
    )


def evaluate_rollback_triggers(
    metrics_current: Dict[str, Any],
    metrics_baseline: Dict[str, Any],
    parent_version_id: Optional[int],
    recent_rollback_count_14d: int = 0,
    consecutive_pipeline_failures: int = 0,
    consecutive_degraded_cycles: int = 0,
    degraded_location_fraction: float = 0.0,
    config: Optional[RollbackConfig] = None,
    now_dt: Optional[datetime] = None,
) -> RollbackResult:
    """Evaluates all rollback triggers and determines if rollback / circuit breaker must execute."""
    cfg = config or RollbackConfig()
    current_time = now_dt or datetime.now(timezone.utc)

    # 1. Check MAE Degradation
    mae_eval = check_mae_degradation_trigger(
        current_mae=metrics_current.get("mae", 0.0),
        baseline_mae=metrics_baseline.get("mae", 0.0),
        sample_count=metrics_current.get("n", 0),
        config=cfg,
    )
    if mae_eval.triggered:
        return _build_rollback_result(mae_eval, parent_version_id, recent_rollback_count_14d, cfg, current_time)

    # 2. Check Bias Explosion
    bias_eval = check_bias_explosion_trigger(
        current_bias=metrics_current.get("bias", 0.0),
        baseline_bias=metrics_baseline.get("bias", 0.0),
        sample_count=metrics_current.get("n", 0),
        config=cfg,
    )
    if bias_eval.triggered:
        return _build_rollback_result(bias_eval, parent_version_id, recent_rollback_count_14d, cfg, current_time)

    # 3. Check CSI Collapse
    csi_eval = check_csi_collapse_trigger(
        current_csi=metrics_current.get("csi", 0.0),
        baseline_csi=metrics_baseline.get("csi", 0.0),
        event_count=metrics_current.get("csi_events", 0),
        config=cfg,
    )
    if csi_eval.triggered:
        return _build_rollback_result(csi_eval, parent_version_id, recent_rollback_count_14d, cfg, current_time)

    # 4. Check Pipeline Failure Rate
    pipe_eval = check_pipeline_failure_trigger(consecutive_pipeline_failures, cfg)
    if pipe_eval.triggered:
        return _build_rollback_result(pipe_eval, parent_version_id, recent_rollback_count_14d, cfg, current_time)

    # 5. Check Coverage Degraded
    cov_eval = check_coverage_degraded_trigger(
        consecutive_degraded_cycles, degraded_location_fraction, cfg
    )
    if cov_eval.triggered:
        return _build_rollback_result(cov_eval, parent_version_id, recent_rollback_count_14d, cfg, current_time)

    # No triggers fired
    return RollbackResult(
        should_rollback=False,
        target_version_id=None,
        trigger_name=None,
        reason=None,
        circuit_breaker_triggered=False,
        cooldown_until=None,
    )


def _build_rollback_result(
    evaluation: RollbackTriggerEvaluation,
    parent_version_id: Optional[int],
    recent_rollback_count_14d: int,
    cfg: RollbackConfig,
    now: datetime,
) -> RollbackResult:
    new_count = recent_rollback_count_14d + 1
    circuit_breaker = new_count >= cfg.circuit_breaker_max_rollbacks
    cooldown = now + timedelta(days=cfg.cooldown_days)

    return RollbackResult(
        should_rollback=True,
        target_version_id=parent_version_id,
        trigger_name=evaluation.trigger_name,
        reason=evaluation.reason,
        circuit_breaker_triggered=circuit_breaker,
        cooldown_until=cooldown,
    )


def execute_rollback(
    conn: Any,
    from_version_id: int,
    to_version_id: int,
    trigger_name: str,
    reason: str,
    recent_rollback_count_14d: int = 0,
    pipeline_run_id: Optional[int] = None,
    now_dt: Optional[datetime] = None,
    config: Optional[RollbackConfig] = None,
    automation_state: Optional[Any] = None,
) -> Tuple[datetime, bool]:
    """Executes atomic rollback in the database and logs required audit decisions."""
    from pipeline.versioning.decisions import write_decision

    now = now_dt or datetime.now(timezone.utc)
    cfg = config or RollbackConfig()
    with conn.cursor() as cur:
        # Check target version exists
        cur.execute("SELECT id FROM model_versions WHERE id = %s;", (to_version_id,))
        if not cur.fetchone():
            raise ValueError(f"Target parent version {to_version_id} does not exist.")

        # Read current rollback count from database if available
        cur.execute("SELECT rollback_count_14d FROM model_switching_automation_state WHERE id = 1;")
        row = cur.fetchone()
        if row is not None and row[0] is not None:
            current_count = int(row[0])
        else:
            current_count = recent_rollback_count_14d

        new_count = current_count + 1
        cooldown = now + timedelta(days=cfg.cooldown_days)
        circuit_breaker = new_count >= cfg.circuit_breaker_max_rollbacks

        # Atomic deactivation of failing active version and activation of target version
        cur.execute(
            """
            UPDATE model_versions
            SET is_active = false, status = 'rolled_back', deactivated_at = %s
            WHERE id = %s;
            """,
            (now, from_version_id),
        )
        cur.execute(
            """
            UPDATE model_versions
            SET is_active = true, status = 'active', activated_at = %s
            WHERE id = %s;
            """,
            (now, to_version_id),
        )

        # Update automation state
        frozen_reason = (
            f"circuit breaker: {new_count} rollbacks within 14 days"
            if circuit_breaker
            else None
        )
        cur.execute(
            """
            UPDATE model_switching_automation_state
            SET rollback_count_14d = %s,
                cooldown_until = %s,
                frozen = CASE WHEN %s THEN true ELSE frozen END,
                frozen_reason = CASE WHEN %s THEN %s ELSE frozen_reason END,
                frozen_at = CASE WHEN %s THEN %s ELSE frozen_at END,
                updated_at = %s
            WHERE id = 1;
            """,
            (
                new_count,
                cooldown,
                circuit_breaker,
                circuit_breaker,
                frozen_reason,
                circuit_breaker,
                now,
                now,
            ),
        )

    # Write ROLLED_BACK audit decision
    write_decision(
        decision="ROLLED_BACK",
        reason=reason,
        candidate_version_id=to_version_id,
        previous_version_id=from_version_id,
        triggered_by=trigger_name,
        pipeline_run_id=pipeline_run_id,
        conn=conn,
    )

    if circuit_breaker:
        write_decision(
            decision="FROZEN",
            reason=frozen_reason,
            candidate_version_id=to_version_id,
            previous_version_id=from_version_id,
            pipeline_run_id=pipeline_run_id,
            conn=conn,
        )

    if automation_state is not None:
        automation_state.rollback_count_14d = new_count
        automation_state.cooldown_until = cooldown
        if circuit_breaker:
            automation_state.frozen = True

    logger.info(
        f"Executed rollback from {from_version_id} to {to_version_id} triggered by '{trigger_name}'. "
        f"Cooldown until {cooldown.isoformat()}, circuit_breaker={circuit_breaker}."
    )
    return cooldown, circuit_breaker


def evaluate_active_rollback_triggers(
    conn: Optional[Any],
    active_version: Dict[str, Any],
    recent_rollback_count_14d: int = 0,
    config: Optional[RollbackConfig] = None,
    now_dt: Optional[datetime] = None,
    pipeline_run_id: Optional[int] = None,
    override_metrics_current: Optional[Dict[str, Any]] = None,
    override_metrics_baseline: Optional[Dict[str, Any]] = None,
    consecutive_pipeline_failures: int = 0,
    consecutive_degraded_cycles: int = 0,
    degraded_location_fraction: float = 0.0,
    automation_state: Optional[Any] = None,
) -> RollbackResult:
    """Evaluates rollback triggers for the currently active version.

    If triggers fire and conn is provided, executes execute_rollback atomically.
    """
    cfg = config or RollbackConfig()
    now = now_dt or datetime.now(timezone.utc)
    parent_version_id = active_version.get("parent_version_id")

    if not parent_version_id:
        return RollbackResult(
            should_rollback=False,
            target_version_id=None,
            trigger_name=None,
            reason="Active version has no parent_version_id; rollback cannot target unrecorded ancestor.",
        )

    # Use overrides if provided
    metrics_curr = override_metrics_current or {}
    metrics_base = override_metrics_baseline or active_version.get("metrics") or {}

    # Query pipeline failure telemetry from pipeline_runs if connected and not overridden
    failures = consecutive_pipeline_failures
    if conn is not None and failures == 0:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status FROM pipeline_runs
                    WHERE job = 'ingest-blend'
                    ORDER BY started_at DESC LIMIT 5;
                    """
                )
                rows = cur.fetchall()
                for r in rows:
                    if r[0] == "FAILED":
                        failures += 1
                    else:
                        break
        except Exception as e:
            logger.warning(f"Could not read pipeline failure history: {e}")

    result = evaluate_rollback_triggers(
        metrics_current=metrics_curr,
        metrics_baseline=metrics_base,
        parent_version_id=parent_version_id,
        recent_rollback_count_14d=recent_rollback_count_14d,
        consecutive_pipeline_failures=failures,
        consecutive_degraded_cycles=consecutive_degraded_cycles,
        degraded_location_fraction=degraded_location_fraction,
        config=cfg,
        now_dt=now,
    )

    if result.should_rollback and conn is not None:
        execute_rollback(
            conn=conn,
            from_version_id=active_version["id"],
            to_version_id=parent_version_id,
            trigger_name=result.trigger_name or "unknown",
            reason=result.reason or "Active version degradation trigger fired",
            recent_rollback_count_14d=recent_rollback_count_14d,
            pipeline_run_id=pipeline_run_id,
            now_dt=now,
            config=cfg,
            automation_state=automation_state,
        )

    return result


def evaluate_canary_rollback_triggers(
    conn: Optional[Any],
    canary_version: Dict[str, Any],
    active_version: Dict[str, Any],
    config: Optional[RollbackConfig] = None,
    now_dt: Optional[datetime] = None,
    pipeline_run_id: Optional[int] = None,
    override_metrics_current: Optional[Dict[str, Any]] = None,
    override_metrics_baseline: Optional[Dict[str, Any]] = None,
    consecutive_pipeline_failures: int = 0,
    consecutive_degraded_cycles: int = 0,
    degraded_location_fraction: float = 0.0,
) -> RollbackResult:
    """Evaluates rollback triggers for a candidate version currently in canary mode.

    If triggers fire:
    - Reverts canary assignments (releases assigned locations back to active).
    - Sets canary status to 'rejected'.
    - Writes ROLLED_BACK audit decision.
    """
    from pipeline.versioning.canary import release_canary_assignments
    from pipeline.versioning.decisions import write_decision

    cfg = config or RollbackConfig()
    now = now_dt or datetime.now(timezone.utc)

    metrics_curr = override_metrics_current or {}
    metrics_base = override_metrics_baseline or active_version.get("metrics") or {}

    result = evaluate_rollback_triggers(
        metrics_current=metrics_curr,
        metrics_baseline=metrics_base,
        parent_version_id=active_version["id"],
        recent_rollback_count_14d=0,
        consecutive_pipeline_failures=consecutive_pipeline_failures,
        consecutive_degraded_cycles=consecutive_degraded_cycles,
        degraded_location_fraction=degraded_location_fraction,
        config=cfg,
        now_dt=now,
    )

    if result.should_rollback and conn is not None:
        # Release canary assignments
        release_canary_assignments(conn, canary_version["id"], now)

        # Set canary status to rejected
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE model_versions
                SET status = 'rejected', deactivated_at = %s
                WHERE id = %s;
                """,
                (now, canary_version["id"]),
            )

        write_decision(
            decision="ROLLED_BACK",
            reason=f"Canary rollback: {result.reason}",
            candidate_version_id=canary_version["id"],
            previous_version_id=active_version["id"],
            triggered_by=result.trigger_name,
            pipeline_run_id=pipeline_run_id,
            conn=conn,
        )

        logger.info(
            f"Canary version {canary_version['id']} rolled back and rejected due to {result.trigger_name}."
        )

    return result
