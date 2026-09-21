"""AAGAM — Database Retention and Nightly Backup Engine (PRD §11).

Implements:
1. Expiring weight overrides past their expires_at date.
2. Cleaning blended forecasts older than 180 days (storing only 00Z runs).
3. Purging non-weekly skill scores older than today, and weekly scores older than 26 weeks.
4. Purging chat audits older than 30 days.
5. Nightly export of key tables to Parquet and upload to Supabase storage `backups` bucket.
6. Telemetry logging to `pipeline_runs`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import psycopg2

from core.config import settings
from pipeline.storage.manager import storage_manager

logger = logging.getLogger("aagam.pipeline.retention")

BACKUP_TABLES = [
    "model_forecasts",
    "blended_forecasts",
    "alerts",
    "skill_scores",
    "weights",
    "pipeline_runs",
]


class RetentionEngine:
    """Manages data retention policies and nightly backup exports."""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or settings.DATABASE_URL

    def get_connection(self):
        if not self.db_url:
            raise RuntimeError("DATABASE_URL is not set.")
        conn = psycopg2.connect(self.db_url)
        conn.autocommit = True
        return conn

    def expire_weight_overrides(self, dry_run: bool = False) -> int:
        """Deactivates weight overrides where expires_at has passed."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                if dry_run:
                    cur.execute("""
                        SELECT COUNT(*) FROM weight_overrides
                        WHERE active = true AND expires_at IS NOT NULL AND expires_at < NOW();
                    """)
                    count = cur.fetchone()[0]
                    logger.info(f"[Dry Run] Overrides eligible for expiry: {count}")
                    return count

                cur.execute("""
                    UPDATE weight_overrides
                    SET active = false
                    WHERE active = true
                      AND expires_at IS NOT NULL
                      AND expires_at < NOW();
                """)
                count = cur.rowcount
                logger.info(f"Expired {count} weight overrides.")
                return count
        finally:
            conn.close()

    def run_cleanup(self, dry_run: bool = False) -> Dict[str, int]:
        """Applies all PRD §11 retention policies to database tables."""
        started_at = datetime.now(timezone.utc)
        conn = self.get_connection()
        stats: Dict[str, int] = {}

        try:
            with conn.cursor() as cur:
                # 1. Expire weight overrides
                stats["overrides_expired"] = self.expire_weight_overrides(dry_run=dry_run)

                # 2. blended_forecasts: keep 180 days, storing only 00Z runs
                # Purge non-00Z runs older than 180 days
                if dry_run:
                    cur.execute("""
                        SELECT COUNT(*) FROM blended_forecasts
                        WHERE valid_date < CURRENT_DATE - INTERVAL '180 days'
                          AND EXTRACT(HOUR FROM issue_time) != 0;
                    """)
                    stats["blended_forecasts_purged"] = cur.fetchone()[0]
                else:
                    cur.execute("""
                        DELETE FROM blended_forecasts
                        WHERE valid_date < CURRENT_DATE - INTERVAL '180 days'
                          AND EXTRACT(HOUR FROM issue_time) != 0;
                    """)
                    stats["blended_forecasts_purged"] = cur.rowcount

                # 3. skill_scores:
                # delete is_weekly = false with computed_at before today
                # delete is_weekly = true older than 26 weeks
                if dry_run:
                    cur.execute("""
                        SELECT COUNT(*) FROM skill_scores
                        WHERE (is_weekly = false AND computed_at < CURRENT_DATE)
                           OR (is_weekly = true AND computed_at < NOW() - INTERVAL '26 weeks');
                    """)
                    stats["skill_scores_purged"] = cur.fetchone()[0]
                else:
                    cur.execute("""
                        DELETE FROM skill_scores
                        WHERE (is_weekly = false AND computed_at < CURRENT_DATE)
                           OR (is_weekly = true AND computed_at < NOW() - INTERVAL '26 weeks');
                    """)
                    stats["skill_scores_purged"] = cur.rowcount

                # 4. chat_audit: delete older than 30 days
                if dry_run:
                    cur.execute("""
                        SELECT COUNT(*) FROM chat_audit
                        WHERE created_at < NOW() - INTERVAL '30 days';
                    """)
                    stats["chat_audit_purged"] = cur.fetchone()[0]
                else:
                    cur.execute("""
                        DELETE FROM chat_audit
                        WHERE created_at < NOW() - INTERVAL '30 days';
                    """)
                    stats["chat_audit_purged"] = cur.rowcount

                finished_at = datetime.now(timezone.utc)
                duration_sec = (finished_at - started_at).total_seconds()

                if not dry_run:
                    total_purged = sum(stats.values())
                    cur.execute(
                        """
                        INSERT INTO pipeline_runs (job, started_at, finished_at, status, rows_written, api_calls_est, message)
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            "retention_cleanup",
                            started_at,
                            finished_at,
                            "SUCCESS",
                            total_purged,
                            0,
                            f"Cleaned {total_purged} expired/stale records in {duration_sec:.2f}s: {stats}",
                        ),
                    )

            logger.info(f"Retention cleanup finished: {stats}")
            return stats
        finally:
            conn.close()

    def run_nightly_backup(
        self,
        backup_date: Optional[str] = None,
        dry_run: bool = False,
        local_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Exports key database tables to Parquet and uploads to storage bucket `backups`."""
        started_at = datetime.now(timezone.utc)
        if not backup_date:
            backup_date = started_at.strftime("%Y%m%d")

        export_dir = local_dir or (Path("data/backups") / backup_date)
        export_dir.mkdir(parents=True, exist_ok=True)

        conn = self.get_connection()
        table_stats: Dict[str, int] = {}
        uploaded_files: List[str] = []

        try:
            for table in BACKUP_TABLES:
                logger.info(f"Exporting table '{table}' to Parquet...")
                query = f"SELECT * FROM {table};"
                with conn.cursor() as cur:
                    cur.execute(query)
                    rows = cur.fetchall()
                    cols = [desc[0] for desc in cur.description] if cur.description else []
                    df = pd.DataFrame(rows, columns=cols)
                table_stats[table] = len(df)

                parquet_path = export_dir / f"{table}.parquet"
                df.to_parquet(parquet_path, index=False)
                logger.info(f"Exported {len(df)} rows from {table} to {parquet_path}")

                if not dry_run:
                    remote_path = f"backups/{backup_date}/{table}.parquet"
                    try:
                        storage_manager.upload_file("backups", parquet_path, remote_path)
                        uploaded_files.append(remote_path)
                    except Exception as e:
                        logger.warning(f"Could not upload {table}.parquet to backups storage: {e}")

            # Execute retention cleanup after backup
            cleanup_stats = self.run_cleanup(dry_run=dry_run)

            finished_at = datetime.now(timezone.utc)
            duration_sec = (finished_at - started_at).total_seconds()
            total_rows_backed_up = sum(table_stats.values())

            if not dry_run:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO pipeline_runs (job, started_at, finished_at, status, rows_written, api_calls_est, message)
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            "backup_nightly",
                            started_at,
                            finished_at,
                            "SUCCESS",
                            total_rows_backed_up,
                            0,
                            f"Nightly backup exported {total_rows_backed_up} rows across {len(BACKUP_TABLES)} tables in {duration_sec:.2f}s. Uploaded {len(uploaded_files)} files to storage.",
                        ),
                    )

            return {
                "status": "SUCCESS",
                "backup_date": backup_date,
                "table_rows": table_stats,
                "total_rows": total_rows_backed_up,
                "uploaded_files": uploaded_files,
                "cleanup_stats": cleanup_stats,
                "duration_seconds": duration_sec,
            }
        finally:
            conn.close()


# Global singleton
retention_engine = RetentionEngine()
