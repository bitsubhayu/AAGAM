"""Tests for Final Phase 1 Training Parquet Dataset (PRD §7.3)."""

from pathlib import Path

import pandas as pd

from pipeline.processing.aggregation import validate_alignment_keys

TRAINING_PARQUET = Path(__file__).resolve().parent.parent / "data" / "training_dataset.parquet"

EXPECTED_COLUMNS = [
    "valid_date", "location_id", "variable", "lead_days",
    "truth", "truth_source",
    "f_gfs", "f_ecmwf_ifs", "f_icon", "f_aifs",
    "mean", "std", "max", "min",
    "doy_sin", "doy_cos", "lat", "lon", "region", "season", "regime",
]


def test_training_parquet_schema_and_keys():
    """Verifies that the generated training parquet matches PRD §7.3 schema exactly."""
    assert TRAINING_PARQUET.exists(), f"Parquet file missing at {TRAINING_PARQUET}"

    df = pd.read_parquet(TRAINING_PARQUET)
    assert not df.empty, "Training dataset is empty"

    # Column schema check
    for col in EXPECTED_COLUMNS:
        assert col in df.columns, f"Required column '{col}' missing from training dataset"

    # Alignment key uniqueness check
    val_report = validate_alignment_keys(df, keys=("location_id", "valid_date", "variable", "lead_days"))
    assert val_report["duplicate_count"] == 0, f"Duplicate keys found: {val_report['duplicate_count']}"

    # Locations, variables, and lead days completeness
    assert df["location_id"].nunique() in (10, 40), f"Expected 10 (interim) or 40 (complete) locations, found {df['location_id'].nunique()}"
    assert sorted(df["lead_days"].unique().tolist()) == [1, 2, 3, 4, 5, 6, 7]
    assert set(df["variable"].unique()) == {"rain_mm", "tmax_c", "wind_max_kmh"}

    # Truth source tracking
    assert set(df["truth_source"].unique()).issubset({"imd_gridded", "era5_historical"})
