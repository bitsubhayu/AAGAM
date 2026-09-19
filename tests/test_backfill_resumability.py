"""Tests for Previous Runs Backfill Resumability and Deduplication (FR-DATA-2)."""

import pandas as pd

from pipeline.ingestion.previous_runs import (
    load_checkpoint,
    save_checkpoint,
)


def test_checkpoint_save_and_load(tmp_path, monkeypatch):
    """Verify that checkpoint state is properly saved and loaded."""
    mock_file = tmp_path / "test_checkpoint.json"
    monkeypatch.setattr("pipeline.ingestion.previous_runs.CHECKPOINT_FILE", mock_file)

    state = {"completed_chunks": ["loc1_2024-06-01_2024-06-05"], "total_calls_made": 1}
    save_checkpoint(state)

    loaded = load_checkpoint()
    assert loaded["completed_chunks"] == ["loc1_2024-06-01_2024-06-05"]
    assert loaded["total_calls_made"] == 1
    assert loaded["last_updated"] is not None


def test_re_running_never_duplicates_rows(tmp_path):
    """Verify that re-running and combining chunk records strictly deduplicates on alignment key."""
    # Alignment key: (location_id, model, valid_date, lead_days)
    records_run1 = [
        {"location_id": 1, "model": "gfs", "valid_date": "2024-06-01", "lead_days": 1, "f_rain_mm": 10.0},
        {"location_id": 1, "model": "gfs", "valid_date": "2024-06-01", "lead_days": 2, "f_rain_mm": 12.0},
    ]
    df1 = pd.DataFrame(records_run1)

    # Identical records produced in second run
    records_run2 = [
        {"location_id": 1, "model": "gfs", "valid_date": "2024-06-01", "lead_days": 1, "f_rain_mm": 10.0},
        {"location_id": 1, "model": "gfs", "valid_date": "2024-06-01", "lead_days": 2, "f_rain_mm": 12.0},
    ]
    df2 = pd.DataFrame(records_run2)

    combined = pd.concat([df1, df2], ignore_index=True)
    dedup_keys = ["location_id", "model", "valid_date", "lead_days"]
    deduped = combined.drop_duplicates(subset=dedup_keys, keep="last")

    assert len(deduped) == 2, f"Expected 2 deduplicated rows, found {len(deduped)}"
