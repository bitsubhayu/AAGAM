"""AAGAM — Model Version Rollback Drill Script (Phase 9 Hardening).

Validates zero-downtime model rollback and activation (PRD §12, FR-OPS-1, FR-OPS-2):
1. Connects to database and checks current active model version.
2. Rolls back to prior model version (id 1) via the admin activation handler.
3. Verifies atomic database state (unique partial index `one_active_version`).
4. Verifies cache invalidation in `api.app.db.model_versions`.
5. Restores original active model version (id 2).
6. Verifies clean restoration and cache invalidation.
7. Outputs structured audit results.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.app.auth.dependencies import CurrentUser
from api.app.db.model_versions import get_active_model_version_cached
from api.app.db.pool import db_pool
from api.app.routers.models import activate_model_version

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("aagam.drill.rollback")


async def run_model_rollback_drill() -> Dict[str, Any]:
    """Executes the zero-downtime model rollback and restoration drill."""
    drill_start = time.perf_counter()

    # Initialize connection pool
    logger.info("Initializing asyncpg connection pool...")
    await db_pool.init_pool()

    coord_user = CurrentUser(user_id="00000000-0000-0000-0000-000000000003", email="coordinator@aagam.gov.in", role="coordinator")

    try:
        assert db_pool.pool is not None, "Failed to initialize db pool"
        async with db_pool.pool.acquire() as conn:
            # 1. Inspect initial active version
            initial_active = await conn.fetchrow(
                "SELECT id, storage_path, is_active FROM model_versions WHERE is_active = true"
            )
            assert initial_active is not None, "No active model version found in database!"
            initial_id = initial_active["id"]
            logger.info(f"Initial active model version: ID={initial_id}, storage_path={initial_active['storage_path']}")

            # Verify target rollback version exists
            target_rollback_id = 1 if initial_id != 1 else 2
            target_exists = await conn.fetchrow("SELECT id FROM model_versions WHERE id = $1", target_rollback_id)
            assert target_exists is not None, f"Target rollback version ID={target_rollback_id} does not exist!"

            # 2. Execute Rollback to target_rollback_id
            logger.info(f"Executing rollback: Activating model version ID={target_rollback_id}...")
            rollback_start = time.perf_counter()
            rollback_resp = await activate_model_version(id=target_rollback_id, current_user=coord_user, conn=conn)
            rollback_duration_ms = (time.perf_counter() - rollback_start) * 1000
            logger.info(f"Rollback executed in {rollback_duration_ms:.2f}ms. Response: ID={rollback_resp.id}, is_active={rollback_resp.is_active}")

            # 3. Verify database state
            active_count = await conn.fetchval("SELECT COUNT(*) FROM model_versions WHERE is_active = true")
            assert active_count == 1, f"Expected exactly 1 active version, got {active_count}"
            current_active = await conn.fetchval("SELECT id FROM model_versions WHERE is_active = true")
            assert current_active == target_rollback_id, f"Expected active ID={target_rollback_id}, got {current_active}"

            # 4. Verify cache invalidation
            cached_version = await get_active_model_version_cached(conn)
            assert cached_version["id"] == target_rollback_id, f"Cache not invalidated! Cached ID={cached_version['id']}"
            logger.info(f"Cache invalidation verified: cached active version is {cached_version['version_str']} (ID={cached_version['id']})")

            # 5. Restore original active version
            logger.info(f"Restoring original active version ID={initial_id}...")
            restore_start = time.perf_counter()
            restore_resp = await activate_model_version(id=initial_id, current_user=coord_user, conn=conn)
            restore_duration_ms = (time.perf_counter() - restore_start) * 1000
            logger.info(f"Restoration executed in {restore_duration_ms:.2f}ms. Response: ID={restore_resp.id}, is_active={restore_resp.is_active}")

            # 6. Verify restored database state & cache
            restored_active_count = await conn.fetchval("SELECT COUNT(*) FROM model_versions WHERE is_active = true")
            assert restored_active_count == 1, f"Expected exactly 1 active version, got {restored_active_count}"
            restored_active_id = await conn.fetchval("SELECT id FROM model_versions WHERE is_active = true")
            assert restored_active_id == initial_id, f"Expected active ID={initial_id}, got {restored_active_id}"

            cached_restored = await get_active_model_version_cached(conn)
            assert cached_restored["id"] == initial_id, f"Cache not restored! Cached ID={cached_restored['id']}"
            logger.info(f"Restoration verified: cached active version restored to {cached_restored['version_str']} (ID={cached_restored['id']})")

        total_drill_duration_ms = (time.perf_counter() - drill_start) * 1000

        result = {
            "status": "PASS",
            "initial_version_id": initial_id,
            "rollback_version_id": target_rollback_id,
            "restored_version_id": initial_id,
            "rollback_duration_ms": round(rollback_duration_ms, 2),
            "restore_duration_ms": round(restore_duration_ms, 2),
            "total_drill_time_ms": round(total_drill_duration_ms, 2),
            "single_active_constraint_verified": True,
            "cache_invalidation_verified": True,
        }
        return result

    finally:
        await db_pool.close_pool()


if __name__ == "__main__":
    try:
        report = asyncio.run(run_model_rollback_drill())
        print("\n=== AAGAM MODEL ROLLBACK DRILL RESULT ===")
        for k, v in report.items():
            print(f"  {k}: {v}")
        print("=========================================\n")
    except Exception:
        logger.exception("Model rollback drill failed")
        sys.exit(1)
