"""Canary location selection, assignment, and release management (Design Doc §M).

In AAGAM, canary evaluation deploys a candidate version to exactly 5 locations:
- Exactly 1 location per configured meteorological region:
  EAST_NE, SOUTH, CENTRAL, NW, HIMALAYAN.
- Durable assignments are persisted in table `model_version_canary_assignments`.
- For assigned locations, the candidate becomes the serving/displayed version.
- For all other locations, the active model remains the serving version.
- On candidate promotion or rejection/rollback, canary assignments are released.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from psycopg2.extras import execute_values

logger = logging.getLogger("aagam.pipeline.versioning.canary")

REQUIRED_REGIONS = ["EAST_NE", "SOUTH", "CENTRAL", "NW", "HIMALAYAN"]


def select_canary_locations(locations: List[Dict[str, Any]]) -> List[int]:
    """Selects exactly 5 locations spanning all 5 AAGAM meteorological regions.

    Picks the first authoritative location for each required region to guarantee
    consistent, reproducible, and balanced spatial representation.
    """
    selected_location_ids: List[int] = []
    seen_regions: Set[str] = set()

    for region in REQUIRED_REGIONS:
        # Find first location belonging to this region
        matched = False
        for i, loc in enumerate(locations):
            loc_region = loc.get("region")
            if loc_region == region and region not in seen_regions:
                loc_id = int(loc.get("id") or loc.get("location_id") or (i + 1))
                selected_location_ids.append(loc_id)
                seen_regions.add(region)
                matched = True
                break
        if not matched:
            raise ValueError(f"No location found for required meteorological region: {region}")

    if len(selected_location_ids) != 5:
        raise ValueError(
            f"Canary selection must yield exactly 5 locations, got {len(selected_location_ids)}: {selected_location_ids}"
        )

    return selected_location_ids


def assign_canary_locations(
    conn: Any,
    candidate_id: int,
    location_ids: List[int],
    now_dt: Optional[datetime] = None,
) -> int:
    """Inserts durable canary assignments into model_version_canary_assignments.

    Idempotent: skips locations that are already assigned to this version.
    """
    if not location_ids:
        return 0

    now = now_dt or datetime.now(timezone.utc)
    with conn.cursor() as cur:
        # Check existing active assignments for this candidate
        cur.execute(
            """
            SELECT location_id
            FROM model_version_canary_assignments
            WHERE version_id = %s AND released_at IS NULL;
            """,
            (candidate_id,),
        )
        existing = {r[0] for r in cur.fetchall()}

        records = [
            (loc_id, candidate_id, now, None)
            for loc_id in location_ids
            if loc_id not in existing
        ]

        if records:
            query = """
                INSERT INTO model_version_canary_assignments (
                    location_id, version_id, assigned_at, released_at
                ) VALUES %s
                ON CONFLICT (location_id, version_id, assigned_at) DO NOTHING;
            """
            execute_values(cur, query, records)
            logger.info(
                f"Assigned {len(records)} canary locations {location_ids} to version {candidate_id}."
            )
            return len(records)
        return 0


def release_canary_assignments(
    conn: Any,
    candidate_id: int,
    now_dt: Optional[datetime] = None,
) -> int:
    """Releases active canary assignments for a candidate version."""
    now = now_dt or datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE model_version_canary_assignments
            SET released_at = %s
            WHERE version_id = %s AND released_at IS NULL;
            """,
            (now, candidate_id),
        )
        count = cur.rowcount
        if count > 0:
            logger.info(f"Released {count} canary assignments for version {candidate_id}.")
        return count


def get_active_canary_assignments(conn: Any) -> Dict[int, int]:
    """Retrieves current active canary location assignments.

    Returns mapping: {location_id: version_id}.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT location_id, version_id
            FROM model_version_canary_assignments
            WHERE released_at IS NULL;
            """
        )
        rows = cur.fetchall()
        return {r[0]: r[1] for r in rows}
