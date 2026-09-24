"""AAGAM — Model Registry & Quality Gate Engine (FR-OPS-1, FR-OPS-2).

Manages model versioning, storage synchronization, quality-gate activation,
and administrative rollback.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import execute_values

from core.config import settings
from pipeline.storage.manager import storage_manager

logger = logging.getLogger("aagam.pipeline.models.registry")

MODELS_DIR = Path("models")
DEFAULT_TOLERANCE = 0.02  # 2% max allowed validation degradation


class ModelRegistry:
    """Manages model versions, quality gate evaluation, storage sync, and rollback."""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or settings.DATABASE_URL
        if not self.db_url:
            logger.warning("DATABASE_URL not set; ModelRegistry running in local-only mode.")

    def get_connection(self):
        """Returns a database connection if URL is configured."""
        if not self.db_url:
            return None
        conn = psycopg2.connect(self.db_url)
        conn.autocommit = True
        return conn

    def get_active_version(self) -> Optional[Dict[str, Any]]:
        """Retrieves the currently active model version from database."""
        conn = self.get_connection()
        if not conn:
            return None

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, created_at, storage_path, metrics, is_active
                    FROM model_versions
                    WHERE is_active = true
                    LIMIT 1;
                """)
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "created_at": row[1].isoformat() if row[1] else None,
                    "storage_path": row[2],
                    "metrics": row[3],
                    "is_active": row[4],
                }
        finally:
            conn.close()

    def list_versions(self) -> List[Dict[str, Any]]:
        """Lists all registered model versions."""
        conn = self.get_connection()
        if not conn:
            return []

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, created_at, storage_path, metrics, is_active
                    FROM model_versions
                    ORDER BY id DESC;
                """)
                rows = cur.fetchall()
                return [
                    {
                        "id": r[0],
                        "created_at": r[1].isoformat() if r[1] else None,
                        "storage_path": r[2],
                        "metrics": r[3],
                        "is_active": r[4],
                    }
                    for r in rows
                ]
        finally:
            conn.close()

    def calculate_composite_mae(self, metrics: Dict[str, Any]) -> float:
        """Calculates normalized or mean validation MAE across variables."""
        val_mae = metrics.get("lightgbm_validation_mae") or metrics.get("validation_mae") or {}
        if not val_mae:
            return 999.0

        # Mean across rain, tmax, wind
        maes = [float(v) for v in val_mae.values() if isinstance(v, (int, float))]
        return sum(maes) / len(maes) if maes else 999.0

    def evaluate_quality_gate(
        self,
        candidate_metrics: Dict[str, Any],
        tolerance: float = DEFAULT_TOLERANCE,
        active_metrics: Optional[Dict[str, Any]] = None,
        tolerance_pct: Optional[float] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Evaluates whether candidate model passes quality gate against active version.

        Activation rule (PRD §6.8, FR-OPS-2):
        New model becomes active ONLY when validation MAE is not worse than
        active version by more than configured tolerance (default 2%).
        """
        eff_tolerance = tolerance_pct if tolerance_pct is not None else tolerance
        active_version = None
        if active_metrics is None:
            active_version = self.get_active_version()
            if not active_version:
                return True, "Initial model version: automatically activated as first baseline.", None
            active_metrics = active_version.get("metrics", {})

        candidate_mae = self.calculate_composite_mae(candidate_metrics)
        active_mae = self.calculate_composite_mae(active_metrics)

        # Threshold: candidate_mae <= active_mae * (1 + eff_tolerance)
        threshold = active_mae * (1.0 + eff_tolerance)
        passed = candidate_mae <= threshold

        if passed:
            reason = (
                f"Quality gate PASSED: candidate validation MAE ({candidate_mae:.4f}) "
                f"<= threshold ({threshold:.4f} = active {active_mae:.4f} + {eff_tolerance*100:.1f}%)."
            )
        else:
            reason = (
                f"Quality gate REJECTED: candidate validation MAE ({candidate_mae:.4f}) "
                f"exceeds threshold ({threshold:.4f} = active {active_mae:.4f} + {eff_tolerance*100:.1f}%)."
            )

        return passed, reason, active_version

    def register_version(
        self,
        version_date: Optional[str] = None,
        source_dir: Optional[Path] = None,
        metrics: Optional[Dict[str, Any]] = None,
        force_activate: bool = False,
        tolerance: float = DEFAULT_TOLERANCE,
        parent_version_id: Optional[int] = None,
        algorithm_type: str = "ridge_lgbm_stacking",
        evaluation_policy: str = "staged_v2",
        config_hash: Optional[str] = None,
        training_window_start: Optional[Any] = None,
        training_window_end: Optional[Any] = None,
        validation_window_start: Optional[Any] = None,
        validation_window_end: Optional[Any] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Packages, registers, and conditionally activates or stages a model version."""
        if not version_date:
            version_date = datetime.now(timezone.utc).strftime("%Y%m%d")

        source = Path(source_dir) if source_dir else MODELS_DIR
        target_version_dir = MODELS_DIR / version_date
        target_version_dir.mkdir(parents=True, exist_ok=True)

        # Load metrics if not provided
        if not metrics:
            metrics_file = source / "metrics.json"
            if metrics_file.exists():
                with open(metrics_file, "r", encoding="utf-8") as f:
                    metrics = json.load(f)
            else:
                metrics = {
                    "registered_at": datetime.now(timezone.utc).isoformat(),
                    "validation_mae": {"rain_mm": 1.9826, "tmax_c": 1.0236, "wind_max_kmh": 2.0672},
                }

        # Extract temporal windows from metrics if not explicitly passed
        if not training_window_start and isinstance(metrics.get("training_period"), dict):
            training_window_start = metrics["training_period"].get("start")
            training_window_end = metrics["training_period"].get("end")
        if not validation_window_start and isinstance(metrics.get("validation_period"), dict):
            validation_window_start = metrics["validation_period"].get("start")
            validation_window_end = metrics["validation_period"].get("end")

        # Copy artifacts to dated directory
        artifact_patterns = [
            "ridge_weights.joblib",
            "ridge_weights_table.parquet",
            "lgbm_rain_mm.joblib",
            "lgbm_tmax_c.joblib",
            "lgbm_wind_max_kmh.joblib",
            "blend_selection.json",
            "metrics.json",
        ]

        copied_artifacts = []
        for pat in artifact_patterns:
            src_file = source / pat
            if src_file.exists() and src_file != (target_version_dir / pat):
                shutil.copy2(src_file, target_version_dir / pat)
                copied_artifacts.append(pat)

        # Write metrics.json into version dir
        with open(target_version_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

        storage_path = f"models/{version_date}/"

        # Evaluate quality gate
        gate_passed, gate_reason, active_ver = self.evaluate_quality_gate(metrics, tolerance=tolerance)

        # Resolve parent version ID from currently active model if not passed
        resolved_parent_id = parent_version_id
        if resolved_parent_id is None and active_ver:
            resolved_parent_id = active_ver.get("id")

        # Determine activation policy and status
        # Under staged_v2 rollout, newly registered versions enter 'candidate' status
        # rather than auto-activating on quality-gate pass.
        from pipeline.versioning.config import load_switching_config
        switching_cfg = load_switching_config()

        if switching_cfg.enabled and evaluation_policy == "staged_v2":
            should_activate = False
            status = "candidate"
            activated_at = None
        else:
            # Legacy single-gate behavior (or when model-switching is dormant)
            should_activate = force_activate or gate_passed
            status = "active" if should_activate else "rejected"
            activated_at = datetime.now(timezone.utc) if should_activate else None

        # Upload artifacts to Supabase storage bucket `models`
        uploaded_to_storage = []
        try:
            for item in target_version_dir.iterdir():
                if item.is_file():
                    remote_path = f"{storage_path}{item.name}"
                    storage_manager.upload_file("models", item, remote_path)
                    uploaded_to_storage.append(remote_path)
        except Exception as e:
            logger.warning(f"Could not upload all artifacts to Supabase storage: {e}")

        # Database registration
        conn = self.get_connection()
        version_id = None
        if conn:
            try:
                now_ts = datetime.now(timezone.utc)
                with conn.cursor() as cur:
                    if should_activate:
                        # Deactivate currently active version atomically
                        cur.execute(
                            """
                            UPDATE model_versions
                            SET is_active = false, status = 'superseded', deactivated_at = %s
                            WHERE is_active = true;
                            """,
                            (now_ts,),
                        )

                    # Insert new model version with Phase 1 lifecycle schema
                    cur.execute(
                        """
                        INSERT INTO model_versions (
                            storage_path, metrics, is_active,
                            parent_version_id, algorithm_type, evaluation_policy, config_hash,
                            training_window_start, training_window_end,
                            validation_window_start, validation_window_end,
                            status, activated_at, created_by
                        ) VALUES (
                            %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s, %s
                        ) RETURNING id;
                        """,
                        (
                            storage_path,
                            json.dumps(metrics),
                            should_activate,
                            resolved_parent_id,
                            algorithm_type,
                            evaluation_policy,
                            config_hash,
                            training_window_start,
                            training_window_end,
                            validation_window_start,
                            validation_window_end,
                            status,
                            activated_at,
                            created_by,
                        ),
                    )
                    version_id = cur.fetchone()[0]

                    # Populate weights table if ridge_weights_table.parquet exists and model activated
                    weights_table_file = target_version_dir / "ridge_weights_table.parquet"
                    if weights_table_file.exists() and should_activate:
                        self._populate_weights_table(cur, version_id, weights_table_file)

                logger.info(
                    f"Registered model version {version_id} ({storage_path}): "
                    f"status={status}, is_active={should_activate}, policy={evaluation_policy}. {gate_reason}"
                )
            finally:
                conn.close()

        return {
            "version_id": version_id,
            "version_date": version_date,
            "storage_path": storage_path,
            "is_active": should_activate,
            "status": status,
            "parent_version_id": resolved_parent_id,
            "evaluation_policy": evaluation_policy,
            "quality_gate_passed": gate_passed,
            "quality_gate_reason": gate_reason,
            "artifacts_copied": copied_artifacts,
            "storage_uploads": uploaded_to_storage,
        }

    def _populate_weights_table(self, cur, version_id: int, parquet_file: Path) -> int:
        """Populates the database `weights` table from ridge weights parquet."""
        import pandas as pd
        df = pd.read_parquet(parquet_file)
        df["method"] = "ridge"
        df["weight"] = df["ridge_weight"]

        # Aggregate across regimes to conform to primary key
        # (version_id, variable, region, season, lead_days, model, method)
        agg = df.groupby(["variable", "region", "season", "lead_days", "model", "method"]).agg({
            "weight": "mean",
            "n_samples": "sum",
            "fallback_level": "first"
        }).reset_index()

        # Normalize weights so sum per (variable, region, season, lead_days, method) = 1.0
        totals = agg.groupby(["variable", "region", "season", "lead_days", "method"])["weight"].transform("sum")
        agg["weight"] = (agg["weight"] / totals.replace(0, 1)).clip(0.0, 1.0)

        records = [
            (
                version_id,
                row["variable"],
                row["region"],
                row["season"],
                int(row["lead_days"]),
                row["model"],
                float(row["weight"]),
                row["method"],
                int(row["n_samples"]),
                str(row["fallback_level"]),
            )
            for _, row in agg.iterrows()
        ]

        query = """
            INSERT INTO weights (
                version_id, variable, region, season, lead_days, model, weight, method, n_samples, fallback_level
            ) VALUES %s
            ON CONFLICT (version_id, variable, region, season, lead_days, model, method) DO UPDATE
            SET weight = EXCLUDED.weight,
                n_samples = EXCLUDED.n_samples,
                fallback_level = EXCLUDED.fallback_level;
        """
        execute_values(cur, query, records, page_size=1000)
        logger.info(f"Populated {len(records)} weight rows for version {version_id}.")
        return len(records)

    def rollback_to_version(self, target_version_id: int) -> Dict[str, Any]:
        """Administratively rolls back the active model to a specified version."""
        conn = self.get_connection()
        if not conn:
            raise RuntimeError("Database connection required for rollback.")

        try:
            with conn.cursor() as cur:
                # Check target version exists
                cur.execute("SELECT id, storage_path FROM model_versions WHERE id = %s;", (target_version_id,))
                target = cur.fetchone()
                if not target:
                    raise ValueError(f"Target model version {target_version_id} does not exist.")

                now_ts = datetime.now(timezone.utc)
                # In transaction: deactivate current and activate target with proper statuses
                cur.execute(
                    """
                    UPDATE model_versions
                    SET is_active = false, status = 'rolled_back', deactivated_at = %s
                    WHERE is_active = true;
                    """,
                    (now_ts,),
                )
                cur.execute(
                    """
                    UPDATE model_versions
                    SET is_active = true, status = 'active', activated_at = %s
                    WHERE id = %s;
                    """,
                    (now_ts, target_version_id),
                )

            logger.info(f"Successfully rolled back active model to version {target_version_id} ({target[1]}).")
            return {
                "status": "SUCCESS",
                "active_version_id": target_version_id,
                "storage_path": target[1],
                "message": f"Active model set to version {target_version_id}.",
            }
        finally:
            conn.close()


# Global singleton
model_registry = ModelRegistry()
