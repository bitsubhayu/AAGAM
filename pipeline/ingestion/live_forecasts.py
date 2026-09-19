"""Live Forecast Ingestion for AAGAM (FR-DATA-1).

Ingests live forecasts for:
- 4 models: GFS, ECMWF IFS, ICON, AIFS
- 40 locations
- 3 variables: precipitation (rain_mm), temperature_2m (tmax_c), wind_speed_10m (wind_max_kmh)
- 8 forecast days horizon
- IST aggregation (FR-PRE-1)
- Upsert into Supabase `model_forecasts`
- Run logging into `pipeline_runs`
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.config import settings
from pipeline.clients.openmeteo import (
    OPENMETEO_MODELS,
    OpenMeteoClient,
)
from pipeline.processing.aggregation import aggregate_hourly_to_ist_daily

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aagam.pipeline.live_forecasts")

MODEL_KEY_MAP = {
    "gfs_seamless": "gfs",
    "ecmwf_ifs025": "ecmwf_ifs",
    "icon_global": "icon",
    "ecmwf_aifs025_single": "aifs",
}


def get_locations_from_db() -> List[Dict[str, Any]]:
    """Retrieves all 40 locations with latitude and longitude from Supabase."""
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

    locations = []
    for r in rows:
        locations.append({
            "id": r[0],
            "slug": r[1],
            "name": r[2],
            "state": r[3],
            "region": r[4],
            "terrain": r[5],
            "latitude": float(r[6]),
            "longitude": float(r[7]),
        })
    return locations


def run_live_forecast_ingestion() -> Dict[str, Any]:
    """Executes live forecast fetch, aggregation, upsert, and run tracking."""
    started_at = datetime.now(timezone.utc)
    issue_date = started_at.date()

    locations = get_locations_from_db()
    if len(locations) != 40:
        raise ValueError(f"Expected 40 locations in Supabase, found {len(locations)}")

    client = OpenMeteoClient(rate_limit_per_sec=4.0)
    api_calls_est = client.estimate_calls(num_locations=len(locations), num_models=4, num_batches=1)

    all_forecast_records: List[Tuple[Any, ...]] = []
    model_keys = list(OPENMETEO_MODELS.values())

    logger.info(f"Starting live forecast ingestion for {len(locations)} locations...")

    for i, loc in enumerate(locations, 1):
        loc_id = loc["id"]
        slug = loc["slug"]
        lat = loc["latitude"]
        lon = loc["longitude"]

        logger.info(f"[{i}/40] Fetching live 8-day forecast for {loc['name']} ({lat:.4f}, {lon:.4f})...")
        data = client.fetch_live_forecast(
            latitude=lat,
            longitude=lon,
            models=model_keys,
            forecast_days=10,
        )

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            logger.warning(f"No hourly data returned for {slug}")
            continue

        # Each model has its own columns in hourly
        for raw_model, db_model in MODEL_KEY_MAP.items():
            rain_col = f"precipitation_{raw_model}"
            temp_col = f"temperature_2m_{raw_model}"
            wind_col = f"wind_speed_10m_{raw_model}"

            if rain_col not in hourly or temp_col not in hourly or wind_col not in hourly:
                logger.warning(f"Columns for {raw_model} missing in response for {slug}")
                continue

            df_model_hourly = pd.DataFrame({
                "time": times,
                "precipitation": hourly[rain_col],
                "temperature_2m": hourly[temp_col],
                "wind_speed_10m": hourly[wind_col],
            })

            df_daily = aggregate_hourly_to_ist_daily(df_model_hourly)

            for _, row in df_daily.iterrows():
                val_date = row["valid_date"]
                lead_days = (val_date - issue_date).days
                if lead_days < 0 or lead_days > 10:
                    continue

                # Add 3 variables: rain_mm, tmax_c, wind_max_kmh
                if pd.notna(row["rain_sum"]):
                    all_forecast_records.append((
                        loc_id, db_model, "rain_mm", val_date, lead_days, started_at, float(row["rain_sum"])
                    ))
                if pd.notna(row["temp_max"]):
                    all_forecast_records.append((
                        loc_id, db_model, "tmax_c", val_date, lead_days, started_at, float(row["temp_max"])
                    ))
                if pd.notna(row["wind_max"]):
                    all_forecast_records.append((
                        loc_id, db_model, "wind_max_kmh", val_date, lead_days, started_at, float(row["wind_max"])
                    ))

    client.close()
    logger.info(f"Generated {len(all_forecast_records)} aggregated daily forecast rows.")

    # Upsert into Supabase model_forecasts
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        logger.info("Upserting records into Supabase `model_forecasts`...")
        upsert_query = """
            INSERT INTO model_forecasts (
                location_id, model, variable, valid_date, lead_days, issue_time, value
            ) VALUES %s
            ON CONFLICT (location_id, model, variable, valid_date) DO UPDATE
            SET lead_days = EXCLUDED.lead_days,
                issue_time = EXCLUDED.issue_time,
                value = EXCLUDED.value;
        """
        execute_values(cur, upsert_query, all_forecast_records, page_size=1000)

        # Verification
        cur.execute("SELECT COUNT(*) FROM model_forecasts;")
        total_rows_db = cur.fetchone()[0]

        cur.execute("""
            SELECT model, COUNT(*)
            FROM model_forecasts
            GROUP BY model
            ORDER BY model;
        """)
        model_counts = dict(cur.fetchall())

        cur.execute("""
            SELECT variable, COUNT(*)
            FROM model_forecasts
            GROUP BY variable
            ORDER BY variable;
        """)
        variable_counts = dict(cur.fetchall())

        cur.execute("SELECT MIN(valid_date), MAX(valid_date) FROM model_forecasts;")
        min_date, max_date = cur.fetchone()

        finished_at = datetime.now(timezone.utc)
        duration_sec = (finished_at - started_at).total_seconds()

        # Log run in pipeline_runs
        cur.execute(
            """
            INSERT INTO pipeline_runs (job, started_at, finished_at, status, rows_written, api_calls_est, message)
            VALUES (%s, %s, %s, %s, %s, %s, %s);
            """,
            (
                "live_forecast_ingestion",
                started_at,
                finished_at,
                "SUCCESS",
                len(all_forecast_records),
                api_calls_est,
                f"Ingested {len(all_forecast_records)} rows across 40 locations and 4 models in {duration_sec:.1f}s. Date range: {min_date} to {max_date}.",
            ),
        )

    conn.close()

    logger.info("Live Forecast Ingestion Summary:")
    logger.info(f"  - Rows Written: {len(all_forecast_records)}")
    logger.info(f"  - Total in DB: {total_rows_db}")
    logger.info(f"  - Models: {model_counts}")
    logger.info(f"  - Variables: {variable_counts}")
    logger.info(f"  - Valid Date Range: {min_date} to {max_date}")
    logger.info(f"  - Duration: {duration_sec:.1f} seconds")

    return {
        "status": "SUCCESS",
        "rows_written": len(all_forecast_records),
        "total_rows_db": total_rows_db,
        "model_counts": model_counts,
        "variable_counts": variable_counts,
        "date_range": (str(min_date), str(max_date)),
        "duration_seconds": duration_sec,
    }


if __name__ == "__main__":
    run_live_forecast_ingestion()
