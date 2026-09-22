"""AAGAM Climatology Backfill & Annual Refresh Pipeline (PRD §6.11 FR-CLIMO-1, §7.6).

Computes and backfills climatological percentiles (p90, p95, p99, mean) from truth-only history
for all 40 locations across all 366 days-of-year.
Strictly idempotent using PostgreSQL ON CONFLICT DO UPDATE.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import settings  # noqa: E402
from pipeline.climatology.percentiles import MINIMUM_HISTORY_YEARS, compute_station_climatology  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aagam.pipeline.climatology.backfill")

DEFAULT_TRUTH_PATH = ROOT_DIR / "data" / "truth.parquet"


def run_climatology_backfill(
    truth_source: Optional[Union[pd.DataFrame, Path, str]] = None,
    location_ids: Optional[List[int]] = None,
    min_years: int = MINIMUM_HISTORY_YEARS,
    dry_run: bool = False,
    db_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Executes climatology percentiles calculation and idempotent database upsert.

    Args:
        truth_source: DataFrame or path to Parquet truth observations. Defaults to data/truth.parquet.
        location_ids: Optional list of location IDs to process. Defaults to all present in dataset.
        min_years: Minimum history guard floor (default: 15).
        dry_run: If True, computes records without writing to database.
        db_url: Database connection string.

    Returns:
        Summary dict containing status, rows computed, locations processed, and elapsed duration.
    """
    start_time = time.time()
    logger.info("Starting Climatology Percentiles Backfill / Refresh Pipeline...")

    # 1. Load truth observations
    if truth_source is None:
        truth_path = DEFAULT_TRUTH_PATH
        if not truth_path.exists():
            raise FileNotFoundError(f"Default truth file not found at {truth_path}")
        logger.info(f"Loading truth observations from {truth_path}...")
        df_truth = pd.read_parquet(truth_path)
    elif isinstance(truth_source, (str, Path)):
        truth_path = Path(truth_source)
        if not truth_path.exists():
            raise FileNotFoundError(f"Truth file not found at {truth_path}")
        logger.info(f"Loading truth observations from {truth_path}...")
        df_truth = pd.read_parquet(truth_path)
    elif isinstance(truth_source, pd.DataFrame):
        df_truth = truth_source.copy()
    else:
        raise ValueError(f"Unsupported truth_source type: {type(truth_source)}")

    if df_truth.empty:
        logger.warning("Truth dataset is empty. Nothing to compute.")
        return {
            "status": "EMPTY",
            "records_computed": 0,
            "locations_processed": 0,
            "duration_sec": round(time.time() - start_time, 2),
        }

    # Available locations
    available_locs = sorted(df_truth["location_id"].unique().tolist())
    target_locs = [loc for loc in available_locs if location_ids is None or loc in location_ids]
    logger.info(f"Processing climatology for {len(target_locs)} location(s) (min_years={min_years})...")

    # 2. Compute climatology records for all variables and metrics
    # Dimensions:
    # - rain_mm: 1day, 3day_sum
    # - tmax_c: 1day
    # - wind_max_kmh: 1day
    all_records: List[Dict[str, Any]] = []

    for loc_id in target_locs:
        # a. Rain 1-day
        records_rain_1d = compute_station_climatology(
            df_observations=df_truth,
            location_id=loc_id,
            variable="rain_mm",
            metric="1day",
            value_col="rain_truth" if "rain_truth" in df_truth.columns else "value",
            min_years=min_years,
        )
        all_records.extend(records_rain_1d)

        # b. Rain 3-day sum
        records_rain_3d = compute_station_climatology(
            df_observations=df_truth,
            location_id=loc_id,
            variable="rain_mm",
            metric="3day_sum",
            value_col="rain_truth" if "rain_truth" in df_truth.columns else "value",
            min_years=min_years,
        )
        all_records.extend(records_rain_3d)

        # c. Tmax 1-day
        records_tmax_1d = compute_station_climatology(
            df_observations=df_truth,
            location_id=loc_id,
            variable="tmax_c",
            metric="1day",
            value_col="tmax_truth" if "tmax_truth" in df_truth.columns else "value",
            min_years=min_years,
        )
        all_records.extend(records_tmax_1d)

        # d. Wind 1-day
        records_wind_1d = compute_station_climatology(
            df_observations=df_truth,
            location_id=loc_id,
            variable="wind_max_kmh",
            metric="1day",
            value_col="wind_max_truth" if "wind_max_truth" in df_truth.columns else "value",
            min_years=min_years,
        )
        all_records.extend(records_wind_1d)

    logger.info(f"Computed {len(all_records)} climatology percentile rows across {len(target_locs)} stations.")

    # 3. Write to PostgreSQL if not dry run
    if dry_run:
        logger.info("[DRY RUN] Skipping database upsert.")
    else:
        target_db = db_url or settings.DATABASE_URL
        if not target_db:
            raise ValueError("DATABASE_URL not configured.")

        logger.info(f"Connecting to database to upsert {len(all_records)} records...")
        conn = psycopg2.connect(target_db)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                upsert_sql = """
                    INSERT INTO climatology_percentiles (
                        location_id, variable, metric, doy_window, mean, p90, p95, p99, n_years, computed_at
                    ) VALUES %s
                    ON CONFLICT (location_id, variable, metric, doy_window) DO UPDATE
                    SET mean = EXCLUDED.mean,
                        p90 = EXCLUDED.p90,
                        p95 = EXCLUDED.p95,
                        p99 = EXCLUDED.p99,
                        n_years = EXCLUDED.n_years,
                        computed_at = EXCLUDED.computed_at;
                """
                tuples_to_insert = [
                    (
                        r["location_id"],
                        r["variable"],
                        r["metric"],
                        r["doy_window"],
                        r["mean"],
                        r["p90"],
                        r["p95"],
                        r["p99"],
                        r["n_years"],
                        r["computed_at"],
                    )
                    for r in all_records
                ]
                execute_values(cur, upsert_sql, tuples_to_insert, page_size=2000)
                logger.info(f"Successfully upserted {len(tuples_to_insert)} rows into climatology_percentiles.")
        finally:
            conn.close()

    duration = round(time.time() - start_time, 2)
    logger.info(f"Climatology backfill completed successfully in {duration}s.")
    return {
        "status": "SUCCESS",
        "records_computed": len(all_records),
        "locations_processed": len(target_locs),
        "duration_sec": duration,
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(description="AAGAM Climatology Percentiles Backfill Pipeline")
    parser.add_argument("--truth-path", type=str, default=None, help="Path to Parquet truth dataset")
    parser.add_argument("--min-years", type=int, default=MINIMUM_HISTORY_YEARS, help="Minimum history guard years")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing to database")
    args = parser.parse_args()

    res = run_climatology_backfill(
        truth_source=args.truth_path,
        min_years=args.min_years,
        dry_run=args.dry_run,
    )
    print(res)


if __name__ == "__main__":
    main()
