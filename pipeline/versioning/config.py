"""Configuration loader and schema for model switching and versioning."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger("aagam.pipeline.versioning.config")

DEFAULT_CONFIG_PATH = Path("config/model_switching.yaml")


@dataclass
class ScoringWeights:
    w_mae: float = 0.40
    w_rmse: float = 0.30
    w_bias: float = 0.15
    w_csi: float = 0.15


@dataclass
class MarginConfig:
    base_margin: float = 0.02
    target_sample_volume: int = 1000
    min_total_sample_floor: int = 150
    regional_non_regression_limit: float = -0.01


@dataclass
class FloorsConfig:
    min_samples_per_stratum: int = 30
    min_strata: int = 5
    min_regions_represented: int = 5
    min_lead_days: int = 4
    min_csi_events: int = 10


@dataclass
class WindowsConfig:
    recent_days: int = 14
    seasonal_days: int = 90
    longterm_max_days: int = 180


@dataclass
class DurationsConfig:
    weekly_cycle_days: int = 7
    shadow_days: int = 7
    canary_days: int = 14
    active_min_dwell_days: int = 14
    consecutive_cycles_required: int = 2


@dataclass
class RollbackConfig:
    mae_degradation_pct: float = 0.25
    min_samples_mae_trigger: int = 20
    bias_explosion_factor: float = 3.0
    min_samples_bias_trigger: int = 20
    csi_drop_absolute: float = 0.15
    min_events_csi_trigger: int = 3
    pipeline_consecutive_failures: int = 3
    coverage_degraded_threshold: float = 0.50
    coverage_consecutive_cycles: int = 2
    cooldown_days: int = 7
    circuit_breaker_window_days: int = 14
    circuit_breaker_max_rollbacks: int = 2


@dataclass
class ModelSwitchingConfig:
    enabled: bool = False
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    margin: MarginConfig = field(default_factory=MarginConfig)
    floors: FloorsConfig = field(default_factory=FloorsConfig)
    regions: List[str] = field(default_factory=lambda: ["EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"])
    windows: WindowsConfig = field(default_factory=WindowsConfig)
    durations: DurationsConfig = field(default_factory=DurationsConfig)
    rollback: RollbackConfig = field(default_factory=RollbackConfig)


def load_model_switching_config(config_path: Optional[Path] = None) -> ModelSwitchingConfig:
    """Loads and validates model_switching.yaml, returning a ModelSwitchingConfig dataclass."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        logger.warning(f"Config file not found at {path}, returning default configuration.")
        return ModelSwitchingConfig()

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        weights_data = raw.get("weights", {})
        margin_data = raw.get("margin", {})
        floors_data = raw.get("floors", {})
        windows_data = raw.get("windows", {})
        durations_data = raw.get("durations", {})
        rollback_data = raw.get("rollback", {})

        return ModelSwitchingConfig(
            enabled=raw.get("enabled", False),
            weights=ScoringWeights(**weights_data) if weights_data else ScoringWeights(),
            margin=MarginConfig(**margin_data) if margin_data else MarginConfig(),
            floors=FloorsConfig(**floors_data) if floors_data else FloorsConfig(),
            regions=raw.get("regions", ["EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"]),
            windows=WindowsConfig(**windows_data) if windows_data else WindowsConfig(),
            durations=DurationsConfig(**durations_data) if durations_data else DurationsConfig(),
            rollback=RollbackConfig(**rollback_data) if rollback_data else RollbackConfig(),
        )
    except Exception as e:
        logger.error(f"Error loading model switching config from {path}: {e}")
        return ModelSwitchingConfig()


# Convenient alias
load_switching_config = load_model_switching_config

