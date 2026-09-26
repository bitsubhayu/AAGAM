"""AAGAM — Daily Verification Pipeline Runner (PRD §6.7, §12, FR-VER-1, FR-VER-2, Tech Stack §10).

Orchestrates the scheduled `verify-daily` workflow (23 3 * * *):
1. Anchors to operational `blended_forecasts` and discovers newly verifiable forecast dates (forecast valid_date <= available ground truth date).
2. Calculates dynamic live verification window (1..90 days, capped at 90) and data maturity label.
3. Evaluates continuous verification scores (MAE, RMSE, Bias, N) across candidates:
   [gfs, ecmwf_ifs, icon, aifs, equal_mean, ridge, lgbm, blend].
   Calculates observation-level metrics for All-India (region='ALL') and regional domains without averaging regional percentages.
4. Evaluates categorical contingency scores (Hits, False Alarms, Misses, Correct Negatives, POD, FAR, CSI)
   at rainfall thresholds [2.5, 15.6, 64.5, 115.6 mm]. Handles zero/insufficient event states safely.
5. Upserts metrics into `skill_scores` table tagged with evaluation_scope='live' (separate from held-out benchmark).
6. Preserves the formal held-out 90-day test benchmark tagged with evaluation_scope='held_out'.
7. Records execution telemetry in `pipeline_runs`.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from core.config import settings
from pipeline.processing.build_training_dataset import get_season
from pipeline.skill.scoring import compute_metrics

logger = logging.getLogger("aagam.pipeline.live.verification")

TRUTH_PARQUET = Path("data/truth.parquet")
BASELINE_COMPARISONS_PARQUET = Path("data/baseline_comparisons.parquet")
RAINFALL_THRESHOLDS = [2.5, 15.6, 64.5, 115.6]
CANDIDATE_MODELS = [
    "gfs",
    "ecmwf_ifs",
    "icon",
    "aifs",
    "equal_mean",
    "ridge",
    "lgbm",
    "blend",
]

CANDIDATE_MAP = {
    "GFS": "gfs",
    "ECMWF IFS": "ecmwf_ifs",
    "ICON": "icon",
    "AIFS": "aifs",
    "Equal-Weight Mean": "equal_mean",
    "Best-Single Model": "best_single",
    "Inverse-MAE Blend": "blend",
}


def calculate_live_window(
    matched_dates: List[date],
    max_window_days: int = 90,
    max_window: Optional[int] = None,
) -> Dict[str, Any]:
    if max_window is not None:
        max_window_days = max_window

    """Determines the effective live verification window and data maturity per PRD §12.

    Inputs:
        matched_dates: Unique dates with at least one matching operational forecast and ground truth pair.
        max_window_days: Hard maximum calendar-day evaluation window (default 90).

    Returns dict with:
        latest_verified_date: latest valid_date with matched forecast/truth.
        earliest_allowed_date: latest_verified_date - (max_window_days - 1) days.
        earliest_verified_date: earliest included valid_date in the window.
        verified_days_count: count of unique verified dates in window.
        effective_calendar_window_days: calendar days from earliest included date to latest date, capped at max_window_days.
        window_start: ISO date string.
        window_end: ISO date string.
        data_status: Maturity label per specification:
            0 days: "NO VERIFICATION DATA"
            1–3 days: "PRELIMINARY LIVE VERIFICATION"
            4–6 days: "EARLY LIVE VERIFICATION"
            7–29 days: "LIVE VERIFICATION"
            30–89 days: "LIVE VERIFICATION"
            90+ days: "LIVE VERIFICATION · 90-DAY MAX"
    """
    if not matched_dates:
        return {
            "latest_verified_date": None,
            "earliest_allowed_date": None,
            "earliest_verified_date": None,
            "verified_days_count": 0,
            "effective_calendar_window_days": 0,
            "window_start": None,
            "window_end": None,
            "data_status": "NO VERIFICATION DATA",
        }

    latest_verified_date = max(matched_dates)
    earliest_allowed_date = latest_verified_date - timedelta(days=max_window_days - 1)

    # Filter to the allowed max_window_days calendar period
    filtered_dates = sorted([d for d in set(matched_dates) if d >= earliest_allowed_date])
    if not filtered_dates:
        return {
            "latest_verified_date": None,
            "earliest_allowed_date": None,
            "earliest_verified_date": None,
            "verified_days_count": 0,
            "effective_calendar_window_days": 0,
            "window_start": None,
            "window_end": None,
            "data_status": "NO VERIFICATION DATA",
        }

    earliest_verified_date = min(filtered_dates)
    verified_days_count = len(filtered_dates)
    calendar_span = (latest_verified_date - earliest_verified_date).days + 1
    effective_calendar_window_days = min(max_window_days, calendar_span)

    if verified_days_count == 0:
        data_status = "NO VERIFICATION DATA"
    elif 1 <= verified_days_count <= 3:
        data_status = "PRELIMINARY LIVE VERIFICATION"
    elif 4 <= verified_days_count <= 6:
        data_status = "EARLY LIVE VERIFICATION"
    elif 7 <= verified_days_count <= 29:
        data_status = "LIVE VERIFICATION"
    elif 30 <= verified_days_count <= 89:
        data_status = "LIVE VERIFICATION"
    else:
        data_status = "LIVE VERIFICATION · 90-DAY MAX"

    return {
        "latest_verified_date": latest_verified_date,
        "earliest_allowed_date": earliest_allowed_date,
        "earliest_verified_date": earliest_verified_date,
        "verified_days_count": verified_days_count,
        "effective_calendar_window_days": effective_calendar_window_days,
        "window_start": earliest_verified_date.isoformat(),
        "window_end": latest_verified_date.isoformat(),
        "data_status": data_status,
    }


def determine_truth_source(truth_df: pd.DataFrame, variable: Optional[str] = None) -> str:
    """Returns human-readable, scientifically accurate description of truth source used."""
    if truth_df.empty:
        return "IMD 0.25° Gridded Rainfall & ERA5 Climatology"

    if variable == "rain_mm":
        if "rain_truth_source" in truth_df.columns:
            sources = set(truth_df["rain_truth_source"].dropna().unique())
            if sources == {"imd_gridded"}:
                return "IMD 0.25° Gridded Rainfall"
            elif "era5_historical" in sources and "imd_gridded" in sources:
                return "IMD 0.25° Gridded Rainfall & ERA5 Climatology Fallback"
            elif sources == {"era5_historical"}:
                return "ERA5 Climatology Fallback (IMD Station Offline)"
        return "IMD Gridded Rainfall / ERA5 Fallback"
    elif variable in ("tmax_c", "wind_max_kmh"):
        return "ERA5 Historical Reanalysis"
    else:
        return "IMD 0.25° Gridded Rainfall & ERA5 Climatology Fallback"


class VerificationRunner:
    """Executes the daily verification and skill scoring pipeline."""

    def __init__(
        self,
        db_url: Optional[str] = None,
        historical_parquet_path: Optional[Path] = None,
    ):
        self.db_url = db_url or settings.DATABASE_URL
        self.historical_parquet_path = (
            Path(historical_parquet_path)
            if historical_parquet_path is not None
            else Path("data/forecasts_backfill.parquet")
        )

    def get_connection(self):
        if not self.db_url:
            raise RuntimeError("DATABASE_URL is required for verification operations.")
        conn = psycopg2.connect(self.db_url)
        conn.autocommit = True
        return conn

    def calculate_live_window(
        self,
        matched_dates: List[date],
        max_window_days: int = 90,
    ) -> Dict[str, Any]:
        return calculate_live_window(matched_dates, max_window_days)

    def determine_truth_source(
        self,
        truth_df: pd.DataFrame,
        variable: Optional[str] = None,
    ) -> str:
        return determine_truth_source(truth_df, variable)

    def load_historical_raw_forecasts(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Retrieves actual historical raw model forecasts from the Parquet archive (PRD §11 line 545)."""
        if not self.historical_parquet_path.exists():
            logger.warning(f"Historical raw forecast store {self.historical_parquet_path} does not exist.")
            return pd.DataFrame()

        try:
            try:
                df_hist = pd.read_parquet(
                    self.historical_parquet_path,
                    filters=[("valid_date", ">=", start_date), ("valid_date", "<=", end_date)],
                )
            except Exception:
                df_hist = pd.read_parquet(self.historical_parquet_path)
                if not df_hist.empty:
                    df_hist["valid_date_dt"] = pd.to_datetime(df_hist["valid_date"]).dt.date
                    df_hist = df_hist[
                        (df_hist["valid_date_dt"] >= start_date) & (df_hist["valid_date_dt"] <= end_date)
                    ].drop(columns=["valid_date_dt"])

            if df_hist.empty:
                return pd.DataFrame()

            model_map = {
                "gfs_seamless": "gfs",
                "ecmwf_ifs025": "ecmwf_ifs",
                "icon_global": "icon",
                "ecmwf_aifs025_single": "aifs",
            }

            if "variable" in df_hist.columns and "value" in df_hist.columns and "model" in df_hist.columns:
                df_long = df_hist[["location_id", "model", "variable", "valid_date", "lead_days", "value"]].copy()
                df_long["location_id"] = df_long["location_id"].astype(int)
                df_long["lead_days"] = df_long["lead_days"].astype(int)
                df_long["valid_date"] = pd.to_datetime(df_long["valid_date"]).dt.date
                df_long["model"] = df_long["model"].replace(model_map)
                pivoted = df_long.pivot_table(
                    index=["location_id", "variable", "valid_date", "lead_days"],
                    columns="model",
                    values="value",
                    aggfunc="first",
                ).reset_index()
                return pivoted

            long_frames = []
            var_map = [
                ("f_rain_mm", "rain_mm"),
                ("f_tmax_c", "tmax_c"),
                ("f_wind_max_kmh", "wind_max_kmh"),
            ]
            for col_name, var_name in var_map:
                if col_name in df_hist.columns:
                    sub = df_hist[["location_id", "model", "valid_date", "lead_days", col_name]].copy()
                    sub = sub.rename(columns={col_name: "value"})
                    sub["variable"] = var_name
                    long_frames.append(sub)

            if not long_frames:
                return pd.DataFrame()

            df_long = pd.concat(long_frames, ignore_index=True)
            df_long = df_long.dropna(subset=["value"])
            df_long["location_id"] = df_long["location_id"].astype(int)
            df_long["lead_days"] = df_long["lead_days"].astype(int)
            df_long["valid_date"] = pd.to_datetime(df_long["valid_date"]).dt.date
            df_long["model"] = df_long["model"].replace(model_map)

            pivoted = df_long.pivot_table(
                index=["location_id", "variable", "valid_date", "lead_days"],
                columns="model",
                values="value",
                aggfunc="first",
            ).reset_index()

            return pivoted
        except Exception as exc:
            logger.error(f"Error loading historical raw forecasts from {self.historical_parquet_path}: {exc}")
            return pd.DataFrame()

    def load_operational_raw_forecasts(
        self,
        start_date: date,
        end_date: date,
        conn: Optional[Any] = None,
    ) -> pd.DataFrame:
        """Retrieves raw model forecasts from DB (model_forecasts) and/or historical parquet archive."""
        frames = []

        # 1. DB model_forecasts
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT location_id, model, variable, valid_date, lead_days, value
                        FROM model_forecasts
                        WHERE valid_date BETWEEN %s AND %s;
                        """,
                        (start_date, end_date),
                    )
                    rows = cur.fetchall()
                if rows:
                    df_db = pd.DataFrame(
                        rows,
                        columns=["location_id", "model", "variable", "valid_date", "lead_days", "value"],
                    )
                    df_db["location_id"] = df_db["location_id"].astype(int)
                    df_db["lead_days"] = df_db["lead_days"].astype(int)
                    df_db["valid_date"] = pd.to_datetime(df_db["valid_date"]).dt.date
                    pivoted_db = df_db.pivot_table(
                        index=["location_id", "variable", "valid_date", "lead_days"],
                        columns="model",
                        values="value",
                        aggfunc="first",
                    ).reset_index()
                    frames.append(pivoted_db)
            except Exception as e:
                logger.warning(f"Could not load raw forecasts from model_forecasts table: {e}")

        # 2. Historical parquet archive
        df_hist = self.load_historical_raw_forecasts(start_date, end_date)
        if not df_hist.empty:
            frames.append(df_hist)

        if not frames:
            return pd.DataFrame()

        combined = pd.concat(frames, ignore_index=True)
        dedup = combined.drop_duplicates(
            subset=["location_id", "variable", "valid_date", "lead_days"],
            keep="last",
        ).reset_index(drop=True)
        return dedup

    def seed_held_out_benchmark(self, conn: Any) -> int:
        """Seeds the formal held-out 90-day test benchmark from baseline_comparisons.parquet into skill_scores."""
        if not BASELINE_COMPARISONS_PARQUET.exists():
            logger.info(f"Baseline comparisons parquet {BASELINE_COMPARISONS_PARQUET} not found; skipping seed.")
            return 0

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM skill_scores WHERE evaluation_scope = 'held_out';")
                existing_count = cur.fetchone()[0]
                if existing_count > 0:
                    logger.debug(f"Formal held-out benchmark already present ({existing_count} rows).")
                    return existing_count

                df_base = pd.read_parquet(BASELINE_COMPARISONS_PARQUET)
                records = []
                computed_at = datetime(2026, 9, 19, 0, 0, 0, tzinfo=timezone.utc)


                for _, row in df_base.iterrows():
                    cand = CANDIDATE_MAP.get(row["candidate"], row["candidate"].lower())
                    var = row["variable"]
                    stype = row["slice_type"]
                    sval = row["slice_value"]

                    if stype == "lead_days":
                        lead = int(sval)
                        reg = "ALL"
                        seas = "ALL"
                    elif stype == "region":
                        lead = 1
                        reg = sval
                        seas = "ALL"
                    elif stype == "overall":
                        lead = 0
                        reg = "ALL"
                        seas = "ALL"
                    elif stype == "season":
                        lead = 0
                        reg = "ALL"
                        seas = sval
                    else:
                        continue

                    records.append((
                        computed_at,
                        90,
                        var,
                        reg,
                        seas,
                        lead,
                        cand,
                        float(row["mae"]) if pd.notna(row["mae"]) else None,
                        float(row["rmse"]) if pd.notna(row["rmse"]) else None,
                        float(row["bias"]) if pd.notna(row["bias"]) else None,
                        int(row["n"]) if pd.notna(row["n"]) else 0,
                        None,  # pod
                        None,  # far
                        None,  # csi
                        0.0,   # threshold_mm
                        False, # is_weekly
                        "held_out",
                        None,  # hits
                        None,  # false_alarms
                        None,  # misses
                        None,  # correct_negatives
                    ))

                if records:
                    upsert_query = """
                        INSERT INTO skill_scores (
                            computed_at, window_days, variable, region, season, lead_days,
                            model, mae, rmse, bias, n, pod, far, csi, threshold_mm, is_weekly,
                            evaluation_scope, hits, false_alarms, misses, correct_negatives
                        ) VALUES %s
                        ON CONFLICT (computed_at, window_days, variable, region, season, lead_days, model, threshold_mm, is_weekly)
                        DO UPDATE
                        SET mae = EXCLUDED.mae,
                            rmse = EXCLUDED.rmse,
                            bias = EXCLUDED.bias,
                            n = EXCLUDED.n,
                            evaluation_scope = EXCLUDED.evaluation_scope;
                    """
                    execute_values(cur, upsert_query, records, page_size=1000)
                    logger.info(f"Seeded {len(records)} formal held-out benchmark records into skill_scores.")
                    return len(records)
        except Exception as e:
            logger.warning(f"Could not seed formal held-out benchmark: {e}")
        return 0

    def run_daily_verification(
        self,
        target_date: Optional[date] = None,
        window_days: int = 90,
        dry_run: bool = False,
        use_test_fallback: bool = False,
    ) -> Dict[str, Any]:
        """Runs daily operational verification against ground truth observations.

        - Anchors strictly to operational `blended_forecasts`.
        - Calculates effective available live window (capped at window_days, default 90).
        - Computes domain-level metrics for All-India ('ALL') and individual regions.
        - Persists live verification records tagged with evaluation_scope='live'.
        - Seeds/preserves formal held-out benchmark separately.
        """
        started_at = datetime.now(timezone.utc)
        logger.info(f"=== Starting Daily Verification Cycle (max_window={window_days}d, dry_run={dry_run}) ===")

        if not TRUTH_PARQUET.exists():
            if use_test_fallback:
                logger.info("Ground truth parquet missing in test mode; checking test dataset.")
            else:
                logger.warning(f"Ground truth parquet {TRUTH_PARQUET} not found.")
                return {"status": "SKIPPED", "message": "No ground truth available.", "rows_written": 0}

        conn = self.get_connection()
        try:
            # Base contract fields
            is_sunday = (target_date.weekday() == 6) if target_date is not None else (datetime.now(timezone.utc).weekday() == 6)

            # 1. Query all operational blended forecasts from database (anchored dataset)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT bf.location_id, bf.variable, bf.valid_date, bf.lead_days,
                           bf.blended AS blend, bf.ridge, bf.lgbm, bf.equal_mean,
                           loc.region
                    FROM blended_forecasts bf
                    JOIN locations loc ON loc.id = bf.location_id;
                    """
                )
                blended_rows = cur.fetchall()

            df_blended = pd.DataFrame()
            if blended_rows:
                df_blended = pd.DataFrame(
                    blended_rows,
                    columns=[
                        "location_id",
                        "variable",
                        "valid_date",
                        "lead_days",
                        "blend",
                        "ridge",
                        "lgbm",
                        "equal_mean",
                        "region",
                    ],
                )
                df_blended["valid_date"] = pd.to_datetime(df_blended["valid_date"]).dt.date
                df_blended["location_id"] = df_blended["location_id"].astype(int)
                df_blended["lead_days"] = df_blended["lead_days"].astype(int)

                # Cap evaluation to target_date if specified (never use future data)
                if target_date is not None:
                    df_blended = df_blended[df_blended["valid_date"] <= target_date]

            if df_blended.empty:
                if not use_test_fallback:
                    msg = "No operational blended forecasts found in database for verification."
                    logger.warning(f"Production verification halted: {msg}")
                    return {
                        "status": "NO_DATA",
                        "rows_written": 0,
                        "skill_scores_written": 0,
                        "matched_observations": 0,
                        "is_sunday": is_sunday,
                        "candidate_models": [],
                        "seasons_evaluated": [],
                        "lead_days_evaluated": [],
                        "message": msg,
                    }

            # 2. Load ground truth
            truth_melted = pd.DataFrame()
            if TRUTH_PARQUET.exists():
                df_truth = pd.read_parquet(TRUTH_PARQUET)
                df_truth["valid_date"] = pd.to_datetime(df_truth["valid_date"]).dt.date

                # Pre-filter truth to operational dates
                if not df_blended.empty:
                    blended_dates_set = set(df_blended["valid_date"].unique())
                    df_truth_sub = df_truth[df_truth["valid_date"].isin(blended_dates_set)].copy()
                else:
                    df_truth_sub = df_truth.copy()

                value_vars = [c for c in ["rain_truth", "tmax_truth", "wind_max_truth"] if c in df_truth_sub.columns]
                if value_vars:
                    truth_melted = df_truth_sub.melt(
                        id_vars=["location_id", "valid_date"],
                        value_vars=value_vars,
                        var_name="var_truth",
                        value_name="truth",
                    )
                    truth_melted["variable"] = truth_melted["var_truth"].map({
                        "rain_truth": "rain_mm",
                        "tmax_truth": "tmax_c",
                        "wind_max_truth": "wind_max_kmh",
                    })

            # 3. Determine verified dates and effective live window
            if not truth_melted.empty and not df_blended.empty:
                overlap_probe = pd.merge(
                    df_blended[["location_id", "variable", "valid_date"]].drop_duplicates(),
                    truth_melted[["location_id", "variable", "valid_date", "truth"]].dropna(subset=["truth"]),
                    on=["location_id", "variable", "valid_date"],
                    how="inner",
                )
                matched_dates = sorted(list(overlap_probe["valid_date"].unique()))
            else:
                matched_dates = []

            window_info = self.calculate_live_window(matched_dates, max_window_days=window_days)
            logger.info(f"Live window calculation: {window_info}")

            if window_info["verified_days_count"] == 0:
                if not use_test_fallback:
                    logger.warning("No overlapping observations between operational forecasts and ground truth.")
                    return {
                        "status": "NO_OVERLAP",
                        "rows_written": 0,
                        "skill_scores_written": 0,
                        "matched_observations": 0,
                        "is_sunday": is_sunday,
                        "candidate_models": [],
                        "seasons_evaluated": [],
                        "lead_days_evaluated": [],
                        "message": "No overlapping observations with truth.",
                        "window_info": window_info,
                    }

            # 4. Filter operational blended forecasts to the effective window
            start_eval_date = window_info["earliest_allowed_date"]
            eval_date = window_info["latest_verified_date"]

            if start_eval_date is not None and eval_date is not None and not df_blended.empty:
                df_blended_window = df_blended[
                    (df_blended["valid_date"] >= start_eval_date) & (df_blended["valid_date"] <= eval_date)
                ].copy()
            else:
                df_blended_window = df_blended.copy()

            df_blended_dedup = df_blended_window.drop_duplicates(
                subset=["location_id", "variable", "valid_date", "lead_days"],
                keep="last",
            )

            # 5. Retrieve historical raw model forecasts from canonical store (PRD §11 line 545)
            df_raw = self.load_historical_raw_forecasts(
                start_date=start_eval_date or (target_date or date.today()) - timedelta(days=window_days),
                end_date=eval_date or (target_date or date.today()),
            )

            if df_raw.empty and not use_test_fallback:
                msg = "Missing historical operational raw model forecast data for verification window."
                logger.warning(f"Production verification halted: {msg}")
                return {
                    "status": "NO_DATA",
                    "rows_written": 0,
                    "skill_scores_written": 0,
                    "matched_observations": 0,
                    "is_sunday": is_sunday,
                    "candidate_models": [],
                    "seasons_evaluated": [],
                    "lead_days_evaluated": [],
                    "message": msg,
                    "window_info": window_info,
                }

            # Attempt 1: Exact join on [location_id, variable, valid_date, lead_days]
            if not df_raw.empty and not df_blended_dedup.empty:
                df_fcst = pd.merge(
                    df_blended_dedup,
                    df_raw,
                    on=["location_id", "variable", "valid_date", "lead_days"],
                    how="inner",
                )
                # If some leads missed exact lead_days match, fall back to matching on [location_id, variable, valid_date]
                if len(df_fcst) < len(df_blended_dedup):
                    unmatched = df_blended_dedup[
                        ~df_blended_dedup.set_index(["location_id", "variable", "valid_date", "lead_days"]).index.isin(
                            df_fcst.set_index(["location_id", "variable", "valid_date", "lead_days"]).index
                        )
                    ].copy()
                    raw_by_valid = df_raw.drop(columns=["lead_days"], errors="ignore").drop_duplicates(
                        subset=["location_id", "variable", "valid_date"],
                        keep="last",
                    )
                    recovered = pd.merge(
                        unmatched,
                        raw_by_valid,
                        on=["location_id", "variable", "valid_date"],
                        how="inner",
                    )
                    if not recovered.empty:
                        df_fcst = pd.concat([df_fcst, recovered], ignore_index=True)
            else:
                df_fcst = df_blended_dedup.copy()

            # Ensure raw model candidate columns exist
            for m in ["gfs", "ecmwf_ifs", "icon", "aifs"]:
                if m not in df_fcst.columns:
                    df_fcst[m] = np.nan

            # 6. Join forecasts with ground truth
            if "truth" in df_fcst.columns and not df_fcst.empty:
                joined = df_fcst.copy()
            elif not df_fcst.empty and not truth_melted.empty:
                joined = pd.merge(
                    df_fcst,
                    truth_melted[["location_id", "variable", "valid_date", "truth"]],
                    on=["location_id", "variable", "valid_date"],
                    how="inner",
                )
            else:
                joined = pd.DataFrame()

            # Fallback to test dataset if joined is empty and use_test_fallback is enabled
            if joined.empty and use_test_fallback:
                logger.info("Test fallback enabled. Loading synthetic test dataset for isolated test mode.")
                test_parquet = Path("data/blended_forecasts_test.parquet")
                if test_parquet.exists():
                    df_test = pd.read_parquet(test_parquet)
                    rename_map = {
                        "f_gfs": "gfs",
                        "f_ecmwf_ifs": "ecmwf_ifs",
                        "f_icon": "icon",
                        "f_aifs": "aifs",
                        "blended": "blend",
                    }
                    df_test = df_test.rename(columns={k: v for k, v in rename_map.items() if k in df_test.columns})
                    if "blend" not in df_test.columns and "blended" in df_test.columns:
                        df_test["blend"] = df_test["blended"]
                    df_test["valid_date"] = pd.to_datetime(df_test["valid_date"]).dt.date
                    joined = df_test
                    matched_dates = sorted(list(joined["valid_date"].unique()))
                    window_info = self.calculate_live_window(matched_dates, max_window_days=window_days)

            if joined.empty:
                logger.warning("No overlapping observations between forecasts and ground truth in window.")
                return {
                    "status": "NO_OVERLAP",
                    "rows_written": 0,
                    "skill_scores_written": 0,
                    "matched_observations": 0,
                    "is_sunday": is_sunday,
                    "candidate_models": [],
                    "seasons_evaluated": [],
                    "lead_days_evaluated": [],
                    "message": "No overlapping observations with truth in window.",
                    "window_info": window_info,
                }

            # Derive canonical meteorological season dynamically from valid_date
            if "valid_date" in joined.columns:
                joined["season"] = [get_season(d) for d in pd.to_datetime(joined["valid_date"]).dt.date]

            # 7. Compute skill records (observation-level domain aggregation)
            computed_at = datetime.now(timezone.utc)
            effective_window_days = window_info.get("effective_calendar_window_days") or len(matched_dates) or 1

            skill_records = self.compute_skill_records(
                joined=joined,
                window_days=effective_window_days,
                computed_at=computed_at,
                evaluation_scope="live",
            )

            # Check if Sunday (weekly copy)
            # Derived strictly from target_date if specified, else eval_date / computed_at
            if target_date is not None:
                is_sunday = (target_date.weekday() == 6)
            elif eval_date is not None:
                is_sunday = (eval_date.weekday() == 6)
            else:
                is_sunday = (computed_at.weekday() == 6)

            records_to_insert = list(skill_records)
            if is_sunday:
                weekly_copy = [rec[:15] + (True,) + rec[16:] for rec in skill_records]
                records_to_insert.extend(weekly_copy)

            # 8. Upsert into database skill_scores
            if not dry_run and records_to_insert:
                conn.autocommit = False
                try:
                    with conn.cursor() as cur:
                        # Delete previous live daily snapshot (preserve weekly and held_out records)
                        cur.execute("DELETE FROM skill_scores WHERE evaluation_scope = 'live' AND is_weekly = false;")

                        upsert_query = """
                            INSERT INTO skill_scores (
                                computed_at, window_days, variable, region, season, lead_days,
                                model, mae, rmse, bias, n, pod, far, csi, threshold_mm, is_weekly,
                                evaluation_scope, hits, false_alarms, misses, correct_negatives
                            ) VALUES %s
                            ON CONFLICT (computed_at, window_days, variable, region, season, lead_days, model, threshold_mm, is_weekly)
                            DO UPDATE
                            SET mae = EXCLUDED.mae,
                                rmse = EXCLUDED.rmse,
                                bias = EXCLUDED.bias,
                                n = EXCLUDED.n,
                                pod = EXCLUDED.pod,
                                far = EXCLUDED.far,
                                csi = EXCLUDED.csi,
                                evaluation_scope = EXCLUDED.evaluation_scope,
                                hits = EXCLUDED.hits,
                                false_alarms = EXCLUDED.false_alarms,
                                misses = EXCLUDED.misses,
                                correct_negatives = EXCLUDED.correct_negatives;
                        """
                        execute_values(cur, upsert_query, records_to_insert, page_size=1000)

                        # Seed formal held-out benchmark if not already seeded
                        self.seed_held_out_benchmark(conn)

                        finished_at = datetime.now(timezone.utc)
                        duration_sec = (finished_at - started_at).total_seconds()

                        # Telemetry to pipeline_runs
                        cur.execute(
                            """
                            INSERT INTO pipeline_runs (job, started_at, finished_at, status, rows_written, api_calls_est, message)
                            VALUES (%s, %s, %s, %s, %s, %s, %s);
                            """,
                            (
                                "verify-daily",
                                started_at,
                                finished_at,
                                "SUCCESS",
                                len(records_to_insert),
                                0,
                                f"Daily verification evaluated {len(joined)} matched observations across {window_info.get('verified_days_count', 0)} verified days ({window_info.get('window_start')} to {window_info.get('window_end')}, effective window: {effective_window_days}d). Replaced daily snapshot with {len(skill_records)} rows (Sunday weekly copy: {is_sunday}) in {duration_sec:.2f}s.",
                            ),
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.autocommit = True

            finished_at = datetime.now(timezone.utc)
            duration_sec = (finished_at - started_at).total_seconds()
            candidates = [c for c in CANDIDATE_MODELS if c in joined.columns]

            return {
                "status": "SUCCESS",
                "matched_observations": len(joined),
                "skill_scores_written": len(records_to_insert),
                "is_sunday": is_sunday,
                "candidate_models": candidates,
                "seasons_evaluated": sorted(list(joined["season"].unique())) if "season" in joined.columns else [],
                "lead_days_evaluated": sorted([int(x) for x in joined["lead_days"].unique()]) if "lead_days" in joined.columns else [],
                "window_info": window_info,
                "duration_seconds": duration_sec,
            }
        finally:
            conn.close()

    def compute_skill_records(
        self,
        joined: pd.DataFrame,
        window_days: int = 90,
        computed_at: Optional[datetime] = None,
        evaluation_scope: str = "live",
    ) -> List[Tuple[Any, ...]]:
        """Computes continuous and categorical skill records across candidates and domains.

        Correctly computes metrics across:
        - All-India ('ALL') domain from all matching observations
        - Individual regional domains from region-specific observations
        - Canonical Indian meteorological seasons (winter, pre_monsoon, monsoon, post_monsoon)
        - Lead days preserved without collapsing or shifting
        """
        if computed_at is None:
            computed_at = datetime.now(timezone.utc)

        df = joined.copy()

        if "valid_date" in df.columns:
            df["season"] = [get_season(d) for d in pd.to_datetime(df["valid_date"]).dt.date]
        elif "season" not in df.columns:
            raise ValueError(
                "Verification dataset must contain 'valid_date' (to derive canonical season) "
                "or an explicit 'season' column; refusing to invent or hardcode a season fallback."
            )

        skill_records: List[Tuple[Any, ...]] = []
        candidates = [c for c in CANDIDATE_MODELS if c in df.columns]

        unique_regions = sorted(list(df["region"].dropna().unique()))
        regions_to_evaluate = ["ALL"] + unique_regions

        unique_seasons = sorted(list(df["season"].dropna().unique()))
        seasons_to_evaluate = unique_seasons

        # 1. Continuous verification metrics
        for var in df["variable"].unique():
            df_var = df[df["variable"] == var]
            for lead in sorted(df_var["lead_days"].unique()):
                df_lead = df_var[df_var["lead_days"] == lead]
                for reg in regions_to_evaluate:
                    df_reg = df_lead if reg == "ALL" else df_lead[df_lead["region"] == reg]
                    if df_reg.empty:
                        continue
                    for seas in seasons_to_evaluate:
                        df_domain = df_reg if seas == "ALL" else df_reg[df_reg["season"] == seas]
                        if df_domain.empty:
                            continue

                        y_true = df_domain["truth"].to_numpy()
                        for cand in candidates:
                            if cand not in df_domain.columns:
                                continue
                            y_pred = df_domain[cand].to_numpy()
                            metrics = compute_metrics(forecast=y_pred, truth=y_true)

                            skill_records.append((
                                computed_at,
                                int(window_days),
                                var,
                                reg,
                                seas,
                                int(lead),
                                cand,
                                float(metrics["mae"]) if not math.isnan(metrics["mae"]) else None,
                                float(metrics["rmse"]) if not math.isnan(metrics["rmse"]) else None,
                                float(metrics["bias"]) if not math.isnan(metrics["bias"]) else None,
                                int(metrics["n"]),
                                None,  # pod
                                None,  # far
                                None,  # csi
                                0.0,   # threshold_mm
                                False, # is_weekly
                                evaluation_scope,
                                None,  # hits
                                None,  # false_alarms
                                None,  # misses
                                None,  # correct_negatives
                            ))

        # 2. Categorical rainfall verification (contingency scores)
        rain_joined = df[df["variable"] == "rain_mm"]
        if not rain_joined.empty:
            for thresh in RAINFALL_THRESHOLDS:
                for lead in sorted(rain_joined["lead_days"].unique()):
                    df_lead = rain_joined[rain_joined["lead_days"] == lead]
                    for reg in regions_to_evaluate:
                        df_reg = df_lead if reg == "ALL" else df_lead[df_lead["region"] == reg]
                        if df_reg.empty:
                            continue
                        for seas in seasons_to_evaluate:
                            df_domain = df_reg if seas == "ALL" else df_reg[df_reg["season"] == seas]
                            if df_domain.empty:
                                continue

                            y_true = df_domain["truth"].to_numpy()
                            for cand in candidates:
                                if cand not in df_domain.columns:
                                    continue
                                y_pred = df_domain[cand].to_numpy()

                                valid_m = ~np.isnan(y_true) & ~np.isnan(y_pred)
                                if not np.any(valid_m):
                                    continue
                                yt = y_true[valid_m]
                                yp = y_pred[valid_m]

                                hits = int(np.sum((yp >= thresh) & (yt >= thresh)))
                                false_alarms = int(np.sum((yp >= thresh) & (yt < thresh)))
                                misses = int(np.sum((yp < thresh) & (yt >= thresh)))
                                correct_negatives = int(np.sum((yp < thresh) & (yt < thresh)))
                                total_samples = len(yt)

                                obs_events = hits + misses
                                pred_events = hits + false_alarms

                                if obs_events == 0 and pred_events == 0:
                                    # No qualifying events observed or predicted: do not display zero
                                    pod = None
                                    far = None
                                    csi = None
                                else:
                                    pod = round(float(hits / obs_events), 4) if obs_events > 0 else None
                                    far = round(float(false_alarms / pred_events), 4) if pred_events > 0 else None
                                    denom = hits + false_alarms + misses
                                    csi = round(float(hits / denom), 4) if denom > 0 else None

                                skill_records.append((
                                    computed_at,
                                    int(window_days),
                                    "rain_mm",
                                    reg,
                                    seas,
                                    int(lead),
                                    cand,
                                    None,  # mae
                                    None,  # rmse
                                    None,  # bias
                                    int(total_samples),
                                    pod,
                                    far,
                                    csi,
                                    float(thresh),
                                    False, # is_weekly
                                    evaluation_scope,
                                    hits,
                                    false_alarms,
                                    misses,
                                    correct_negatives,
                                ))

        return skill_records


# Global singleton
verification_runner = VerificationRunner()
