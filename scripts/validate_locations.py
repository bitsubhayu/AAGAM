"""AAGAM — 40 Locations Validation Script.

Strictly validates:
1. Exactly 40 locations
2. Zero duplicate slugs
3. Zero duplicate (name, state) pairs
4. Exactly the 5 required region groups: EAST_NE, SOUTH, CENTRAL, NW, HIMALAYAN
5. Valid terrain values: plains, coastal, hills
6. Every location has name, state, region, terrain
7. No invented coordinates in Phase 0
"""
import sys
from pathlib import Path

import yaml

REQUIRED_REGIONS = {"EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"}
VALID_TERRAINS = {"plains", "coastal", "hills"}

def validate_locations():
    config_path = Path(__file__).resolve().parent.parent / "config" / "locations.yaml"
    if not config_path.exists():
        print(f"FAIL: {config_path} does not exist!")
        return False, []

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    locations = data.get("locations", [])
    errors = []

    # 1. Count == 40
    if len(locations) != 40:
        errors.append(f"Expected exactly 40 locations, found {len(locations)}")

    slugs = set()
    city_states = set()
    found_regions = set()
    region_counts = {r: 0 for r in REQUIRED_REGIONS}

    validated_list = []

    for idx, loc in enumerate(locations, 1):
        slug = loc.get("slug")
        name = loc.get("name")
        state = loc.get("state")
        region = loc.get("region")
        terrain = loc.get("terrain")

        # Check required fields
        if not all([slug, name, state, region, terrain]):
            errors.append(f"Row {idx} is missing required fields: {loc}")
            continue

        # Check duplicate slugs
        if slug in slugs:
            errors.append(f"Duplicate slug found: '{slug}'")
        slugs.add(slug)

        # Check duplicate city/state
        pair = (name.lower(), state.lower())
        if pair in city_states:
            errors.append(f"Duplicate city/state pair: '{name}, {state}'")
        city_states.add(pair)

        # Check region
        if region not in REQUIRED_REGIONS:
            errors.append(f"Invalid region '{region}' in {name}. Must be one of {REQUIRED_REGIONS}")
        else:
            found_regions.add(region)
            region_counts[region] += 1

        # Check terrain
        if terrain not in VALID_TERRAINS:
            errors.append(f"Invalid terrain '{terrain}' in {name}. Must be one of {VALID_TERRAINS}")

        # Check for uncalled geocoding in Phase 0 (PRD states coordinates are Phase 1 geocoded)
        if "latitude" in loc or "longitude" in loc:
            errors.append(f"Location '{name}' contains coordinates in Phase 0. Phase 0 must not invent coordinates.")

        validated_list.append({
            "index": idx,
            "name": name,
            "state": state,
            "region": region,
            "terrain": terrain,
            "slug": slug
        })

    # Check that all 5 regions are represented
    missing_regions = REQUIRED_REGIONS - found_regions
    if missing_regions:
        errors.append(f"Missing required regions: {missing_regions}")

    # Expected breakdown: EAST_NE=10, SOUTH=8, CENTRAL=7, NW=9, HIMALAYAN=6
    expected_breakdown = {"EAST_NE": 10, "SOUTH": 8, "CENTRAL": 7, "NW": 9, "HIMALAYAN": 6}
    for r, exp in expected_breakdown.items():
        if region_counts.get(r, 0) != exp:
            errors.append(f"Region '{r}': expected {exp} locations, found {region_counts.get(r, 0)}")

    if errors:
        print("VALIDATION FAILED:")
        for err in errors:
            print(f"  - {err}")
        return False, []

    print("PASS: config/locations.yaml is 100% VALID.")
    print(f"Total Locations: {len(locations)}")
    print(f"Regional Breakdown: {region_counts}")
    return True, validated_list

if __name__ == "__main__":
    ok, locs = validate_locations()
    if ok:
        print("\nFull Validated 40 Locations List:")
        print(f"{'No.':<4} {'City, State':<32} {'Region':<12} {'Terrain':<10} {'Slug':<15}")
        print("-" * 75)
        for item in locs:
            cs = f"{item['name']}, {item['state']}"
            print(f"{item['index']:<4} {cs:<32} {item['region']:<12} {item['terrain']:<10} {item['slug']:<15}")
        sys.exit(0)
    else:
        sys.exit(1)
