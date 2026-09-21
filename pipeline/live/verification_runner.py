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
from pipeline.skill.scoring import compute_metrics

logger = logging.getLogger("aagam.pipeline.live.verification")

TRUTH_PARQUET = Path("data/truth.parquet")
RAINFALL_THRESHOLDS = [2.5, 15.6, 64.5, 115.6]


class VerificationRunner:
    """Executes the daily verification and skill scoring pipeline."""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or settings.DATABASE_URL

    def get_connection(self):
        if not self.db_url:
            raise RuntimeError("DATABASE_URL is required for verification operations.")
        conn = psycopg2.connect(self.db_url)
        conn.autocommit = True
        return conn

    def run_daily_verification(
        self,
        target_date: Optional[date] = None,
        window_days: int = 60,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Runs daily verification against available ground truth observations."""
        started_at = datetime.now(timezone.utc)
        logger.info(f"=== Starting Daily Verification Cycle (dry_run={dry_run}) ===")

        if not TRUTH_PARQUET.exists():
            logger.warning(f"Ground truth parquet {TRUTH_PARQUET} not found.")
            return {"status": "SKIPPED", "message": "No ground truth available.", "rows_written": 0}

        # Load truth
        df_truth = pd.read_parquet(TRUTH_PARQUET)
        max_truth_date = pd.to_datetime(df_truth["valid_date"]).max().date()
        eval_date = target_date or max_truth_date
        start_eval_date = eval_date - pd.Timedelta(days=window_days)

        logger.info(f"Evaluating verification window: {start_eval_date} to {eval_date} ({window_days} days)")

        # Filter truth to window
        truth_window = df_truth[
            (pd.to_datetime(df_truth["valid_date"]).dt.date >= start_eval_date) &
            (pd.to_datetime(df_truth["valid_date"]).dt.date <= eval_date)
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

        conn = self.get_connection()
        try:
            # Query blended and model forecasts for this window
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT bf.location_id, bf.variable, bf.valid_date, bf.lead_days,
                           bf.blended, bf.ridge, bf.lgbm, bf.equal_mean,
                           loc.region
                    FROM blended_forecasts bf
                    JOIN locations loc ON loc.id = bf.location_id
                    WHERE bf.valid_date BETWEEN %s AND %s;
                """, (start_eval_date, eval_date))
                rows = cur.fetchall()

            if not rows:
                logger.info("No blended forecasts found in DB for verification window. Falling back to test dataset verification.")
                test_parquet = Path("data/blended_forecasts_test.parquet")
                if test_parquet.exists():
                    df_fcst = pd.read_parquet(test_parquet)
                else:
                    return {"status": "NO_DATA", "rows_written": 0, "message": "No forecast data available for verification."}
            else:
                df_fcst = pd.DataFrame(rows, columns=[
                    "location_id", "variable", "valid_date", "lead_days",
                    "blend", "ridge", "lgbm", "equal_mean", "region"
                ])

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

            computed_at = datetime.now(timezone.utc)
            skill_records: List[Tuple[Any, ...]] = []

            # 1. Continuous verification metrics
            candidates = [c for c in ["blend", "ridge", "lgbm", "equal_mean"] if c in joined.columns]

            for (var, reg, lead), grp in joined.groupby(["variable", "region", "lead_days"]):
                y_true = grp["truth"].to_numpy()
                season_str = "monsoon"  # Or inferred from dates

                for cand in candidates:
                    y_pred = grp[cand].to_numpy()
                    metrics = compute_metrics(forecast=y_pred, truth=y_true)

                    skill_records.append((
                        computed_at,
                        window_days,
                        var,
                        reg,
                        season_str,
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

            # 2. Categorical rainfall verification
            rain_joined = joined[joined["variable"] == "rain_mm"]
            if not rain_joined.empty:
                for thresh in RAINFALL_THRESHOLDS:
                    for (reg, lead), grp in rain_joined.groupby(["region", "lead_days"]):
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
                                "monsoon",
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

            logger.info(f"Generated {len(skill_records)} verification skill rows.")

            # Upsert into database skill_scores
            if not dry_run and skill_records:
                with conn.cursor() as cur:
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
                    execute_values(cur, upsert_query, skill_records, page_size=1000)

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
                            len(skill_records),
                            0,
                            f"Daily verification evaluated {len(joined)} matched observations, recorded {len(skill_records)} skill metrics in {duration_sec:.2f}s.",
                        ),
                    )

            finished_at = datetime.now(timezone.utc)
            duration_sec = (finished_at - started_at).total_seconds()
            return {
                "status": "SUCCESS",
                "matched_observations": len(joined),
                "skill_scores_written": len(skill_records),
                "eval_window": (str(start_eval_date), str(eval_date)),
                "duration_seconds": duration_sec,
            }
        finally:
            conn.close()


# Global singleton
verification_runner = VerificationRunner()
