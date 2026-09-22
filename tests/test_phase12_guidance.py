"""Phase 12 — Hazard Guidance Tests (PRD §11.3, Feature C).

Tests static, team-authored hazard guidance:
- Loads from config/hazard_guidance.yaml.
- Covers all supported hazards and severities.
- Contains official IMD warning link.
- Is strictly deterministic and not dynamically generated.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from api.app.services.hazard_guidance import get_hazard_guidance

IMD_OFFICIAL_URL = "https://mausam.imd.gov.in/responsive/districtWiseWarningGIS.php"
SUPPORTED_HAZARDS = ["heavy_rain", "heatwave", "high_wind", "heavy_rain_3day"]
SUPPORTED_SEVERITIES = ["advisory", "watch", "alert"]


def test_hazard_guidance_yaml_structure():
    """Verify config/hazard_guidance.yaml exists and contains valid YAML."""
    config_path = Path("config/hazard_guidance.yaml")
    assert config_path.exists(), "config/hazard_guidance.yaml must exist"

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "guidance" in data
    assert "imd_warning_portal" in data
    portal = data["imd_warning_portal"]
    assert portal.get("url") == IMD_OFFICIAL_URL
    assert "IMD" in portal.get("label", "")


def test_all_hazards_and_severities_covered():
    """Verify guidance exists for all 4 hazards x 3 severities = 12 combinations."""
    for hazard in SUPPORTED_HAZARDS:
        for severity in SUPPORTED_SEVERITIES:
            guidance = get_hazard_guidance(hazard, severity)
            assert guidance is not None, f"Missing guidance for {hazard} - {severity}"
            assert guidance["hazard"] == hazard
            assert guidance["severity"] == severity
            assert len(guidance["headline"]) > 5, f"Headline too short for {hazard} - {severity}"
            assert len(guidance["body"]) > 30, f"Body too short for {hazard} - {severity}"
            assert isinstance(guidance["precautions"], list)
            assert len(guidance["precautions"]) >= 3, f"Need at least 3 precautions for {hazard} - {severity}"
            assert guidance["official_link"] == IMD_OFFICIAL_URL, "Must contain official IMD warning URL"


def test_hazard_guidance_deterministic():
    """Verify static guidance is deterministic and repeatable across calls."""
    g1 = get_hazard_guidance("heavy_rain", "watch")
    g2 = get_hazard_guidance("heavy_rain", "watch")
    assert g1 == g2
    assert "Be Prepared" in g1["headline"]


def test_unknown_hazard_returns_none():
    """Verify querying an unsupported hazard or severity returns None without error."""
    assert get_hazard_guidance("unknown_storm", "alert") is None
    assert get_hazard_guidance("heavy_rain", "catastrophic") is None
