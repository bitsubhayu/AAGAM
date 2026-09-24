"""Unit tests for temporal safety and data leakage prevention.

Authoritative source: AAGAM_MODEL_VERSIONING_DESIGN.md §D, §F, §R
"""

from __future__ import annotations

from datetime import date

from pipeline.versioning.floors import validate_evaluation_window_temporal_safety


class TestTemporalSafety:
    """Tests temporal boundaries and data-leakage guards."""

    def test_future_data_leakage_blocked(self):
        """Case 13a: Evaluation window cannot extend past current operational date (as_of_date)."""
        as_of = date(2026, 9, 23)
        eval_start = date(2026, 9, 10)
        eval_end = date(2026, 9, 25)  # 2 days in future!

        passed, reason = validate_evaluation_window_temporal_safety(
            evaluation_window_start=eval_start,
            evaluation_window_end=eval_end,
            as_of_date=as_of,
        )
        assert passed is False
        assert "Temporal leakage" in reason
        assert "is after as_of_date" in reason

    def test_training_partition_overlap_blocked(self):
        """Case 13b: Evaluation window cannot overlap the candidate's training data."""
        train_end = date(2026, 6, 30)
        as_of = date(2026, 9, 23)
        eval_start = date(2026, 6, 15)  # Overlaps training partition!
        eval_end = date(2026, 9, 20)

        passed, reason = validate_evaluation_window_temporal_safety(
            evaluation_window_start=eval_start,
            evaluation_window_end=eval_end,
            as_of_date=as_of,
            training_window_end=train_end,
        )
        assert passed is False
        assert "Data leakage" in reason
        assert "overlaps training partition" in reason

    def test_validation_partition_overlap_blocked(self):
        """Case 13c: Evaluation window cannot overlap the candidate's validation partition."""
        train_end = date(2026, 6, 30)
        val_end = date(2026, 7, 31)
        as_of = date(2026, 9, 23)
        eval_start = date(2026, 7, 15)  # Overlaps validation partition!
        eval_end = date(2026, 9, 20)

        passed, reason = validate_evaluation_window_temporal_safety(
            evaluation_window_start=eval_start,
            evaluation_window_end=eval_end,
            as_of_date=as_of,
            training_window_end=train_end,
            validation_window_end=val_end,
        )
        assert passed is False
        assert "Data leakage" in reason
        assert "overlaps validation partition" in reason

    def test_inverted_date_bounds_blocked(self):
        """Evaluation window start cannot be after end."""
        as_of = date(2026, 9, 23)
        passed, reason = validate_evaluation_window_temporal_safety(
            evaluation_window_start=date(2026, 9, 20),
            evaluation_window_end=date(2026, 9, 10),
            as_of_date=as_of,
        )
        assert passed is False
        assert "Invalid window bounds" in reason

    def test_strictly_valid_temporal_window_passes(self):
        """Clean evaluation window strictly after validation and before as_of_date passes."""
        train_end = date(2026, 6, 30)
        val_end = date(2026, 7, 31)
        eval_start = date(2026, 8, 1)
        eval_end = date(2026, 9, 22)
        as_of = date(2026, 9, 23)

        passed, reason = validate_evaluation_window_temporal_safety(
            evaluation_window_start=eval_start,
            evaluation_window_end=eval_end,
            as_of_date=as_of,
            training_window_end=train_end,
            validation_window_end=val_end,
        )
        assert passed is True
        assert reason is None
