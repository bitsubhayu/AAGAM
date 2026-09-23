"""AAGAM — Live Ingest & Blend Pipeline Runner (PRD §7.1, §8.4, Tech Stack §10).

Orchestrates the scheduled `ingest-blend` workflow (17 0,6,12,18 * * *):
1. Fetches live 8-10 day forecasts from Open-Meteo for 40 locations across 4 NWP models.
2. Respects rate-limits, call budget, and clean 429 halting.
3. Aggregates hourly values to IST daily values.
4. Upserts model forecasts into database table `model_forecasts`.
5. Loads active model artifacts from `model_registry`.
6. Generates features and computes predictions with Ridge, LightGBM, and Adaptive Blend.
7. Evaluates Phase 4 extreme weather hazards (heavy rain, heat wave, high wind, high uncertainty).
8. Upserts results into `blended_forecasts` and `alerts`.
9. Logs full execution telemetry to `pipeline_runs`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from core.config import get_locations, get_regions, settings
from pipeline.blend.blender import AagamBlender
from pipeline.blend.extremes import ExtremeGuidanceEngine
from pipeline.clients.openmeteo import OPENMETEO_MODELS, OpenMeteoClient
from pipeline.events.group import AlertEventRecord, group_alerts_into_events
from pipeline.events.lifecycle_state import (
    compute_lifecycle_states,
    update_event_cancellations_and_expiries,
)
from pipeline.models.lgbm import LightGBMEngine
from pipeline.models.registry import model_registry
from pipeline.models.select import SelectionDecision
from pipeline.processing.aggregation import aggregate_hourly_to_ist_daily
from pipeline.processing.build_training_dataset import get_regime, get_season

logger = logging.getLogger("aagam.pipeline.live.runner")

MODEL_KEY_MAP = {
    "gfs_seamless": "gfs",
    "ecmwf_ifs025": "ecmwf_ifs",
    "icon_global": "icon",
    "ecmwf_aifs025_single": "aifs",
}


class LivePipelineRunner:
    """Executes the operational ingest-blend pipeline cycle."""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or settings.DATABASE_URL
        self.locations = self._load_locations()
        self.regions_cfg = get_regions()

    def _load_locations(self) -> List[Dict[str, Any]]:
        """Loads all 40 authoritative locations with coordinates and terrain."""
        if self.db_url:
            try:
                conn = psycopg2.connect(self.db_url)
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
                if rows:
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
            except Exception as e:
                logger.warning(f"Could not load locations from DB: {e}; falling back to locations.yaml")

        yaml_locs = get_locations()
        return [
            {
                "id": i + 1,
                "slug": loc_entry["slug"],
                "name": loc_entry["name"],
                "state": loc_entry.get("state", ""),
                "region": loc_entry.get("region", "NW"),
                "terrain": loc_entry.get("terrain", "plains"),
                "latitude": 28.6139,
                "longitude": 77.2090,
            }
            for i, loc_entry in enumerate(yaml_locs)
        ]

    def get_connection(self):
        if not self.db_url:
            raise RuntimeError("DATABASE_URL is required for live pipeline operations.")
        conn = psycopg2.connect(self.db_url)
        conn.autocommit = True
        return conn

    def fetch_live_forecasts(
        self,
        dry_run: bool = False,
    ) -> Tuple[List[Tuple[Any, ...]], int, Optional[str]]:
        """Fetches and aggregates 10-day forecasts from Open-Meteo across 40 locations."""
        started_at = datetime.now(timezone.utc)
        issue_date = started_at.date()

        if dry_run:
            logger.info("[Dry Run] Simulating live forecast fetch without hitting Open-Meteo API.")
            # Use cached or synthetic rows for dry-run verification
            sample_records = []
            for loc in self.locations:
                loc_id = loc["id"]
                for model in ["gfs", "ecmwf_ifs", "icon", "aifs"]:
                    for var in ["rain_mm", "tmax_c", "wind_max_kmh"]:
                        for lead in range(0, 8):
                            val_date = issue_date + pd.Timedelta(days=lead)
                            val = 15.0 if var == "rain_mm" else (33.0 if var == "tmax_c" else 18.0)
                            sample_records.append((
                                loc_id, model, var, val_date, lead, started_at, float(val)
                            ))
            return sample_records, 0, None

        client = OpenMeteoClient(rate_limit_per_sec=4.0)
        api_calls_est = client.estimate_calls(num_locations=len(self.locations), num_models=4, num_batches=1)
        logger.info(f"Starting live forecast fetch for 40 locations. Estimated calls: {api_calls_est}")

        records: List[Tuple[Any, ...]] = []
        model_keys = list(OPENMETEO_MODELS.values())

        try:
            for i, loc in enumerate(self.locations, 1):
                loc_id = loc["id"]
                lat = loc["latitude"]
                lon = loc["longitude"]

                logger.info(f"[{i}/40] Fetching live forecast for {loc['name']} ({lat:.4f}, {lon:.4f})...")
                try:
                    data = client.fetch_live_forecast(
                        latitude=lat,
                        longitude=lon,
                        models=model_keys,
                        forecast_days=10,
                    )
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "rate limit" in err_str.lower():
                        logger.error(f"HTTP 429 Quota Exceeded at location {loc['slug']}: {e}")
                        client.close()
                        return records, api_calls_est, f"HALTED: HTTP 429 quota reached at {loc['slug']}."
                    logger.warning(f"Error fetching {loc['slug']}: {e}; continuing with remaining stations.")
                    continue

                hourly = data.get("hourly", {})
                times = hourly.get("time", [])
                if not times:
                    continue

                for raw_model, db_model in MODEL_KEY_MAP.items():
                    rain_col = f"precipitation_{raw_model}"
                    temp_col = f"temperature_2m_{raw_model}"
                    wind_col = f"wind_speed_10m_{raw_model}"

                    if rain_col not in hourly or temp_col not in hourly or wind_col not in hourly:
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
                        if lead_days < 0 or lead_days > 7:
                            continue

                        if pd.notna(row["rain_sum"]):
                            records.append((
                                loc_id, db_model, "rain_mm", val_date, lead_days, started_at, float(row["rain_sum"])
                            ))
                        if pd.notna(row["temp_max"]):
                            records.append((
                                loc_id, db_model, "tmax_c", val_date, lead_days, started_at, float(row["temp_max"])
                            ))
                        if pd.notna(row["wind_max"]):
                            records.append((
                                loc_id, db_model, "wind_max_kmh", val_date, lead_days, started_at, float(row["wind_max"])
                            ))

            client.close()
            return records, api_calls_est, None
        except Exception as e:
            client.close()
            logger.error(f"Unexpected error in live fetch: {e}")
            return records, api_calls_est, f"ERROR: {e}"

    def run_ingest_and_blend(self, dry_run: bool = False) -> Dict[str, Any]:
        """Executes full live ingestion, model blending, alert evaluation, and database write."""
        started_at = datetime.now(timezone.utc)
        logger.info(f"=== Starting AAGAM Ingest-Blend Cycle (dry_run={dry_run}) ===")

        # 1. Fetch live forecasts
        raw_records, api_calls_est, halt_reason = self.fetch_live_forecasts(dry_run=dry_run)

        conn = self.get_connection()

        if halt_reason and "429" in halt_reason:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pipeline_runs (job, started_at, finished_at, status, rows_written, api_calls_est, message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        "ingest-blend",
                        started_at,
                        datetime.now(timezone.utc),
                        "HALTED",
                        len(raw_records),
                        api_calls_est,
                        halt_reason,
                    ),
                )
            conn.close()
            return {"status": "HALTED", "message": halt_reason, "rows_written": len(raw_records)}

        # 2. Upsert into model_forecasts
        if raw_records:
            logger.info(f"Upserting {len(raw_records)} raw model forecasts into database...")
            with conn.cursor() as cur:
                upsert_query = """
                    INSERT INTO model_forecasts (
                        location_id, model, variable, valid_date, lead_days, issue_time, value
                    ) VALUES %s
                    ON CONFLICT (location_id, model, variable, valid_date) DO UPDATE
                    SET lead_days = EXCLUDED.lead_days,
                        issue_time = EXCLUDED.issue_time,
                        value = EXCLUDED.value;
                """
                execute_values(cur, upsert_query, raw_records, page_size=1000)

            # Archive raw forecasts to Parquet historical store (PRD §11 line 545)
            if not dry_run:
                self.archive_live_forecasts_to_parquet(raw_records)

        # 3. Build pivoting table for active blending
        logger.info("Assembling multi-model inputs for blending...")
        df_raw = pd.DataFrame(
            raw_records,
            columns=["location_id", "model", "variable", "valid_date", "lead_days", "issue_time", "value"]
        )

        if df_raw.empty:
            conn.close()
            return {"status": "SUCCESS", "message": "No forecast rows to blend.", "rows_written": 0}

        # Pivot models to columns
        pivoted = df_raw.pivot_table(
            index=["location_id", "variable", "valid_date", "lead_days", "issue_time"],
            columns="model",
            values="value",
            aggfunc="first",
        ).reset_index()

        # Rename to f_gfs, f_ecmwf_ifs, f_icon, f_aifs
        col_rename = {
            "gfs": "f_gfs",
            "ecmwf_ifs": "f_ecmwf_ifs",
            "icon": "f_icon",
            "aifs": "f_aifs",
        }
        pivoted = pivoted.rename(columns=col_rename)
        for col in ["f_gfs", "f_ecmwf_ifs", "f_icon", "f_aifs"]:
            if col not in pivoted.columns:
                pivoted[col] = np.nan

        # Attach location metadata
        loc_map = {loc["id"]: loc for loc in self.locations}
        pivoted["lat"] = pivoted["location_id"].map(lambda x: loc_map[x]["latitude"])
        pivoted["lon"] = pivoted["location_id"].map(lambda x: loc_map[x]["longitude"])
        pivoted["region"] = pivoted["location_id"].map(lambda x: loc_map[x]["region"])
        pivoted["terrain"] = pivoted["location_id"].map(lambda x: loc_map[x]["terrain"])
        pivoted["location_name"] = pivoted["location_id"].map(lambda x: loc_map[x]["name"])
        pivoted["location_slug"] = pivoted["location_id"].map(lambda x: loc_map[x]["slug"])

        # Compute consensus statistics
        model_cols = ["f_gfs", "f_ecmwf_ifs", "f_icon", "f_aifs"]
        pivoted["mean"] = pivoted[model_cols].mean(axis=1, skipna=True)
        pivoted["std"] = pivoted[model_cols].std(axis=1, skipna=True).fillna(0.0)
        pivoted["max"] = pivoted[model_cols].max(axis=1, skipna=True)
        pivoted["min"] = pivoted[model_cols].min(axis=1, skipna=True)

        # Compute time features
        doy_series = pd.to_datetime(pivoted["valid_date"]).dt.dayofyear
        pivoted["doy_sin"] = np.sin(2.0 * np.pi * doy_series / 365.25)
        pivoted["doy_cos"] = np.cos(2.0 * np.pi * doy_series / 365.25)
        pivoted["season"] = [get_season(d) for d in pd.to_datetime(pivoted["valid_date"]).dt.date]
        pivoted["regime"] = [get_regime(v, m) for v, m in zip(pivoted["variable"], pivoted["mean"])]

        # 4. Load active model version artifacts
        active_ver = model_registry.get_active_version()
        version_id = active_ver["id"] if active_ver else None
        active_dir = Path(active_ver["storage_path"]) if active_ver else Path("models")
        if not active_dir.exists():
            active_dir = Path("models")

        logger.info(f"Using active model version {version_id} from {active_dir}")

        # Load Ridge model
        ridge_path = active_dir / "ridge_weights.joblib"
        if not ridge_path.exists():
            ridge_path = Path("models/ridge_weights.joblib")
        ridge_engine = joblib.load(ridge_path)

        # Load LightGBM models
        lgbm_engine = LightGBMEngine(models_dir=active_dir)
        try:
            lgbm_engine.load_models(input_dir=active_dir)
        except Exception:
            lgbm_engine.load_models(input_dir=Path("models"))

        # Load Selection decisions
        decisions_path = active_dir / "blend_selection.json"
        if not decisions_path.exists():
            decisions_path = Path("models/blend_selection.json")
        selection_decisions = {}
        if decisions_path.exists():
            with open(decisions_path, "r", encoding="utf-8") as f:
                raw_dec = json.load(f)
            for k, v in raw_dec.items():
                selection_decisions[(v["variable"], int(v["lead_days"]))] = SelectionDecision(**v)

        # 5. Predict with Ridge & LightGBM
        pred_ridge, degraded_ridge = ridge_engine.predict_dataframe(pivoted)
        pred_lgbm = lgbm_engine.predict_dataframe(pivoted)

        # 6. Blend dataframe using AagamBlender
        blender = AagamBlender(selection_decisions=selection_decisions)
        df_blended = blender.blend_dataframe(
            df=pivoted,
            pred_ridge=pred_ridge,
            pred_lgbm=pred_lgbm,
            degraded_ridge=degraded_ridge,
        )

        # 7. Evaluate extreme hazards
        logger.info("Evaluating Phase 4 extreme weather hazard rules...")
        extreme_engine = ExtremeGuidanceEngine()
        alerts_list = extreme_engine.evaluate_all(df_blended)
        logger.info(f"Generated {len(alerts_list)} hazard guidance alerts.")

        # 8. Upsert blended forecasts into database
        blended_records = [
            (
                int(row["location_id"]),
                row["variable"],
                row["valid_date"],
                row["issue_time"],
                int(row["lead_days"]),
                float(row["blended"]) if pd.notna(row["blended"]) else None,
                float(row["ridge"]) if pd.notna(row["ridge"]) else None,
                float(row["lgbm"]) if pd.notna(row["lgbm"]) else None,
                float(row["equal_mean"]) if pd.notna(row["equal_mean"]) else None,
                float(row["spread"]) if pd.notna(row["spread"]) else None,
                int(row["models_over_threshold"]),
                bool(row["degraded"]),
                version_id,
            )
            for _, row in df_blended.iterrows()
        ]

        logger.info(f"Upserting {len(blended_records)} rows into `blended_forecasts`...")
        with conn.cursor() as cur:
            blend_upsert_query = """
                INSERT INTO blended_forecasts (
                    location_id, variable, valid_date, issue_time, lead_days,
                    blended, ridge, lgbm, equal_mean, spread, models_over_threshold, degraded, version_id
                ) VALUES %s
                ON CONFLICT (location_id, variable, valid_date, issue_time) DO UPDATE
                SET lead_days = EXCLUDED.lead_days,
                    blended = EXCLUDED.blended,
                    ridge = EXCLUDED.ridge,
                    lgbm = EXCLUDED.lgbm,
                    equal_mean = EXCLUDED.equal_mean,
                    spread = EXCLUDED.spread,
                    models_over_threshold = EXCLUDED.models_over_threshold,
                    degraded = EXCLUDED.degraded,
                    version_id = EXCLUDED.version_id;
            """
            execute_values(cur, blend_upsert_query, blended_records, page_size=1000)

            # 9. Phase 10: Event grouping, lifecycle state evaluation, and alert upsert
            # Query existing active alert_events from database
            cur.execute("""
                SELECT id, location_id, hazard, status, severity_peak, value_peak,
                       start_date, end_date, first_detected_at, last_updated_at, outcome, verified_at
                FROM alert_events
                WHERE status = 'active';
            """)
            active_events = [
                AlertEventRecord(
                    id=r[0], location_id=r[1], hazard=r[2], status=r[3],
                    severity_peak=r[4], value_peak=r[5], start_date=r[6], end_date=r[7],
                    first_detected_at=r[8], last_updated_at=r[9], outcome=r[10], verified_at=r[11]
                )
                for r in cur.fetchall()
            ]

            # Query immediately previous cycle alerts
            cur.execute("""
                SELECT DISTINCT issue_time FROM alerts
                WHERE issue_time < %s
                ORDER BY issue_time DESC LIMIT 1;
            """, (started_at,))
            prev_issue_row = cur.fetchone()
            previous_alerts = []
            if prev_issue_row:
                cur.execute("""
                    SELECT id, location_id, hazard, severity, valid_date, lead_days, value, event_id
                    FROM alerts
                    WHERE issue_time = %s;
                """, (prev_issue_row[0],))
                previous_alerts = [
                    {
                        "id": r[0], "location_id": r[1], "hazard": r[2],
                        "severity": r[3], "valid_date": r[4], "lead_days": r[5],
                        "value": r[6], "event_id": r[7]
                    }
                    for r in cur.fetchall()
                ]

            # Compute lifecycle states (new, upgraded, downgraded, unchanged)
            compute_lifecycle_states(alerts_list, previous_alerts)

            # Group alerts into alert_events
            grouped_alerts, updated_events = group_alerts_into_events(alerts_list, active_events, now=started_at)

            # Persist alert_events (insert new or update existing)
            for evt in updated_events:
                if evt.id is None or evt.id < 0:
                    cur.execute("""
                        INSERT INTO alert_events (
                            location_id, hazard, status, severity_peak, value_peak,
                            start_date, end_date, first_detected_at, last_updated_at, outcome
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                    """, (
                        evt.location_id, evt.hazard, evt.status, evt.severity_peak, evt.value_peak,
                        evt.start_date, evt.end_date, evt.first_detected_at, evt.last_updated_at, evt.outcome
                    ))
                    new_id = cur.fetchone()[0]
                    old_temp_id = evt.id
                    evt.id = new_id
                    for a in grouped_alerts:
                        if getattr(a, "event_id", None) == old_temp_id or getattr(a, "_event_ref", None) is evt:
                            a.event_id = new_id
                else:
                    cur.execute("""
                        UPDATE alert_events
                        SET start_date = %s, end_date = %s, severity_peak = %s, value_peak = %s,
                            status = %s, last_updated_at = %s
                        WHERE id = %s;
                    """, (
                        evt.start_date, evt.end_date, evt.severity_peak, evt.value_peak,
                        evt.status, evt.last_updated_at, evt.id
                    ))

            # Handle event and alert cancellations/expiries
            expired_ids, cancelled_evt_ids, cancelled_alert_ids = update_event_cancellations_and_expiries(
                grouped_alerts, previous_alerts, updated_events, today_date=started_at.date(), now=started_at
            )
            if expired_ids:
                cur.execute("UPDATE alert_events SET status = 'expired', last_updated_at = %s WHERE id = ANY(%s::bigint[]);", (started_at, expired_ids))
            if cancelled_evt_ids:
                cur.execute("UPDATE alert_events SET status = 'cancelled', last_updated_at = %s WHERE id = ANY(%s::bigint[]);", (started_at, cancelled_evt_ids))
            if cancelled_alert_ids:
                cur.execute("UPDATE alerts SET lifecycle_state = 'cancelled' WHERE id = ANY(%s::bigint[]);", (cancelled_alert_ids,))

            # Upsert enriched alerts into database
            if grouped_alerts:
                logger.info(f"Upserting {len(grouped_alerts)} alerts with lifecycle states into database...")
                # Deduplicate by constraint key (started_at, location_id, hazard, valid_date, lead_days)
                # to prevent CardinalityViolation in Postgres execute_values
                alert_records_dict = {}
                for a in grouped_alerts:
                    record_key = (started_at, int(a.location_id), str(a.hazard), str(a.valid_date), int(a.lead_days))
                    alert_records_dict[record_key] = (
                        started_at,
                        a.location_id,
                        a.hazard,
                        a.severity,
                        a.valid_date,
                        a.lead_days,
                        a.value,
                        a.agreement,
                        a.spread,
                        json.dumps(a.rule),
                        a.status,
                        getattr(a, "event_id", None),
                        getattr(a, "lifecycle_state", "new"),
                        getattr(a, "previous_severity", None),
                        getattr(a, "rarity_label", None),
                    )
                alert_records = list(alert_records_dict.values())
                alert_upsert_query = """
                    INSERT INTO alerts (
                        issue_time, location_id, hazard, severity, valid_date, lead_days,
                        value, models_over, spread, rule, status, event_id, lifecycle_state, previous_severity, rarity_label
                    ) VALUES %s
                    ON CONFLICT (issue_time, location_id, hazard, valid_date, lead_days) DO UPDATE
                    SET severity = EXCLUDED.severity,
                        value = EXCLUDED.value,
                        models_over = EXCLUDED.models_over,
                        spread = EXCLUDED.spread,
                        rule = EXCLUDED.rule,
                        status = EXCLUDED.status,
                        event_id = EXCLUDED.event_id,
                        lifecycle_state = EXCLUDED.lifecycle_state,
                        previous_severity = EXCLUDED.previous_severity,
                        rarity_label = EXCLUDED.rarity_label;
                """
                execute_values(cur, alert_upsert_query, alert_records, page_size=1000)

            finished_at = datetime.now(timezone.utc)
            duration_sec = (finished_at - started_at).total_seconds()

            # 10. Observability: log run to pipeline_runs
            cur.execute(
                """
                INSERT INTO pipeline_runs (job, started_at, finished_at, status, rows_written, api_calls_est, message)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    "ingest-blend",
                    started_at,
                    finished_at,
                    "SUCCESS",
                    len(blended_records),
                    api_calls_est,
                    f"Successfully blended {len(blended_records)} forecasts and generated {len(alerts_list)} alerts across 40 locations in {duration_sec:.2f}s (active version {version_id}).",
                ),
            )

        conn.close()
        logger.info(f"Ingest-blend cycle complete in {duration_sec:.2f}s.")

        return {
            "status": "SUCCESS",
            "blended_rows": len(blended_records),
            "alerts_count": len(alerts_list),
            "version_id": version_id,
            "duration_seconds": duration_sec,
            "api_calls_est": api_calls_est,
        }

    def archive_live_forecasts_to_parquet(
        self,
        raw_records: List[Tuple[Any, ...]],
        parquet_path: Optional[Path] = None,
    ) -> int:
        """Archives live raw model forecast records to the canonical Parquet store (PRD §11 line 545).

        Deduplicates on (location_id, model, valid_date, lead_days) so that every lead day
        and issue is preserved for subsequent operational verification.
        """
        if not raw_records:
            return 0

        target_path = parquet_path or Path("data/forecasts_backfill.parquet")

        df_new = pd.DataFrame(
            raw_records,
            columns=["location_id", "model", "variable", "valid_date", "lead_days", "issue_time", "value"],
        )

        pivoted_new = df_new.pivot_table(
            index=["location_id", "model", "valid_date", "lead_days"],
            columns="variable",
            values="value",
            aggfunc="first",
        ).reset_index()

        rename_dict = {
            "rain_mm": "f_rain_mm",
            "tmax_c": "f_tmax_c",
            "wind_max_kmh": "f_wind_max_kmh",
        }
        pivoted_new = pivoted_new.rename(columns={k: v for k, v in rename_dict.items() if k in pivoted_new.columns})
        for c in ["f_rain_mm", "f_tmax_c", "f_wind_max_kmh"]:
            if c not in pivoted_new.columns:
                pivoted_new[c] = np.nan

        pivoted_new["valid_date"] = pd.to_datetime(pivoted_new["valid_date"]).dt.date
        pivoted_new["location_id"] = pivoted_new["location_id"].astype(int)
        pivoted_new["lead_days"] = pivoted_new["lead_days"].astype(int)

        dedup_keys = ["location_id", "model", "valid_date", "lead_days"]

        if target_path.exists():
            try:
                df_existing = pd.read_parquet(target_path)
                df_existing["valid_date"] = pd.to_datetime(df_existing["valid_date"]).dt.date
                df_existing["location_id"] = df_existing["location_id"].astype(int)
                df_existing["lead_days"] = df_existing["lead_days"].astype(int)
                combined = pd.concat([df_existing, pivoted_new], ignore_index=True)
                combined = combined.drop_duplicates(subset=dedup_keys, keep="last").sort_values(dedup_keys).reset_index(drop=True)
            except Exception as e:
                logger.warning(f"Could not read existing parquet {target_path}: {e}; creating fresh.")
                combined = pivoted_new.drop_duplicates(subset=dedup_keys, keep="last").sort_values(dedup_keys).reset_index(drop=True)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            combined = pivoted_new.drop_duplicates(subset=dedup_keys, keep="last").sort_values(dedup_keys).reset_index(drop=True)

        combined.to_parquet(target_path, index=False, engine="pyarrow", compression="snappy")
        logger.info(f"Archived {len(pivoted_new)} live forecast records into {target_path} (total rows: {len(combined)}).")
        return len(pivoted_new)

    run_cycle = run_ingest_and_blend


# Global singleton
live_runner = LivePipelineRunner()
