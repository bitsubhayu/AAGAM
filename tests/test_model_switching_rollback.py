"""Unit tests for automatic rollback triggers, cooldowns, and circuit breakers.

Authoritative source: AAGAM_MODEL_VERSIONING_DESIGN.md §O, §P
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pipeline.versioning.config import RollbackConfig
from pipeline.versioning.rollback import (
    check_bias_explosion_trigger,
    check_coverage_degraded_trigger,
    check_csi_collapse_trigger,
    check_mae_degradation_trigger,
    check_pipeline_failure_trigger,
    evaluate_rollback_triggers,
)


class TestRollbackTriggers:
    """Tests operational failure triggers and negative guardrails."""

    def test_sudden_mae_degradation_triggers_rollback(self):
        """MAE degrading by > 25% with >= 20 samples fires rollback."""
        cfg = RollbackConfig(mae_degradation_pct=0.25, min_samples_mae_trigger=20)
        # Baseline = 2.0, Current = 2.6 (+30% degradation), N = 25
        res = check_mae_degradation_trigger(current_mae=2.6, baseline_mae=2.0, sample_count=25, config=cfg)
        assert res.triggered is True
        assert res.trigger_name == "sudden_mae_degradation"
        assert "degraded by 30.0%" in res.reason

    def test_negative_case_insufficient_samples_mae(self):
        """Case 10a: Single bad day (insufficient samples < 20) does NOT fire MAE rollback."""
        cfg = RollbackConfig(mae_degradation_pct=0.25, min_samples_mae_trigger=20)
        # 100% degradation but only 5 samples
        res = check_mae_degradation_trigger(current_mae=4.0, baseline_mae=2.0, sample_count=5, config=cfg)
        assert res.triggered is False
        assert "Insufficient samples (5 < 20)" in res.reason

    def test_bias_explosion_trigger(self):
        """Absolute bias > 3.0x baseline with >= 20 samples fires rollback."""
        cfg = RollbackConfig(bias_explosion_factor=3.0, min_samples_bias_trigger=20)
        # Baseline = 0.10, Current = 0.35 (3.5x), N = 25
        res = check_bias_explosion_trigger(current_bias=0.35, baseline_bias=0.10, sample_count=25, config=cfg)
        assert res.triggered is True
        assert res.trigger_name == "bias_explosion"
        assert "3.5x baseline" in res.reason

        # Negative case: 2.0x baseline does NOT fire
        res_neg = check_bias_explosion_trigger(current_bias=0.20, baseline_bias=0.10, sample_count=25, config=cfg)
        assert res_neg.triggered is False

    def test_csi_collapse_trigger(self):
        """Rain CSI dropping > 0.15 with >= 3 events fires rollback."""
        cfg = RollbackConfig(csi_drop_absolute=0.15, min_events_csi_trigger=3)
        # Baseline = 0.70, Current = 0.50 (drop = 0.20), Events = 4
        res = check_csi_collapse_trigger(current_csi=0.50, baseline_csi=0.70, event_count=4, config=cfg)
        assert res.triggered is True
        assert res.trigger_name == "csi_collapse"
        assert "dropped by 0.2000 absolute" in res.reason

    def test_negative_case_single_missed_event_csi(self):
        """Case 10b: Single missed event (< 3 events) does NOT fire CSI rollback."""
        cfg = RollbackConfig(csi_drop_absolute=0.15, min_events_csi_trigger=3)
        # Big drop from 0.80 to 0.20, but only 1 event in window
        res = check_csi_collapse_trigger(current_csi=0.20, baseline_csi=0.80, event_count=1, config=cfg)
        assert res.triggered is False
        assert "Insufficient extreme events (1 < 3)" in res.reason

    def test_pipeline_failure_trigger(self):
        """3 consecutive cycle failures fires rollback; 2 does not."""
        cfg = RollbackConfig(pipeline_consecutive_failures=3)
        assert check_pipeline_failure_trigger(3, cfg).triggered is True
        assert check_pipeline_failure_trigger(4, cfg).triggered is True
        assert check_pipeline_failure_trigger(2, cfg).triggered is False

    def test_coverage_degraded_trigger(self):
        """> 50% degraded locations for 2 consecutive cycles fires rollback."""
        cfg = RollbackConfig(coverage_degraded_threshold=0.50, coverage_consecutive_cycles=2)
        # 60% degraded for 2 cycles => fired
        assert check_coverage_degraded_trigger(2, 0.60, cfg).triggered is True
        # 60% degraded for 1 cycle => NOT fired (could be temporary glitch)
        assert check_coverage_degraded_trigger(1, 0.60, cfg).triggered is False
        # 40% degraded for 2 cycles => NOT fired
        assert check_coverage_degraded_trigger(2, 0.40, cfg).triggered is False

    def test_cooldown_duration_and_target_selection(self):
        """Case 11: Rollback selects parent_version_id and initiates 7-day cooldown."""
        t_now = datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc)
        curr = {"mae": 3.0, "n": 30}
        base = {"mae": 2.0}

        res = evaluate_rollback_triggers(
            metrics_current=curr,
            metrics_baseline=base,
            parent_version_id=2,  # Must revert to parent
            recent_rollback_count_14d=0,
            now_dt=t_now,
        )
        assert res.should_rollback is True
        assert res.target_version_id == 2
        assert res.circuit_breaker_triggered is False
        assert res.cooldown_until == t_now + timedelta(days=7)

    def test_circuit_breaker_freezes_automation(self):
        """Case 12: 2 rollbacks within 14 days triggers the circuit breaker."""
        t_now = datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc)
        curr = {"mae": 3.0, "n": 30}
        base = {"mae": 2.0}

        # First rollback was already recorded in past 14 days; this is the second rollback
        res = evaluate_rollback_triggers(
            metrics_current=curr,
            metrics_baseline=base,
            parent_version_id=2,
            recent_rollback_count_14d=1,  # New count will be 2
            now_dt=t_now,
        )
        assert res.should_rollback is True
        assert res.circuit_breaker_triggered is True

    def test_evaluate_rollback_triggers_bias_explosion(self):
        """evaluate_rollback_triggers fires when bias explodes."""
        curr = {"mae": 2.0, "bias": 0.40, "n": 25}
        base = {"mae": 2.0, "bias": 0.10}
        res = evaluate_rollback_triggers(curr, base, parent_version_id=2)
        assert res.should_rollback is True
        assert res.trigger_name == "bias_explosion"

    def test_evaluate_rollback_triggers_csi_collapse(self):
        """evaluate_rollback_triggers fires when CSI collapses."""
        curr = {"mae": 2.0, "bias": 0.10, "csi": 0.45, "csi_events": 5, "n": 25}
        base = {"mae": 2.0, "bias": 0.10, "csi": 0.65}
        res = evaluate_rollback_triggers(curr, base, parent_version_id=2)
        assert res.should_rollback is True
        assert res.trigger_name == "csi_collapse"

    def test_evaluate_rollback_triggers_pipeline_failures(self):
        """evaluate_rollback_triggers fires when consecutive pipeline failures >= 3."""
        curr = {"mae": 2.0, "n": 25}
        base = {"mae": 2.0}
        res = evaluate_rollback_triggers(curr, base, parent_version_id=2, consecutive_pipeline_failures=3)
        assert res.should_rollback is True
        assert res.trigger_name == "pipeline_error_rate"

    def test_evaluate_rollback_triggers_coverage_degraded(self):
        """evaluate_rollback_triggers fires when coverage degraded for 2 consecutive cycles."""
        curr = {"mae": 2.0, "n": 25}
        base = {"mae": 2.0}
        res = evaluate_rollback_triggers(
            curr,
            base,
            parent_version_id=2,
            consecutive_degraded_cycles=2,
            degraded_location_fraction=0.60,
        )
        assert res.should_rollback is True
        assert res.trigger_name == "missing_forecast_coverage"

    def test_check_mae_zero_baseline(self):
        """Zero baseline MAE does not trigger rollback."""
        res = check_mae_degradation_trigger(current_mae=2.0, baseline_mae=0.0, sample_count=30)
        assert res.triggered is False

    def test_check_bias_insufficient_samples(self):
        """Insufficient samples for bias trigger returns triggered=False."""
        res = check_bias_explosion_trigger(current_bias=0.5, baseline_bias=0.1, sample_count=10)
        assert res.triggered is False
        assert "Insufficient samples" in res.reason

    def test_evaluate_rollback_triggers_no_triggers_fired(self):
        """Healthy operational metrics result in should_rollback=False."""
        curr = {"mae": 2.0, "bias": 0.05, "csi": 0.70, "n": 30, "csi_events": 5}
        base = {"mae": 2.0, "bias": 0.05, "csi": 0.70}
        res = evaluate_rollback_triggers(curr, base, parent_version_id=2)
        assert res.should_rollback is False
        assert res.trigger_name is None
        assert res.target_version_id is None


