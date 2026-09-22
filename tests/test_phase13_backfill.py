"""
Tests for Phase 13 Climatology Backfill Pipeline.
Covers:
- Controlled historical backfill logic.
- Idempotency / repeat-safety: running backfill multiple times uses ON CONFLICT DO UPDATE.
- Dry run support.
- Station filtering and empty dataset handling.
"""

import datetime as dt
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pipeline.climatology.backfill import run_climatology_backfill


@pytest.fixture
def sample_truth_df():
    """Generates 16 years of sample observations for location 1."""
    rows = []
    base_date = dt.date(2005, 1, 1)
    for i in range(16 * 365):
        d = base_date + dt.timedelta(days=i)
        rows.append({
            "location_id": 1,
            "valid_date": pd.to_datetime(d),
            "rain_truth": 15.0 + (i % 10),
            "tmax_truth": 35.0 + (i % 5),
            "wind_max_truth": 20.0 + (i % 8),
        })
    return pd.DataFrame(rows)


class TestClimatologyBackfill:
    def test_backfill_dry_run(self, sample_truth_df):
        """Verify dry run calculates all records without touching database."""
        res = run_climatology_backfill(
            truth_source=sample_truth_df,
            location_ids=[1],
            min_years=15,
            dry_run=True,
        )
        assert res["status"] == "SUCCESS"
        assert res["locations_processed"] == 1
        # 366 DOYs * 4 (rain 1d, rain 3d, tmax 1d, wind 1d) = 1464 rows
        assert res["records_computed"] == 366 * 4

    def test_backfill_idempotent_sql_execution(self, sample_truth_df):
        """Verify backfill invokes execute_values with ON CONFLICT DO UPDATE on exact primary keys."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.connection.encoding = "UTF8"
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        with patch("psycopg2.connect", return_value=mock_conn), \
             patch("pipeline.climatology.backfill.execute_values") as mock_execute_values:

            res = run_climatology_backfill(
                truth_source=sample_truth_df,
                location_ids=[1],
                min_years=15,
                dry_run=False,
                db_url="postgresql://mock:mock@localhost:5432/mock",
            )

            assert res["status"] == "SUCCESS"
            assert mock_execute_values.called
            # First positional arg is cursor, second is query string
            called_query = mock_execute_values.call_args[0][1]
            assert "ON CONFLICT (location_id, variable, metric, doy_window) DO UPDATE" in called_query
            assert "SET mean = EXCLUDED.mean" in called_query

    def test_backfill_empty_dataset_handling(self):
        """Verify backfill handles empty truth dataset gracefully."""
        res = run_climatology_backfill(
            truth_source=pd.DataFrame(),
            dry_run=True,
        )
        assert res["status"] == "EMPTY"
        assert res["records_computed"] == 0
        assert res["locations_processed"] == 0
