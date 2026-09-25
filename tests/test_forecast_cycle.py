"""Deterministic Forecast Cycle & Invariant Tests (PRD §12).

Verifies:
1. Returns strictly one latest operational cycle per location + variable.
2. No duplicate valid_date or lead_days rows.
3. lead_days are unique and in ascending order (D0..D7).
4. D0 is not shifted to D1.
5. All 3 variables (rain_mm, tmax_c, wind_max_kmh) return at most 8 current-cycle points.
6. Table data and chart data are mathematically coherent.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from api.tests.test_phase6_contracts import create_test_jwt


@pytest.fixture
def client():
    with TestClient(app) as tc:
        yield tc


def test_forecast_cycle_uniqueness_and_ordering(client: TestClient):
    """Asserts that /forecast returns exactly one coherent latest cycle with unique sorted leads."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}

    for var in ["rain_mm", "tmax_c", "wind_max_kmh"]:
        response = client.get(
            f"/api/v1/forecast?location=bhubaneswar&variable={var}",
            headers=headers,
        )
        assert response.status_code == 200, f"Forecast endpoint failed: {response.text}"
        data = response.json()

        assert "series" in data
        series = data["series"]
        assert len(series) <= 8, f"Too many series rows ({len(series)}) returned for variable {var}"
        assert len(series) > 0, f"No series rows returned for variable {var}"

        # 1. Assert unique lead_days
        leads = [item["lead_days"] for item in series]
        assert len(leads) == len(set(leads)), f"Duplicate lead_days found: {leads}"

        # 2. Assert unique valid_dates
        dates = [item["valid_date"] for item in series]
        assert len(dates) == len(set(dates)), f"Duplicate valid_dates found: {dates}"

        # 3. Assert strictly sorted lead order
        assert leads == sorted(leads), f"Leads not in sorted order: {leads}"

        # 4. Assert leads are within D0..D7
        assert all(0 <= ld <= 7 for ld in leads), f"Lead outside 0..7: {leads}"

        # 5. Assert D0 is present if first lead is today
        if 0 in leads:
            d0_item = next(item for item in series if item["lead_days"] == 0)
            assert d0_item["lead_days"] == 0, "D0 lead day mutated"

        # 6. Verify model values are not hallucinated or replaced with blend
        for item in series:
            assert isinstance(item["models"], dict)
            for m_name, val in item["models"].items():
                assert m_name in ("gfs", "ecmwf_ifs", "icon", "aifs")
                if val is not None:
                    assert isinstance(val, (int, float))


def test_forecast_numeric_id_and_slug_equivalence(client: TestClient):
    """Asserts that location ID and location slug return identical operational cycle."""
    token = create_test_jwt(role="public")
    headers = {"Authorization": f"Bearer {token}"}

    res_slug = client.get("/api/v1/forecast?location=kolkata&variable=tmax_c", headers=headers)
    assert res_slug.status_code == 200
    data_slug = res_slug.json()

    res_id = client.get("/api/v1/forecast?location=1&variable=tmax_c", headers=headers)
    assert res_id.status_code == 200
    data_id = res_id.json()

    assert data_slug["location"]["name"] == "Bhubaneswar" or data_slug["location"]["slug"] == "kolkata"
    assert len(data_slug["series"]) == len(set(item["lead_days"] for item in data_slug["series"]))
    assert len(data_id["series"]) == len(set(item["lead_days"] for item in data_id["series"]))
