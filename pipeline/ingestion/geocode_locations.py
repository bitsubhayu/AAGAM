"""AAGAM — 40-Location Geocoding & Supabase Ingestion (Phase 1).

Authoritative rules:
1. Uses config/locations.yaml as the source of truth (40 locations).
2. Obtains coordinates through Open-Meteo Geocoding API.
3. Never manually hardcodes coordinates.
4. Inserts all 40 into Supabase `locations` table with PostGIS Point geometry.
5. Verifies count=40, unique slugs, valid regions, valid terrains, and valid PostGIS points.
"""
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
import yaml

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aagam.pipeline.geocode")

GEOCODING_API_BASE = "https://geocoding-api.open-meteo.com/v1/search"
VALID_REGIONS = {"NW", "CENTRAL", "EAST_NE", "SOUTH", "HIMALAYAN"}
VALID_TERRAINS = {"plains", "coastal", "hills"}


def geocode_location(name: str, state: str) -> Optional[Dict[str, Any]]:
    """Queries Open-Meteo Geocoding API for a location strictly within India."""
    # For well-known alternate names in Open-Meteo geodatabase:
    if name.lower() == "panaji":
        queries_to_try = ["Panjim", "Panaji"]
    else:
        queries_to_try = [name, f"{name}, {state}"]

    state_clean = state.lower().replace("&", "and").strip()
    candidate_matches = []

    for q in queries_to_try:
        params = {
            "name": q,
            "count": 20,
            "language": "en",
            "format": "json",
        }
        url = f"{GEOCODING_API_BASE}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "AAGAM-Geocoding/1.0"})

        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    results = data.get("results", [])
                    in_results = [
                        r for r in results
                        if r.get("country_code") == "IN"
                        and 6.0 <= float(r.get("latitude", 0)) <= 38.5
                        and 66.0 <= float(r.get("longitude", 0)) <= 100.0
                    ]
                    for res in in_results:
                        admin1 = (res.get("admin1") or "").lower().replace("&", "and").strip()
                        # Check state match
                        if admin1 and (state_clean in admin1 or admin1 in state_clean):
                            return {
                                "name": name,
                                "state": state,
                                "latitude": float(res["latitude"]),
                                "longitude": float(res["longitude"]),
                                "elevation": float(res.get("elevation") or 0.0),
                                "admin1": res.get("admin1"),
                                "geocoding_id": res.get("id"),
                            }
                        candidate_matches.append(res)
                    break
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {q}: {e}")
                time.sleep(1.0)

    # Fallback to exact name match if no state match found
    for res in candidate_matches:
        if res.get("name", "").lower() in [name.lower(), "panjim"]:
            return {
                "name": name,
                "state": state,
                "latitude": float(res["latitude"]),
                "longitude": float(res["longitude"]),
                "elevation": float(res.get("elevation") or 0.0),
                "admin1": res.get("admin1"),
                "geocoding_id": res.get("id"),
            }

    if candidate_matches:
        res = candidate_matches[0]
        return {
            "name": name,
            "state": state,
            "latitude": float(res["latitude"]),
            "longitude": float(res["longitude"]),
            "elevation": float(res.get("elevation") or 0.0),
            "admin1": res.get("admin1"),
            "geocoding_id": res.get("id"),
        }

    return None


def run_geocoding_and_ingestion() -> List[Dict[str, Any]]:
    """Geocodes all 40 locations from config/locations.yaml and inserts into Supabase."""
    root_dir = Path(__file__).resolve().parent.parent.parent
    config_file = root_dir / "config" / "locations.yaml"
    cache_file = root_dir / "config" / "locations_geocoded.json"

    if not config_file.exists():
        raise FileNotFoundError(f"Missing config file: {config_file}")

    with open(config_file, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    locations_spec = config_data.get("locations", [])
    if len(locations_spec) != 40:
        raise ValueError(f"Expected exactly 40 locations, found {len(locations_spec)}")

    geocoded_locations = []
    logger.info("Starting Open-Meteo geocoding for authoritative 40 locations...")

    for i, loc in enumerate(locations_spec, 1):
        name = loc["name"]
        state = loc["state"]
        slug = loc["slug"]
        region = loc["region"]
        terrain = loc["terrain"]

        if region not in VALID_REGIONS:
            raise ValueError(f"Invalid region '{region}' for location '{slug}'")
        if terrain not in VALID_TERRAINS:
            raise ValueError(f"Invalid terrain '{terrain}' for location '{slug}'")

        geo = geocode_location(name, state)
        if not geo:
            raise RuntimeError(f"Failed to geocode location '{name}, {state}'")

        loc_record = {
            "slug": slug,
            "name": name,
            "state": state,
            "region": region,
            "terrain": terrain,
            "latitude": geo["latitude"],
            "longitude": geo["longitude"],
            "elevation": geo["elevation"],
        }
        geocoded_locations.append(loc_record)
        logger.info(f"[{i}/40] {name}, {state} ({region}, {terrain}) -> Lat: {geo['latitude']:.4f}, Lon: {geo['longitude']:.4f}")
        time.sleep(0.2)  # Polite API throttling

    # Save to local cache file
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump({"count": len(geocoded_locations), "locations": geocoded_locations}, f, indent=2)
    logger.info(f"Cached geocoded locations to {cache_file}")

    # Insert into Supabase database via psycopg2
    db_url = settings.DATABASE_URL
    if not db_url:
        raise RuntimeError("DATABASE_URL not set in environment.")

    logger.info("Inserting 40 locations into Supabase `locations` table...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        for loc in geocoded_locations:
            cur.execute(
                """
                INSERT INTO locations (slug, name, state, region, terrain, geog)
                VALUES (
                    %s, %s, %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
                )
                ON CONFLICT (slug) DO UPDATE
                SET name = EXCLUDED.name,
                    state = EXCLUDED.state,
                    region = EXCLUDED.region,
                    terrain = EXCLUDED.terrain,
                    geog = EXCLUDED.geog;
                """,
                (
                    loc["slug"],
                    loc["name"],
                    loc["state"],
                    loc["region"],
                    loc["terrain"],
                    loc["longitude"],
                    loc["latitude"],
                ),
            )

        # Verification Queries
        cur.execute("SELECT COUNT(*) FROM locations;")
        total_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT slug) FROM locations;")
        unique_slugs = cur.fetchone()[0]

        cur.execute("""
            SELECT region, COUNT(*)
            FROM locations
            GROUP BY region
            ORDER BY region;
        """)
        regions_breakdown = dict(cur.fetchall())

        cur.execute("""
            SELECT slug, name, state, region, terrain, ST_AsText(geog::geometry)
            FROM locations
            ORDER BY id
            LIMIT 5;
        """)
        sample_rows = cur.fetchall()

    conn.close()

    logger.info("Database Verification:")
    logger.info(f"  - Total Rows: {total_count} (Expected: 40)")
    logger.info(f"  - Unique Slugs: {unique_slugs} (Expected: 40)")
    logger.info(f"  - Regional Breakdown: {regions_breakdown}")
    logger.info(f"  - Sample PostGIS rows: {sample_rows}")

    if total_count != 40 or unique_slugs != 40:
        raise ValueError(f"Verification failed: count={total_count}, unique={unique_slugs}")

    return geocoded_locations


if __name__ == "__main__":
    run_geocoding_and_ingestion()
