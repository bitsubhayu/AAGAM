"""Continuous Backfill Runner for AAGAM (FR-DATA-2, FR-DATA-4).

Resumes the Previous Runs backfill from checkpoints until all 1,360 chunks
across all 40 locations are completed. Safely respects Open-Meteo's hourly quota
limits by waiting out rate-limit windows with lightweight probes before resuming.
Once 1,360 chunks are complete, automatically rebuilds and validates
the final training_dataset.parquet.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pipeline.clients.openmeteo import OpenMeteoClient
from pipeline.ingestion.previous_runs import CHECKPOINT_FILE, run_previous_runs_backfill
from pipeline.processing.build_training_dataset import build_joined_training_dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aagam.pipeline.continuous_runner")

TOTAL_TARGET_CHUNKS = 1360


def get_completed_chunks_count() -> int:
    """Reads backfill_state.json and returns completed chunks count."""
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                return len(state.get("completed_chunks", []))
        except Exception:
            return 0
    return 0


def probe_openmeteo_availability() -> bool:
    """Performs a lightweight 1-day probe to check if Open-Meteo rate limit has reset."""
    client = OpenMeteoClient(rate_limit_per_sec=1.0, timeout=15.0)
    try:
        client.fetch_previous_runs(
            latitude=28.6139,
            longitude=77.2090,
            start_date="2024-01-01",
            end_date="2024-01-02",
            models=["gfs_seamless"],
            lead_days=[1],
        )
        return True
    except Exception as e:
        logger.debug(f"Probe not ready yet: {e}")
        return False
    finally:
        client.close()


def run_until_complete() -> None:
    """Runs backfill cycles in a loop until all 1,360 chunks are completed."""
    cycle = 1
    while True:
        completed = get_completed_chunks_count()
        logger.info(
            f"=== CYCLE {cycle}: Current Progress: {completed} / {TOTAL_TARGET_CHUNKS} chunks "
            f"({completed / TOTAL_TARGET_CHUNKS * 100:.1f}%) ==="
        )

        if completed >= TOTAL_TARGET_CHUNKS:
            logger.info("All 1,360 chunks already completed! Proceeding to rebuild training dataset.")
            break

        # Run the backfill
        result = run_previous_runs_backfill()
        status = result.get("status")
        completed = get_completed_chunks_count()

        logger.info(
            f"Cycle {cycle} finished with status={status}. "
            f"Progress: {completed} / {TOTAL_TARGET_CHUNKS} chunks."
        )

        if completed >= TOTAL_TARGET_CHUNKS:
            logger.info("Target of 1,360 chunks achieved!")
            break

        if status == "HALTED_ON_429":
            logger.warning(
                f"Hourly quota reached at {completed} chunks ({datetime.now(timezone.utc).isoformat()}). "
                "Entering wait loop with 5-minute probes until quota window resets..."
            )
            probe_success = False
            wait_intervals = 0
            while not probe_success:
                time.sleep(300)  # Wait 5 minutes
                wait_intervals += 1
                logger.info(
                    f"Checking probe after {wait_intervals * 5} minutes wait "
                    f"({datetime.now(timezone.utc).isoformat()})..."
                )
                if probe_openmeteo_availability():
                    logger.info("Probe SUCCESS! Open-Meteo hourly quota window has reset. Resuming backfill!")
                    probe_success = True
                else:
                    logger.info("Probe still returning 429/error. Continuing to wait 5 more minutes...")

        cycle += 1

    # Rebuild final training dataset
    logger.info("============================================================")
    logger.info("REBUILDING FINAL TRAINING DATASET (PRD §7.3)")
    logger.info("============================================================")
    build_joined_training_dataset()
    logger.info("Final training dataset successfully generated and verified!")


if __name__ == "__main__":
    run_until_complete()
