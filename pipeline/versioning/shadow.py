"""Durable shadow-evidence persistence and cross-run recovery (Design Doc §L).

In GitHub Actions, workflows run on ephemeral runners where local filesystems
disappear after each job execution. To guarantee that the 7-day shadow period
preserves all evaluation evidence across all 6-hourly cycles:
1. Each cycle appends its shadow forecasts to the accumulated dataset.
2. The dataset is persisted locally AND synced to durable cloud storage
   (Supabase Storage bucket 'models' under 'shadow/v{id}/shadow_v{id}.parquet').
3. When a subsequent runner spins up with an empty filesystem, it automatically
   recovers the accumulated evidence from durable storage before scoring or appending.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from pipeline.storage.manager import StorageManager, storage_manager

logger = logging.getLogger("aagam.pipeline.versioning.shadow")

SHADOW_STORAGE_BUCKET = "models"


def get_shadow_storage_path(version_id: int) -> str:
    """Returns durable cloud storage path for a candidate's shadow evidence."""
    return f"shadow/v{version_id}/shadow_v{version_id}.parquet"


def save_shadow_predictions(
    df_shadow: pd.DataFrame,
    version_id: int,
    base_dir: Path = Path("data/shadow"),
    storage_mgr: Optional[StorageManager] = None,
) -> Tuple[Path, int]:
    """Persists shadow forecasts locally and syncs to durable cloud storage.

    Recovers previous shadow evidence across ephemeral runner executions to ensure
    no data is lost during the 7-day shadow window.
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    local_path = base_dir / f"shadow_v{version_id}.parquet"
    mgr = storage_mgr or storage_manager

    # 1. Recover existing accumulated shadow data if present
    df_existing = recover_shadow_predictions(
        version_id=version_id,
        base_dir=base_dir,
        storage_mgr=mgr,
    )

    # 2. Merge and deduplicate
    if df_existing is not None and not df_existing.empty:
        df_combined = pd.concat([df_existing, df_shadow], ignore_index=True)
        dedup_cols = [c for c in ["location_id", "variable", "valid_date", "issue_time"] if c in df_combined.columns]
        if dedup_cols:
            df_combined = df_combined.drop_duplicates(subset=dedup_cols, keep="last")
    else:
        df_combined = df_shadow.copy()

    # 3. Write locally
    df_combined.to_parquet(local_path, index=False)
    total_rows = len(df_combined)

    # 4. Sync durably to cloud storage
    cloud_key = get_shadow_storage_path(version_id)
    if mgr and mgr.client:
        try:
            mgr.upload_file(
                bucket=SHADOW_STORAGE_BUCKET,
                source_path=local_path,
                target_path=cloud_key,
                content_type="application/octet-stream",
            )
            logger.info(
                f"Durably synced shadow evidence for candidate {version_id} ({total_rows} rows) "
                f"to {SHADOW_STORAGE_BUCKET}/{cloud_key}."
            )
        except Exception as e:
            logger.warning(
                f"Could not sync shadow evidence to cloud storage ({e}); local file retained."
            )

    return local_path, total_rows


def recover_shadow_predictions(
    version_id: int,
    base_dir: Path = Path("data/shadow"),
    storage_mgr: Optional[StorageManager] = None,
) -> Optional[pd.DataFrame]:
    """Recovers accumulated shadow evidence from local disk or durable cloud storage.

    Essential for ephemeral GitHub Actions runners: if local disk is empty,
    restores accumulated evidence from Supabase Storage.
    """
    local_path = base_dir / f"shadow_v{version_id}.parquet"
    mgr = storage_mgr or storage_manager

    # 1. Check local file first
    if local_path.exists():
        try:
            return pd.read_parquet(local_path)
        except Exception as e:
            logger.warning(f"Local shadow file {local_path} could not be read ({e}); attempting cloud recovery.")

    # 2. If not local, recover from durable cloud storage
    cloud_key = get_shadow_storage_path(version_id)
    if mgr and mgr.client:
        try:
            mgr.download_file(
                bucket=SHADOW_STORAGE_BUCKET,
                source_path=cloud_key,
                target_path=local_path,
            )
            if local_path.exists():
                df_recovered = pd.read_parquet(local_path)
                logger.info(
                    f"Recovered {len(df_recovered)} shadow rows for candidate {version_id} "
                    f"from durable storage {SHADOW_STORAGE_BUCKET}/{cloud_key}."
                )
                return df_recovered
        except Exception as e:
            logger.debug(f"No existing shadow evidence found in cloud storage for v{version_id}: {e}")

    return None
