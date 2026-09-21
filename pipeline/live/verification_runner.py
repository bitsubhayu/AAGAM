"""AAGAM — Daily Verification Pipeline Runner (PRD §6.7, FR-VER-1, FR-VER-2, Tech Stack §10).

Orchestrates the scheduled `verify-daily` workflow (23 3 * * *):
1. Identifies newly verifiable forecast dates (forecast valid_date <= available ground truth date).
2. Evaluates continuous verification scores (MAE, RMSE, Bias, N) across candidates:
   [gfs, ecmwf_ifs, icon, aifs, equal_mean, ridge, lgbm, blend].
3. Evaluates categorical contingency scores (Hits, False Alarms, Misses, POD, FAR, CSI)
   at rainfall thresholds [2.5, 15.6, 64.5, 115.6 mm].
4. Upserts metrics into `skill_scores` table.
5. Records execution telemetry in `pipeline_runs`.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from core.config import settings
from pipeline.blend.verification import compute_contingency_metrics
from pipeline.processing.build_training_dataset import get_season
from pipeline.skill.scoring import compute_metrics

logger = logging.getLogger("aagam.pipeline.live.verification")

TRUTH_PARQUET = Path("data/truth.parquet")
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

    def load_historical_raw_forecasts(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Retrieves actual historical raw model forecasts from the Parquet archive (PRD §11 line 545).

        Returns DataFrame with columns:
        [location_id, variable, valid_date, lead_days, gfs, ecmwf_ifs, icon, aifs]
        where (location_id, variable, valid_date, lead_days) uniquely identifies the forecast issue.
        """
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

            # If already in long format (location_id, model, variable, valid_date, lead_days, value)
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

            # Canonical wide-variable format: f_rain_mm, f_tmax_c, f_wind_max_kmh
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

    def run_daily_verification(
        self,
        target_date: Optional[date] = None,
        window_days: int = 60,
        dry_run: bool = False,
        use_test_fallback: bool = False,
    ) -> Dict[str, Any]:
        """Runs daily verification against available ground truth observations."""
        started_at = datetime.now(timezone.utc)
        logger.info(f"=== Starting Daily Verification Cycle (dry_run={dry_run}, test_fallback={use_test_fallback}) ===")

        if not TRUTH_PARQUET.exists():
            if use_test_fallback:
                logger.info("Ground truth parquet missing in test mode; checking test dataset.")
            else:
                logger.warning(f"Ground truth parquet {TRUTH_PARQUET} not found.")
                return {"status": "SKIPPED", "message": "No ground truth available.", "rows_written": 0}

        # Load truth
        if TRUTH_PARQUET.exists():
            df_truth = pd.read_parquet(TRUTH_PARQUET)
            max_truth_date = pd.to_datetime(df_truth["valid_date"]).max().date()
            eval_date = target_date or max_truth_date
            start_eval_date = eval_date - pd.Timedelta(days=window_days)

            logger.info(f"Evaluating verification window: {start_eval_date} to {eval_date} ({window_days} days)")

            # Filter truth to window
            truth_window = df_truth[
                (pd.to_datetime(df_truth["valid_date"]).dt.date >= start_eval_date)
                & (pd.to_datetime(df_truth["valid_date"]).dt.date <= eval_date)
            ].copy()
            truth_window["valid_date_str"] = pd.to_datetime(truth_window["valid_date"]).dt.strftime("%Y-%m-%d")
            truth_melted = truth_window.melt(
                id_vars=["location_id", "valid_date_str"],
                value_vars=[c for c in ["rain_truth", "tmax_truth", "wind_max_truth"] if c in truth_window.columns],
                var_name="var_truth",
                value_name="truth",
            )
            truth_melted["variable"] = truth_melted["var_truth"].map({
                "rain_truth": "rain_mm",
                "tmax_truth": "tmax_c",
                "wind_max_truth": "wind_max_kmh",
            })
        else:
            eval_date = target_date or date.today()
            start_eval_date = eval_date - pd.Timedelta(days=window_days)
            truth_melted = pd.DataFrame()

        conn = self.get_connection()
        try:
            # Query blended forecasts for this window
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT bf.location_id, bf.variable, bf.valid_date, bf.lead_days,
                           bf.blended AS blend, bf.ridge, bf.lgbm, bf.equal_mean,
                           loc.region
                    FROM blended_forecasts bf
                    JOIN locations loc ON loc.id = bf.location_id
                    WHERE bf.valid_date BETWEEN %s AND %s;
                    """,
                    (start_eval_date, eval_date),
                )
                blended_rows = cur.fetchall()

            # Retrieve actual historical raw model forecasts from canonical Parquet archive (PRD §11 line 545)
            df_raw_historical = self.load_historical_raw_forecasts(start_eval_date, eval_date)

            if not blended_rows or df_raw_historical.empty:
                if not use_test_fallback:
                    msg = (
                        "No operational blended forecasts found in database for verification window."
                        if not blended_rows
                        else "Missing historical operational raw model forecast data for verification window."
                    )
                    logger.warning(f"Production verification halted: {msg}")
                    return {"status": "NO_DATA", "rows_written": 0, "message": msg}

                logger.info("Test fallback enabled. Loading synthetic test dataset for isolated test mode.")
                test_parquet = Path("data/blended_forecasts_test.parquet")
                if test_parquet.exists():
                    df_fcst = pd.read_parquet(test_parquet)
                else:
                    return {
                        "status": "NO_DATA",
                        "rows_written": 0,
                        "message": "No forecast data available for verification.",
                    }
            else:
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

                df_blended_dedup = df_blended.drop_duplicates(
                    subset=["location_id", "variable", "valid_date", "lead_days"],
                    keep="last",
                )

                # Merge blended predictions with historical raw model forecasts matching the exact issue/lead_days
                df_fcst = pd.merge(
                    df_blended_dedup,
                    df_raw_historical,
                    on=["location_id", "variable", "valid_date", "lead_days"],
                    how="inner",
                )

                # Verify presence of raw model candidates
                raw_models = ["gfs", "ecmwf_ifs", "icon", "aifs"]
                missing_raw = [m for m in raw_models if m not in df_fcst.columns]
                if missing_raw or df_fcst.empty:
                    if not use_test_fallback:
                        msg = (
                            f"Incomplete historical raw model forecast data (missing {missing_raw})."
                            if missing_raw
                            else "No matching historical raw forecasts for blended predictions."
                        )
                        logger.warning(f"Production verification halted: {msg}")
                        return {"status": "NO_DATA", "rows_written": 0, "message": msg}

                    logger.info("Test fallback enabled. Missing raw models; loading synthetic test dataset.")
                    test_parquet = Path("data/blended_forecasts_test.parquet")
                    if test_parquet.exists():
                        df_fcst = pd.read_parquet(test_parquet)
                    else:
                        return {
                            "status": "NO_DATA",
                            "rows_written": 0,
                            "message": "No forecast data available for verification.",
                        }

            # Standardize candidate column names across test parquet and DB sources
            rename_map = {
                "f_gfs": "gfs",
                "f_ecmwf_ifs": "ecmwf_ifs",
                "f_icon": "icon",
                "f_aifs": "aifs",
                "blended": "blend",
            }
            df_fcst = df_fcst.rename(columns={k: v for k, v in rename_map.items() if k in df_fcst.columns})
            if "blend" not in df_fcst.columns and "blended" in df_fcst.columns:
                df_fcst["blend"] = df_fcst["blended"]

            if "truth" in df_fcst.columns:
                df_fcst["valid_date_dt"] = pd.to_datetime(df_fcst["valid_date"]).dt.date
                joined = df_fcst[
                    (df_fcst["valid_date_dt"] >= start_eval_date) & (df_fcst["valid_date_dt"] <= eval_date)
                ].copy()
            else:
                if truth_melted.empty:
                    joined = pd.DataFrame()
                else:
                    df_fcst["valid_date_str"] = pd.to_datetime(df_fcst["valid_date"]).dt.strftime("%Y-%m-%d")
                    joined = pd.merge(
                        df_fcst,
                        truth_melted[["location_id", "variable", "valid_date_str", "truth"]],
                        on=["location_id", "variable", "valid_date_str"],
                        how="inner",
                    )

            if joined.empty:
                if not use_test_fallback:
                    logger.warning("No overlapping observations between historical operational forecasts and ground truth.")
                    return {"status": "NO_OVERLAP", "rows_written": 0, "message": "No overlapping observations with truth."}

                logger.info("Test fallback enabled. No overlap; attempting fallback to test dataset.")
                test_parquet = Path("data/blended_forecasts_test.parquet")
                if test_parquet.exists():
                    df_fcst = pd.read_parquet(test_parquet)
                    df_fcst = df_fcst.rename(columns={k: v for k, v in rename_map.items() if k in df_fcst.columns})
                    if "blend" not in df_fcst.columns and "blended" in df_fcst.columns:
                        df_fcst["blend"] = df_fcst["blended"]
                    if "truth" in df_fcst.columns:
                        joined = df_fcst.copy()
                    else:
                        df_fcst["valid_date_str"] = pd.to_datetime(df_fcst["valid_date"]).dt.strftime("%Y-%m-%d")
                        joined = pd.merge(
                            df_fcst,
                            truth_melted[["location_id", "variable", "valid_date_str", "truth"]],
                            on=["location_id", "variable", "valid_date_str"],
                            how="inner",
                        )

            if joined.empty:
                logger.warning("No overlapping observations between forecasts and ground truth.")
                return {"status": "NO_OVERLAP", "rows_written": 0, "message": "No overlapping observations with truth."}

            if "valid_date" in joined.columns:
                joined["season"] = [get_season(d) for d in pd.to_datetime(joined["valid_date"]).dt.date]

            computed_at = datetime.now(timezone.utc)
            skill_records = self.compute_skill_records(
                joined=joined,
                window_days=window_days,
                computed_at=computed_at,
            )

            candidates = [c for c in CANDIDATE_MODELS if c in joined.columns]

            # Check if evaluation/computation date is Sunday (FR-VER-1)
            # In Python: Monday is 0, Sunday is 6
            is_sunday = (eval_date.weekday() == 6) if eval_date else (computed_at.weekday() == 6)

            records_to_insert = list(skill_records)
            if is_sunday:
                # FR-VER-1: On Sunday, also insert a copy of the snapshot with is_weekly = True
                weekly_copy = [rec[:-1] + (True,) for rec in skill_records]
                records_to_insert.extend(weekly_copy)

            logger.info(
                f"Prepared {len(records_to_insert)} skill score records "
                f"({len(skill_records)} non-weekly, {len(records_to_insert) - len(skill_records)} weekly, is_sunday={is_sunday})."
            )

            # Upsert into database skill_scores under FR-VER-1
            if not dry_run and records_to_insert:
                conn.autocommit = False
                try:
                    with conn.cursor() as cur:
                        # 1. Delete all previous skill_scores rows where is_weekly = false (FR-VER-1)
                        cur.execute("DELETE FROM skill_scores WHERE is_weekly = false;")

                        # 2. Insert newly computed rows with is_weekly = false (and is_weekly = true on Sunday)
                        upsert_query = """
                            INSERT INTO skill_scores (
                                computed_at, window_days, variable, region, season, lead_days,
                                model, mae, rmse, bias, n, pod, far, csi, threshold_mm, is_weekly
                            ) VALUES %s
                            ON CONFLICT (computed_at, window_days, variable, region, season, lead_days, model, threshold_mm, is_weekly)
                            DO UPDATE
                            SET mae = EXCLUDED.mae,
                                rmse = EXCLUDED.rmse,
                                bias = EXCLUDED.bias,
                                n = EXCLUDED.n,
                                pod = EXCLUDED.pod,
                                far = EXCLUDED.far,
                                csi = EXCLUDED.csi;
                        """
                        execute_values(cur, upsert_query, records_to_insert, page_size=1000)

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
                                f"Daily verification evaluated {len(joined)} matched observations, replaced daily snapshot with {len(skill_records)} rows (Sunday weekly copy: {is_sunday}) in {duration_sec:.2f}s.",
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
            return {
                "status": "SUCCESS",
                "matched_observations": len(joined),
                "skill_scores_written": len(records_to_insert),
                "is_sunday": is_sunday,
                "candidate_models": candidates,
                "seasons_evaluated": sorted(list(joined["season"].unique())) if "season" in joined.columns else [],
                "lead_days_evaluated": sorted([int(x) for x in joined["lead_days"].unique()]) if "lead_days" in joined.columns else [],
                "eval_window": (str(start_eval_date), str(eval_date)),
                "duration_seconds": duration_sec,
            }
        finally:
            conn.close()

    def compute_skill_records(
        self,
        joined: pd.DataFrame,
        window_days: int = 60,
        computed_at: Optional[datetime] = None,
    ) -> List[Tuple[Any, ...]]:
        """Computes continuous and categorical skill records across all 8 required candidates (FR-VER-1, FR-VER-2).

        Preserves:
        - All 8 candidates: [gfs, ecmwf_ifs, icon, aifs, equal_mean, ridge, lgbm, blend]
        - Canonical Indian meteorological seasons derived per forecast valid_date
        - Lead-day correctness across 0..7 without collapsing
        """
        if computed_at is None:
            computed_at = datetime.now(timezone.utc)

        df = joined.copy()

        # Infer canonical season from forecast valid_date (FR-VER-1)
        if "valid_date" in df.columns:
            df["season"] = [get_season(d) for d in pd.to_datetime(df["valid_date"]).dt.date]
        elif "season" not in df.columns:
            raise ValueError(
                "Verification dataset must contain 'valid_date' (to derive canonical season) "
                "or an explicit 'season' column; refusing to invent or hardcode a season fallback."
            )

        skill_records: List[Tuple[Any, ...]] = []
        candidates = [c for c in CANDIDATE_MODELS if c in df.columns]

        # 1. Continuous verification metrics (FR-VER-1)
        for (var, reg, season_name, lead), grp in df.groupby(["variable", "region", "season", "lead_days"]):
            y_true = grp["truth"].to_numpy()

            for cand in candidates:
                y_pred = grp[cand].to_numpy()
                metrics = compute_metrics(forecast=y_pred, truth=y_true)

                skill_records.append((
                    computed_at,
                    window_days,
                    var,
                    reg,
                    season_name,
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
                ))

        # 2. Categorical rainfall verification (FR-VER-2)
        rain_joined = df[df["variable"] == "rain_mm"]
        if not rain_joined.empty:
            for thresh in RAINFALL_THRESHOLDS:
                for (reg, season_name, lead), grp in rain_joined.groupby(["region", "season", "lead_days"]):
                    y_true = grp["truth"].to_numpy()
                    for cand in candidates:
                        y_pred = grp[cand].to_numpy()
                        ct = compute_contingency_metrics(
                            y_true=y_true,
                            y_pred=y_pred,
                            threshold=float(thresh),
                            label=f"{thresh} mm",
                            status="operational",
                            candidate=cand,
                        )

                        skill_records.append((
                            computed_at,
                            window_days,
                            "rain_mm",
                            reg,
                            season_name,
                            int(lead),
                            cand,
                            None,
                            None,
                            None,
                            int(ct.total_samples),
                            float(ct.pod) if ct.pod is not None and not math.isnan(ct.pod) else None,
                            float(ct.far) if ct.far is not None and not math.isnan(ct.far) else None,
                            float(ct.csi) if ct.csi is not None and not math.isnan(ct.csi) else None,
                            float(thresh),
                            False,
                        ))

        return skill_records


# Global singleton
verification_runner = VerificationRunner()
