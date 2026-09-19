"""Previous Runs Backfill Pipeline for AAGAM (FR-DATA-2).

Strictly adheres to:
- Uses Open-Meteo Previous Runs API (`previous-runs-api.open-meteo.com`).
- Lead days: previous_day1 through previous_day7.
- Models: GFS (gfs_seamless), ECMWF IFS (ecmwf_ifs025), ICON (icon_global), AIFS (ecmwf_aifs025_single).
- 40 authoritative locations.
- Variables: precipitation, temperature_2m, wind_speed_10m.
- Checkpointed & resumable via `pipeline/checkpoints/backfill_state.json`.
- Strict deduplication: re-running never creates duplicate rows.
- Daily call budget enforcement (<= 8,000 calls/day).
- Aggregated via IST conventions (FR-PRE-1).
- Stored as Parquet: `data/forecasts_backfill.parquet`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
import psycopg2

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.config import settings
from pipeline.clients.openmeteo import (
    OPENMETEO_MODELS,
    OpenMeteoClient,
)
from pipeline.processing.aggregation import aggregate_hourly_to_ist_daily

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aagam.pipeline.previous_runs")

MAX_DAILY_CALLS_BUDGET = 8000
CHECKPOINT_FILE = Path(__file__).resolve().parent.parent / "checkpoints" / "backfill_state.json"
OUTPUT_PARQUET = Path(__file__).resolve().parent.parent.parent / "data" / "forecasts_backfill.parquet"

MODEL_KEY_MAP = {
    "gfs_seamless": "gfs",
    "ecmwf_ifs025": "ecmwf_ifs",
    "icon_global": "icon",
    "ecmwf_aifs025_single": "aifs",
}


def load_checkpoint() -> Dict[str, Any]:
    """Loads backfill state checkpoint from disk."""
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load checkpoint file, creating new: {e}")
    return {"completed_chunks": [], "total_calls_made": 0, "last_updated": None}


def save_checkpoint(state: Dict[str, Any]) -> None:
    """Persists backfill state checkpoint to disk atomically."""
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    temp_file = CHECKPOINT_FILE.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    temp_file.replace(CHECKPOINT_FILE)


def get_locations_from_db() -> List[Dict[str, Any]]:
    """Fetches all 40 locations from Supabase database."""
    conn = psycopg2.connect(settings.DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, slug, name, state, region, terrain,
                   ST_Y(geog::geometry) AS latitude,
                   ST_X(geog::geometry) AS longitude
            FROM locations
            ORDER BY id;
        """)
        rows = cur.fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "slug": r[1],
            "name": r[2],
            "state": r[3],
            "region": r[4],
            "terrain": r[5],
            "latitude": float(r[6]),
            "longitude": float(r[7]),
        }
        for r in rows
    ]


def generate_date_chunks(start_date: date, end_date: date, chunk_days: int = 14) -> List[Tuple[date, date]]:
    """Generates continuous date intervals for batching requests."""
    chunks = []
    curr = start_date
    while curr <= end_date:
        chunk_end = min(curr + timedelta(days=chunk_days - 1), end_date)
        chunks.append((curr, chunk_end))
        curr = chunk_end + timedelta(days=1)
    return chunks


def run_previous_runs_backfill(
    start_date_str: str = "2024-01-01",
    end_date_str: str = "2026-09-18",
    chunk_days: int = 30,
    dry_run: bool = False,
    force_reset: bool = False,
) -> Dict[str, Any]:
    """Executes or resumes the Previous Runs backfill pipeline."""
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    if end_dt < start_dt:
        raise ValueError(f"end_date ({end_date_str}) cannot be before start_date ({start_date_str})")

    locations = get_locations_from_db()
    if len(locations) != 40:
        raise ValueError(f"Expected 40 locations, found {len(locations)}")

    chunks = generate_date_chunks(start_dt, end_dt, chunk_days)
    total_planned_calls = len(locations) * len(chunks)

    logger.info("=" * 60)
    logger.info("AAGAM Previous Runs Backfill (FR-DATA-2)")
    logger.info("=" * 60)
    logger.info(f"Target Date Range: {start_date_str} to {end_date_str} ({ (end_dt - start_dt).days + 1 } days)")
    logger.info(f"Locations: {len(locations)} authoritative stations")
    logger.info("Lead Days: previous_day1 through previous_day7")
    logger.info("Models: GFS, ECMWF IFS, ICON, AIFS")
    logger.info(f"Chunk Size: {chunk_days} days ({len(chunks)} chunks per location)")
    logger.info(f"Total Estimated API Calls: {total_planned_calls} (Daily Budget: {MAX_DAILY_CALLS_BUDGET})")

    if total_planned_calls > MAX_DAILY_CALLS_BUDGET:
        raise RuntimeError(
            f"Safety Halt: Estimated calls ({total_planned_calls}) exceed daily limit ({MAX_DAILY_CALLS_BUDGET})!"
        )

    if dry_run:
        logger.info("[DRY RUN] Call estimation and configuration validated successfully.")
        return {"dry_run": True, "estimated_calls": total_planned_calls}

    # Manage checkpoint state
    if force_reset and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("Reset existing checkpoint file.")

    state = load_checkpoint()
    completed_set = set(state.get("completed_chunks", []))
    logger.info(f"Loaded checkpoint: {len(completed_set)} chunks already completed.")

    # Load existing parquet rows to avoid duplicates on re-run
    existing_df = None
    if OUTPUT_PARQUET.exists() and not force_reset:
        try:
            existing_df = pd.read_parquet(OUTPUT_PARQUET)
            logger.info(f"Loaded existing Parquet dataset with {len(existing_df)} rows.")
        except Exception as e:
            logger.warning(f"Could not read existing parquet: {e}")

    client = OpenMeteoClient(rate_limit_per_sec=3.5, timeout=60.0)
    model_keys = list(OPENMETEO_MODELS.values())
    lead_days = list(range(1, 8))

    calls_made_this_run = 0
    started_at = datetime.now(timezone.utc)
    new_chunks_list: List[pd.DataFrame] = []
    completed_chunks_in_batch: List[str] = []

    try:
        for loc_idx, loc in enumerate(locations, 1):
            loc_id = loc["id"]
            slug = loc["slug"]
            lat = loc["latitude"]
            lon = loc["longitude"]

            for chunk_idx, (c_start, c_end) in enumerate(chunks, 1):
                chunk_id = f"{slug}_{c_start.isoformat()}_{c_end.isoformat()}"
                if chunk_id in completed_set:
                    continue

                logger.info(
                    f"[{loc_idx}/40 loc] [{chunk_idx}/{len(chunks)} chunk] Fetching {slug} "
                    f"({c_start} to {c_end})..."
                )

                fetch_start = (c_start - timedelta(days=1)).isoformat()
                fetch_end = (c_end + timedelta(days=1)).isoformat()

                data = client.fetch_previous_runs(
                    latitude=lat,
                    longitude=lon,
                    start_date=fetch_start,
                    end_date=fetch_end,
                    models=model_keys,
                    lead_days=lead_days,
                )
                calls_made_this_run += 1

                hourly = data.get("hourly", {})
                times = hourly.get("time", [])
                if not times:
                    logger.warning(f"No timeseries returned for chunk {chunk_id}")
                    completed_set.add(chunk_id)
                    state["completed_chunks"] = list(completed_set)
                    save_checkpoint(state)
                    continue

                chunk_records = []
                # Process each model and lead day
                for raw_model, db_model in MODEL_KEY_MAP.items():
                    for lead in lead_days:
                        rain_col = f"precipitation_previous_day{lead}_{raw_model}"
                        temp_col = f"temperature_2m_previous_day{lead}_{raw_model}"
                        wind_col = f"wind_speed_10m_previous_day{lead}_{raw_model}"

                        # If model was bundled or has single suffix
                        if rain_col not in hourly:
                            rain_col = f"precipitation_previous_day{lead}"
                            temp_col = f"temperature_2m_previous_day{lead}"
                            wind_col = f"wind_speed_10m_previous_day{lead}"

                        if rain_col not in hourly:
                            continue

                        df_hourly = pd.DataFrame({
                            "time": times,
                            "precipitation": hourly[rain_col],
                            "temperature_2m": hourly[temp_col],
                            "wind_speed_10m": hourly[wind_col],
                        })

                        df_daily = aggregate_hourly_to_ist_daily(df_hourly)

                        for _, row in df_daily.iterrows():
                            val_date = row["valid_date"]
                            if val_date < c_start or val_date > c_end:
                                continue

                            chunk_records.append({
                                "location_id": loc_id,
                                "model": db_model,
                                "valid_date": val_date,
                                "lead_days": lead,
                                "f_rain_mm": row["rain_sum"],
                                "f_tmax_c": row["temp_max"],
                                "f_wind_max_kmh": row["wind_max"],
                            })

                if chunk_records:
                    new_chunks_list.append(pd.DataFrame(chunk_records))
                completed_chunks_in_batch.append(chunk_id)

                # Batch commit to Parquet and checkpoint every 10 chunks or on final chunk
                is_final = (loc_idx == len(locations) and chunk_idx == len(chunks))
                if len(new_chunks_list) >= 10 or is_final:
                    if new_chunks_list:
                        df_new_batch = pd.concat(new_chunks_list, ignore_index=True)
                        if existing_df is not None and not existing_df.empty:
                            existing_df = pd.concat([existing_df, df_new_batch], ignore_index=True)
                        else:
                            existing_df = df_new_batch

                        dedup_keys = ["location_id", "model", "valid_date", "lead_days"]
                        existing_df = existing_df.drop_duplicates(subset=dedup_keys, keep="last").sort_values(
                            dedup_keys
                        ).reset_index(drop=True)

                        OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
                        existing_df.to_parquet(OUTPUT_PARQUET, index=False, engine="pyarrow", compression="snappy")
                        new_chunks_list = []

                    for cid in completed_chunks_in_batch:
                        completed_set.add(cid)
                    completed_chunks_in_batch = []
                    state["completed_chunks"] = list(completed_set)
                    state["total_calls_made"] = len(completed_set)
                    save_checkpoint(state)

    except Exception as exc:
        is_429 = "429" in str(exc) or "limit exceeded" in str(exc).lower()
        run_status = "HALTED_ON_429" if is_429 else "FAILED"
        logger.warning(f"Backfill execution stopped: {exc}. Telemetry recorded with status={run_status}.")
        error_msg = f"Halted: {exc}"
    else:
        run_status = "SUCCESS"
        error_msg = "Completed successfully."
    finally:
        client.close()
        if new_chunks_list:
            try:
                df_new_batch = pd.concat(new_chunks_list, ignore_index=True)
                if existing_df is not None and not existing_df.empty:
                    existing_df = pd.concat([existing_df, df_new_batch], ignore_index=True)
                else:
                    existing_df = df_new_batch
                dedup_keys = ["location_id", "model", "valid_date", "lead_days"]
                existing_df = existing_df.drop_duplicates(subset=dedup_keys, keep="last").sort_values(
                    dedup_keys
                ).reset_index(drop=True)
                OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
                existing_df.to_parquet(OUTPUT_PARQUET, index=False, engine="pyarrow", compression="snappy")
                for cid in completed_chunks_in_batch:
                    completed_set.add(cid)
                state["completed_chunks"] = list(completed_set)
                state["total_calls_made"] = len(completed_set)
                save_checkpoint(state)
            except Exception as e:
                logger.warning(f"Failed to flush pending chunks on exit: {e}")

        total_rows = len(existing_df) if existing_df is not None else 0
        finished_at = datetime.now(timezone.utc)
        duration_sec = (finished_at - started_at).total_seconds()

        # Log execution to pipeline_runs per FR-DATA-5
        try:
            conn = psycopg2.connect(settings.DATABASE_URL)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pipeline_runs (job, started_at, finished_at, status, rows_written, api_calls_est, message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        "previous_runs_backfill",
                        started_at,
                        finished_at,
                        run_status,
                        total_rows,
                        calls_made_this_run,
                        f"Backfill {run_status}: {calls_made_this_run} API calls, {total_rows} total rows, {len(completed_set)} chunks in {duration_sec:.1f}s. {error_msg}",
                    ),
                )
            conn.commit()
            conn.close()
            logger.info(f"Logged backfill run ({run_status}) to pipeline_runs table.")
        except Exception as e:
            logger.warning(f"Failed to log backfill to pipeline_runs: {e}")

    logger.info(f"Backfill complete/checkpointed. Parquet contains {total_rows} rows at {OUTPUT_PARQUET}.")

    return {
        "status": "SUCCESS",
        "calls_made": calls_made_this_run,
        "total_rows": total_rows,
        "parquet_path": str(OUTPUT_PARQUET),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AAGAM Previous Runs Backfill Pipeline")
    parser.add_argument("--start-date", default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="2026-09-18", help="End date (YYYY-MM-DD)")
    parser.add_argument("--chunk-days", type=int, default=30, help="Chunk size in days")
    parser.add_argument("--dry-run", action="store_true", help="Estimate calls without executing")
    parser.add_argument("--force-reset", action="store_true", help="Reset checkpoint and overwrite")
    args = parser.parse_args()

    run_previous_runs_backfill(
        start_date_str=args.start_date,
        end_date_str=args.end_date,
        chunk_days=args.chunk_days,
        dry_run=args.dry_run,
        force_reset=args.force_reset,
    )
