"""AAGAM — Database Retention and Nightly Backup Engine (PRD §11).

Implements authoritative PRD retention rules:
1. Expiring weight overrides past their expires_at date (active = false).
2. Purging blended forecasts older than 90 days.
3. Purging chat audit records older than 30 days.
4. Nightly export of key tables to Parquet and upload to Supabase storage `backups` bucket.
5. Telemetry logging to `pipeline_runs`.
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
        """Applies authoritative PRD retention policies to database tables."""
        started_at = datetime.now(timezone.utc)
        conn = self.get_connection()
        stats: Dict[str, int] = {}

        try:
            with conn.cursor() as cur:
                # 1. Expire weight overrides past expires_at
                stats["overrides_expired"] = self.expire_weight_overrides(dry_run=dry_run)

                # 2. blended_forecasts: retain 90 days (PRD §11)
                if dry_run:
                    cur.execute("""
                        SELECT COUNT(*) FROM blended_forecasts
                        WHERE valid_date < CURRENT_DATE - INTERVAL '90 days';
                    """)
                    stats["blended_forecasts_purged"] = cur.fetchone()[0]
                else:
                    cur.execute("""
                        DELETE FROM blended_forecasts
                        WHERE valid_date < CURRENT_DATE - INTERVAL '90 days';
                    """)
                    stats["blended_forecasts_purged"] = cur.rowcount

                # 3. chat_audit: retain 30 days (PRD §6.8, §11)
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
        failed_uploads: Dict[str, str] = {}

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
                        upload_ok = storage_manager.upload_file("backups", parquet_path, remote_path)
                        if upload_ok:
                            uploaded_files.append(remote_path)
                        else:
                            err = f"upload_file returned False for {table}"
                            logger.error(f"Backup upload failed: {err}")
                            failed_uploads[table] = err
                    except Exception as e:
                        err = f"upload_file raised exception for {table}: {e}"
                        logger.error(f"Backup upload exception: {err}")
                        failed_uploads[table] = err

            finished_at = datetime.now(timezone.utc)
            duration_sec = (finished_at - started_at).total_seconds()
            total_rows_backed_up = sum(table_stats.values())

            # Fail-safe check: If ANY upload failed, abort retention cleanup immediately!
            if failed_uploads and not dry_run:
                failed_msg = (
                    f"Nightly backup FAILED for {len(failed_uploads)} table(s): {failed_uploads}. "
                    f"Retention cleanup ABORTED to prevent data loss. "
                    f"Exported {total_rows_backed_up} rows across {len(BACKUP_TABLES)} tables in {duration_sec:.2f}s."
                )
                logger.error(failed_msg)
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
                            "FAILED",
                            total_rows_backed_up,
                            0,
                            failed_msg,
                        ),
                    )
                return {
                    "status": "FAILED",
                    "backup_date": backup_date,
                    "table_rows": table_stats,
                    "total_rows": total_rows_backed_up,
                    "uploaded_files": uploaded_files,
                    "failed_uploads": failed_uploads,
                    "cleanup_stats": None,
                    "duration_seconds": duration_sec,
                    "error": failed_msg,
                }

            # Execute retention cleanup ONLY after all table uploads successfully succeed
            cleanup_stats = self.run_cleanup(dry_run=dry_run)

            finished_at = datetime.now(timezone.utc)
            duration_sec = (finished_at - started_at).total_seconds()

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
