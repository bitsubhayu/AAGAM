"""Unit tests for model switching configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

from pipeline.versioning.config import (
    ModelSwitchingConfig,
    load_model_switching_config,
)


class TestModelSwitchingConfig:
    """Tests loading config/model_switching.yaml."""

    def test_load_default_config_file(self):
        """Verifies loading the actual repository config/model_switching.yaml."""
        cfg = load_model_switching_config(Path("config/model_switching.yaml"))
        assert cfg.enabled is False  # DORMANT by default
        assert cfg.weights.w_mae == 0.40
        assert cfg.weights.w_rmse == 0.30
        assert cfg.weights.w_bias == 0.15
        assert cfg.weights.w_csi == 0.15

        assert cfg.margin.base_margin == 0.02
        assert cfg.margin.target_sample_volume == 1000
        assert cfg.margin.min_total_sample_floor == 150
        assert cfg.margin.regional_non_regression_limit == -0.01

        assert cfg.floors.min_samples_per_stratum == 30
        assert cfg.floors.min_strata == 5
        assert cfg.floors.min_regions_represented == 5
        assert cfg.floors.min_lead_days == 4
        assert cfg.floors.min_csi_events == 10

        assert cfg.regions == ["EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"]
        assert cfg.durations.shadow_days == 7
        assert cfg.durations.canary_days == 14
        assert cfg.durations.active_min_dwell_days == 14
        assert cfg.durations.consecutive_cycles_required == 2

        assert cfg.rollback.mae_degradation_pct == 0.25
        assert cfg.rollback.bias_explosion_factor == 3.0
        assert cfg.rollback.csi_drop_absolute == 0.15
        assert cfg.rollback.pipeline_consecutive_failures == 3
        assert cfg.rollback.coverage_degraded_threshold == 0.50
        assert cfg.rollback.coverage_consecutive_cycles == 2
        assert cfg.rollback.cooldown_days == 7
        assert cfg.rollback.circuit_breaker_window_days == 14
        assert cfg.rollback.circuit_breaker_max_rollbacks == 2

    def test_nonexistent_config_returns_defaults(self, tmp_path):
        """Non-existent config path falls back gracefully to default values."""
        non_existent = tmp_path / "missing.yaml"
        cfg = load_model_switching_config(non_existent)
        assert cfg.enabled is False
        assert cfg.margin.base_margin == 0.02

    def test_malformed_config_falls_back(self, tmp_path):
        """Malformed YAML file falls back gracefully."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("weights: [invalid yaml syntax", encoding="utf-8")
        cfg = load_model_switching_config(bad_file)
        assert isinstance(cfg, ModelSwitchingConfig)
        assert cfg.enabled is False
