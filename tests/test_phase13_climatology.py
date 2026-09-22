"""
Tests for Phase 13 Climatology Core Engine.
Covers:
- Circular DOY window (±7 days) and year-boundary wrapping (DOY 1, 365, 366).
- 1-day and 3-day rolling rainfall sum calculations.
- Deterministic percentile calculations (p90, p95, p99).
- History count (n_years) and strict insufficient-history safeguard (n_years < 15).
- Local extremeness rarity mapping.
"""

import datetime

import pandas as pd

from pipeline.climatology.percentiles import (
    calculate_percentiles,
    compute_3day_rainfall_sums,
    compute_station_climatology,
    get_rarity_label,
    is_doy_in_window,
)


class TestDoyWindow:
    """Test the circular DOY ±7 day window, including year boundary wrapping."""

    def test_mid_year_window(self):
        # DOY 180 should match [173, 187]
        target_doy = 180
        assert is_doy_in_window(180, target_doy) is True
        assert is_doy_in_window(173, target_doy) is True
        assert is_doy_in_window(187, target_doy) is True
        assert is_doy_in_window(172, target_doy) is False
        assert is_doy_in_window(188, target_doy) is False

    def test_year_boundary_start_of_year(self):
        # DOY 1: window ±7 days wraps to include 360..366 and 1..8
        target_doy = 1
        assert is_doy_in_window(1, target_doy) is True
        assert is_doy_in_window(2, target_doy) is True
        assert is_doy_in_window(8, target_doy) is True
        assert is_doy_in_window(9, target_doy) is False

        # Year boundary wrap backwards
        assert is_doy_in_window(365, target_doy) is True
        assert is_doy_in_window(366, target_doy) is True
        assert is_doy_in_window(360, target_doy) is True
        assert is_doy_in_window(358, target_doy) is False

    def test_year_boundary_end_of_year(self):
        # DOY 365: window ±7 wraps to include 358..366 and 1..6
        target_doy = 365
        assert is_doy_in_window(365, target_doy) is True
        assert is_doy_in_window(358, target_doy) is True
        assert is_doy_in_window(357, target_doy) is False

        # Year boundary wrap forwards
        assert is_doy_in_window(1, target_doy) is True
        assert is_doy_in_window(5, target_doy) is True
        assert is_doy_in_window(10, target_doy) is False


class TestRolling3DaySum:
    """Test rolling 3-day accumulated rainfall sum computation."""

    def test_rolling_sums_consecutive_days(self):
        # Daily records across 5 consecutive days
        start = datetime.date(2020, 1, 1)
        dates = [start + datetime.timedelta(days=i) for i in range(5)]
        rains = [10.0, 20.0, 30.0, 40.0, 50.0]
        df = pd.DataFrame({
            "location_id": 1,
            "valid_date": pd.to_datetime(dates),
            "rain_truth": rains,
        })
        res = compute_3day_rainfall_sums(df, rain_col="rain_truth")
        # Sums should have 3 rows (days 3, 4, 5)
        assert len(res) == 3
        # Day 3 sum: 10 + 20 + 30 = 60
        assert res.iloc[0]["rain_3day_sum"] == 60.0
        # Day 4 sum: 20 + 30 + 40 = 90
        assert res.iloc[1]["rain_3day_sum"] == 90.0
        # Day 5 sum: 30 + 40 + 50 = 120
        assert res.iloc[2]["rain_3day_sum"] == 120.0

    def test_rolling_sums_with_gap(self):
        # Missing Day 3
        dates = [
            datetime.date(2020, 1, 1),
            datetime.date(2020, 1, 2),
            # Gap on 2020-01-03
            datetime.date(2020, 1, 4),
            datetime.date(2020, 1, 5),
            datetime.date(2020, 1, 6),
        ]
        rains = [10.0, 20.0, 30.0, 40.0, 50.0]
        df = pd.DataFrame({
            "location_id": 1,
            "valid_date": pd.to_datetime(dates),
            "rain_truth": rains,
        })
        res = compute_3day_rainfall_sums(df, rain_col="rain_truth")
        # Only Jan 6 has full 3-day consecutive history (Jan 4, 5, 6)
        assert len(res) == 1
        assert res.iloc[0]["rain_3day_sum"] == 120.0


class TestPercentileCalculations:
    """Test percentile calculations and strict history safeguards."""

    def test_sufficient_history_calculations(self):
        # 20 years of data
        vals = [float(i) for i in range(1, 101)]
        stats = calculate_percentiles(vals, n_years=20, min_years=15)
        assert stats["p90"] is not None
        assert stats["p95"] is not None
        assert stats["p99"] is not None
        assert stats["p90"] <= stats["p95"] <= stats["p99"]
        # With 1..100, 90th percentile is ~90.1, 95th ~95.05, 99th ~99.01
        assert 89.0 <= stats["p90"] <= 91.0
        assert 94.0 <= stats["p95"] <= 96.0
        assert 98.0 <= stats["p99"] <= 100.0

    def test_insufficient_history_suppression(self):
        # Only 10 years of history (< 15 required)
        vals = [float(i) for i in range(1, 101)]
        stats = calculate_percentiles(vals, n_years=10, min_years=15)
        # STRICT REQUIREMENT: DO NOT fabricate percentiles, return None
        assert stats["mean"] is None
        assert stats["p90"] is None
        assert stats["p95"] is None
        assert stats["p99"] is None

    def test_empty_records(self):
        stats = calculate_percentiles([], n_years=20, min_years=15)
        assert stats["mean"] is None
        assert stats["p90"] is None
        assert stats["p95"] is None
        assert stats["p99"] is None


class TestRarityMapping:
    """Test local rarity classification according to Upgrade Pack v1.1."""

    def test_rarity_levels_sufficient_history(self):
        p90 = 70.0
        p95 = 100.0
        p99 = 150.0
        n_years = 20

        # >= p99
        assert get_rarity_label(160.0, p90, p95, p99, n_years) == "roughly a 1-in-100 event"
        assert get_rarity_label(150.0, p90, p95, p99, n_years) == "roughly a 1-in-100 event"

        # >= p95 and < p99
        assert get_rarity_label(120.0, p90, p95, p99, n_years) == "roughly a 1-in-20 event"
        assert get_rarity_label(100.0, p90, p95, p99, n_years) == "roughly a 1-in-20 event"

        # >= p90 and < p95
        assert get_rarity_label(85.0, p90, p95, p99, n_years) == "roughly a 1-in-10 event"
        assert get_rarity_label(70.0, p90, p95, p99, n_years) == "roughly a 1-in-10 event"

        # < p90
        assert get_rarity_label(65.0, p90, p95, p99, n_years) is None

    def test_rarity_with_insufficient_history(self):
        # n_years < 15 must suppress even if value exceeds thresholds
        assert get_rarity_label(200.0, 70.0, 100.0, 150.0, n_years=14) is None
        assert get_rarity_label(200.0, None, None, None, n_years=14) is None
        assert get_rarity_label(200.0, 70.0, None, None, n_years=20) is None


class TestStationClimatologyComputation:
    """Test end-to-end station climatology generation."""

    def test_computes_1day_and_3day_for_station(self):
        # Generate 16 years of synthetic daily rain data
        dates = []
        rains = []
        base = datetime.date(2005, 1, 1)
        for i in range(16 * 365):
            d = base + datetime.timedelta(days=i)
            dates.append(d)
            # Give reasonable rainfall in monsoon (DOY ~150-200)
            rain = 30.0 + (i % 20) if 150 <= d.timetuple().tm_yday <= 200 else 2.0
            rains.append(rain)

        df = pd.DataFrame({
            "location_id": 1,
            "valid_date": pd.to_datetime(dates),
            "rain_truth": rains,
        })

        rows_1d = compute_station_climatology(
            df_observations=df,
            location_id=1,
            variable="rain_mm",
            metric="1day",
            value_col="rain_truth",
        )
        assert len(rows_1d) == 366
        row_170_1d = next(r for r in rows_1d if r["doy_window"] == 170)
        assert row_170_1d["location_id"] == 1
        assert row_170_1d["variable"] == "rain_mm"
        assert row_170_1d["metric"] == "1day"
        assert row_170_1d["n_years"] >= 15
        assert row_170_1d["p90"] is not None
        assert row_170_1d["p99"] >= row_170_1d["p90"]

        rows_3d = compute_station_climatology(
            df_observations=df,
            location_id=1,
            variable="rain_mm",
            metric="3day_sum",
            value_col="rain_truth",
        )
        assert len(rows_3d) == 366
        row_170_3d = next(r for r in rows_3d if r["doy_window"] == 170)
        assert row_170_3d["metric"] == "3day_sum"
        assert row_170_3d["n_years"] >= 15
        assert row_170_3d["p90"] is not None
        assert row_170_3d["p99"] >= row_170_3d["p90"]
