"""Location Validation Test Suite for AAGAM (Phase 1).

Verifies:
1. config/locations.yaml has exactly 40 locations.
2. Unique slugs, valid region codes, and valid terrains.
3. Supabase `locations` table has exactly 40 rows.
4. Valid PostGIS geography(Point, 4326) within India geographic bounds.
"""

from pathlib import Path

import psycopg2
import yaml

from core.config import settings

VALID_REGIONS = {"NW", "CENTRAL", "EAST_NE", "SOUTH", "HIMALAYAN"}
VALID_TERRAINS = {"plains", "coastal", "hills"}


def test_locations_yaml_structure():
    """Verify YAML specification integrity."""
    root = Path(__file__).resolve().parent.parent
    loc_file = root / "config" / "locations.yaml"
    assert loc_file.exists(), "config/locations.yaml not found"

    with open(loc_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    locations = data.get("locations", [])
    assert len(locations) == 40, f"Expected exactly 40 locations, found {len(locations)}"

    slugs = set()
    for loc in locations:
        slug = loc["slug"]
        assert slug not in slugs, f"Duplicate slug in YAML: {slug}"
        slugs.add(slug)
        assert loc["region"] in VALID_REGIONS, f"Invalid region {loc['region']} for {slug}"
        assert loc["terrain"] in VALID_TERRAINS, f"Invalid terrain {loc['terrain']} for {slug}"


def test_supabase_locations_database():
    """Verify Supabase database locations table has 40 valid PostGIS rows."""
    conn = psycopg2.connect(settings.DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM locations;")
        count = cur.fetchone()[0]
        assert count == 40, f"Expected 40 rows in DB, found {count}"

        cur.execute("SELECT COUNT(DISTINCT slug) FROM locations;")
        unique_slugs = cur.fetchone()[0]
        assert unique_slugs == 40, f"Expected 40 unique slugs in DB, found {unique_slugs}"

        cur.execute("""
            SELECT slug, region, terrain,
                   ST_Y(geog::geometry) AS lat,
                   ST_X(geog::geometry) AS lon,
                   ST_IsValid(geog::geometry) AS is_valid
            FROM locations;
        """)
        rows = cur.fetchall()

    conn.close()

    for slug, region, terrain, lat, lon, is_valid in rows:
        assert is_valid, f"Invalid PostGIS geography geometry for {slug}"
        assert region in VALID_REGIONS, f"Invalid region {region} for {slug}"
        assert terrain in VALID_TERRAINS, f"Invalid terrain {terrain} for {slug}"
        # India bounds
        assert 6.0 <= lat <= 38.5, f"Latitude out of India bounds for {slug}: {lat}"
        assert 66.0 <= lon <= 100.0, f"Longitude out of India bounds for {slug}: {lon}"
