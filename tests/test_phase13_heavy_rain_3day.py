"""
Tests for Phase 13 heavy_rain_3day hazard evaluation.
Covers:
- Rolling 3-day aggregation across 7-day forecast horizon.
- Threshold crossing against climatology percentiles (p90 -> advisory, p95 -> watch, p99 -> alert).
- Rarity label attachment ("roughly a 1-in-100 event", etc.).
- Strict suppression when climatology is missing or n_years < 15.
- Integration into ExtremeGuidanceEngine.
"""

import datetime as dt

import pandas as pd
import pytest

from pipeline.blend.extremes import ExtremeGuidanceEngine


class DummyClimatology:
    class DummyMeta:
        source = "test_source"
    metadata = DummyMeta()

    def get_normal_tmax(self, loc_id, doy):
        return 35.0


class DummyUncertainty:
    def evaluate_uncertainty(self, *args, **kwargs):
        return False, 0.0, ""


@pytest.fixture
def base_meta():
    return {
        "id": 1,
        "name": "Kolkata (Alipore)",
        "slug": "kolkata-alipore",
        "terrain": "plains",
        "region": "east",
    }


def make_forecast_df(start_date: dt.date, rain_values: list):
    """Creates a 7-day precipitation forecast dataframe for a location."""
    rows = []
    for i, rain in enumerate(rain_values):
        v_date = start_date + dt.timedelta(days=i + 1)
        lead = i + 1
        rows.append({
            "location_id": 1,
            "variable": "precipitation",
            "valid_date": str(v_date),
            "lead_days": lead,
            "blended": rain,
            "f_gfs": rain * 0.95,
            "f_ecmwf_ifs": rain * 1.05,
            "f_icon": rain * 1.0,
            "f_aifs": rain * 0.98,
            "spread": 2.5,
            "degraded": False,
            "region": "east",
            "season": "monsoon",
            "regime": "wet",
        })
    return pd.DataFrame(rows)


class TestHeavyRain3Day:
    def test_heavy_rain_3day_alert_levels(self, base_meta):
        # Setup percentiles lookup with sufficient history (n_years = 25)
        # For a target DOY (say July 10, DOY 191..197)
        start_date = dt.date(2026, 7, 7)
        doy_end_day3 = (start_date + dt.timedelta(days=3)).timetuple().tm_yday

        climo_lookup = {
            (1, "rain_mm", "3day_sum", doy_end_day3): {
                "mean": 80.0,
                "p90": 120.0,
                "p95": 160.0,
                "p99": 220.0,
                "n_years": 25,
            }
        }

        engine = ExtremeGuidanceEngine(
            climatology_engine=DummyClimatology(),
            uncertainty_engine=DummyUncertainty(),
            climatology_percentiles_lookup=climo_lookup,
        )

        now = dt.datetime(2026, 7, 7, 6, 0, tzinfo=dt.timezone.utc)

        # Case 1: 3-day sum exceeds p99 (Alert)
        # Rain: [80, 80, 80, 10, 10, 10, 10] -> 3-day sum = 240 >= 220
        df_alert = make_forecast_df(start_date, [80.0, 80.0, 80.0, 10.0, 10.0, 10.0, 10.0])
        alerts = engine.evaluate_heavy_rain_3day_hazards_for_location(df_alert, base_meta, now)
        assert len(alerts) >= 1
        a_p99 = alerts[0]
        assert a_p99.hazard == "heavy_rain_3day"
        assert a_p99.severity == "alert"
        assert a_p99.value == 240.0
        assert a_p99.rarity_label == "roughly a 1-in-100 event"
        assert a_p99.rule["p99"] == 220.0
        assert a_p99.rule["threshold_applied"] == 220.0

        # Case 2: 3-day sum exceeds p95 but below p99 (Watch)
        # Rain: [60, 60, 60, 10, 10, 10, 10] -> 3-day sum = 180 >= 160
        df_watch = make_forecast_df(start_date, [60.0, 60.0, 60.0, 10.0, 10.0, 10.0, 10.0])
        alerts = engine.evaluate_heavy_rain_3day_hazards_for_location(df_watch, base_meta, now)
        assert len(alerts) >= 1
        a_p95 = alerts[0]
        assert a_p95.severity == "watch"
        assert a_p95.value == 180.0
        assert a_p95.rarity_label == "roughly a 1-in-20 event"

        # Case 3: 3-day sum exceeds p90 but below p95 (Advisory)
        # Rain: [45, 45, 45, 10, 10, 10, 10] -> 3-day sum = 135 >= 120
        df_adv = make_forecast_df(start_date, [45.0, 45.0, 45.0, 10.0, 10.0, 10.0, 10.0])
        alerts = engine.evaluate_heavy_rain_3day_hazards_for_location(df_adv, base_meta, now)
        assert len(alerts) >= 1
        a_p90 = alerts[0]
        assert a_p90.severity == "advisory"
        assert a_p90.value == 135.0
        assert a_p90.rarity_label == "roughly a 1-in-10 event"

        # Case 4: 3-day sum below p90 (< 120) -> No alert
        df_none = make_forecast_df(start_date, [30.0, 30.0, 30.0, 10.0, 10.0, 10.0, 10.0])
        alerts = engine.evaluate_heavy_rain_3day_hazards_for_location(df_none, base_meta, now)
        assert len(alerts) == 0

    def test_insufficient_history_suppression(self, base_meta):
        # Climatology has n_years = 12 (< 15 required)
        start_date = dt.date(2026, 7, 7)
        doy_end_day3 = (start_date + dt.timedelta(days=3)).timetuple().tm_yday

        climo_lookup = {
            (1, "rain_mm", "3day_sum", doy_end_day3): {
                "mean": 80.0,
                "p90": 120.0,
                "p95": 160.0,
                "p99": 220.0,
                "n_years": 12,  # INSUFFICIENT
            }
        }

        engine = ExtremeGuidanceEngine(
            climatology_engine=DummyClimatology(),
            uncertainty_engine=DummyUncertainty(),
            climatology_percentiles_lookup=climo_lookup,
        )

        now = dt.datetime(2026, 7, 7, 6, 0, tzinfo=dt.timezone.utc)
        # Even with an extreme 3-day rainfall of 300 mm, suppress alert
        df_rain = make_forecast_df(start_date, [100.0, 100.0, 100.0, 10.0, 10.0, 10.0, 10.0])
        alerts = engine.evaluate_heavy_rain_3day_hazards_for_location(df_rain, base_meta, now)

        # STRICT SAFEGUARD: Must produce NO alert when n_years < 15
        assert len(alerts) == 0

    def test_missing_climatology_suppression(self, base_meta):
        # Empty climatology lookup
        engine = ExtremeGuidanceEngine(
            climatology_engine=DummyClimatology(),
            uncertainty_engine=DummyUncertainty(),
            climatology_percentiles_lookup={},
        )
        now = dt.datetime(2026, 7, 7, 6, 0, tzinfo=dt.timezone.utc)
        df_rain = make_forecast_df(dt.date(2026, 7, 7), [100.0, 100.0, 100.0, 10.0, 10.0, 10.0, 10.0])
        alerts = engine.evaluate_heavy_rain_3day_hazards_for_location(df_rain, base_meta, now)
        assert len(alerts) == 0
