"""AAGAM Climatology & Local Extremeness Engine (Phase 13, PRD §6.11, §11.2)."""

from pipeline.climatology.percentiles import (
    calculate_percentiles,
    compute_3day_rainfall_sums,
    compute_station_climatology,
    get_rarity_label,
    is_doy_in_window,
)

__all__ = [
    "is_doy_in_window",
    "compute_3day_rainfall_sums",
    "calculate_percentiles",
    "get_rarity_label",
    "compute_station_climatology",
]
