"""AAGAM — Supabase Storage Manager.

Manages the three required Supabase storage buckets:
- training-data: joined training Parquet Jan 2024 -> latest available date
- models: models/{yyyymmdd}/ridge.joblib, lgbm_*.txt, metrics.json
- backups: nightly Parquet exports of key database tables
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import settings
from supabase import Client, create_client

logger = logging.getLogger("aagam.pipeline.storage")

REQUIRED_BUCKETS = ["training-data", "models", "backups"]


class StorageManager:
    """Manages cloud storage operations for AAGAM."""

    def __init__(self, client: Optional[Client] = None):
        if client:
            self.client = client
        elif settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
            self.client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        else:
            self.client = None
            logger.warning("Supabase credentials not configured; StorageManager operating in offline mode.")

    def ensure_buckets(self) -> List[str]:
        """Ensures all required buckets exist in Supabase storage."""
        if not self.client:
            return REQUIRED_BUCKETS

        existing_buckets = {b.name for b in self.client.storage.list_buckets()}
        created = []
        for bucket_name in REQUIRED_BUCKETS:
            if bucket_name not in existing_buckets:
                try:
                    self.client.storage.create_bucket(bucket_name, options={"public": False})
                    logger.info(f"Created Supabase storage bucket: {bucket_name}")
                    created.append(bucket_name)
                except Exception as e:
                    logger.warning(f"Could not create bucket '{bucket_name}': {e}")
            else:
                logger.debug(f"Bucket '{bucket_name}' already exists.")
        return list(existing_buckets.union(created))

    def list_buckets(self) -> List[str]:
        """Returns list of bucket names."""
        if not self.client:
            return REQUIRED_BUCKETS
        try:
            return [b.name for b in self.client.storage.list_buckets()]
        except Exception as e:
            logger.warning(f"Could not list buckets: {e}")
            return REQUIRED_BUCKETS

    def upload_file(
        self,
        bucket: str,
        source_path: Path | str,
        target_path: str,
        content_type: str = "application/octet-stream",
    ) -> bool:
        """Uploads a local file to the specified Supabase storage bucket."""
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source file does not exist: {source}")

        if not self.client:
            logger.warning(f"Offline mode: skipping upload of {source} to {bucket}/{target_path}")
            return False

        with open(source, "rb") as f:
            file_data = f.read()

        target_str = str(target_path).replace("\\", "/")
        try:
            # Try to upload with file_options upsert = True
            self.client.storage.from_(bucket).upload(
                path=target_str,
                file=file_data,
                file_options={"content-type": content_type, "upsert": "true"},
            )
            logger.info(f"Successfully uploaded {source.name} to {bucket}/{target_str}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload {source} to {bucket}/{target_str}: {e}")
            raise

    def upload_bytes(
        self,
        bucket: str,
        data: bytes,
        target_path: str,
        content_type: str = "application/octet-stream",
    ) -> bool:
        """Uploads in-memory bytes to the specified storage bucket."""
        if not self.client:
            logger.warning(f"Offline mode: skipping byte upload to {bucket}/{target_path}")
            return False

        target_str = str(target_path).replace("\\", "/")
        try:
            self.client.storage.from_(bucket).upload(
                path=target_str,
                file=data,
                file_options={"content-type": content_type, "upsert": "true"},
            )
            logger.info(f"Successfully uploaded bytes ({len(data)} B) to {bucket}/{target_str}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload bytes to {bucket}/{target_str}: {e}")
            raise

    def download_file(self, bucket: str, source_path: str, target_path: Path | str) -> Path:
        """Downloads a file from Supabase storage to a local path."""
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if not self.client:
            raise RuntimeError("Storage client not available for download.")

        source_str = str(source_path).replace("\\", "/")
        response = self.client.storage.from_(bucket).download(source_str)
        with open(target, "wb") as f:
            f.write(response)
        logger.info(f"Downloaded {bucket}/{source_str} to {target}")
        return target

    def list_files(self, bucket: str, prefix: str = "") -> List[Dict[str, Any]]:
        """Lists files within a storage bucket."""
        if not self.client:
            return []
        prefix_str = str(prefix).replace("\\", "/")
        try:
            return self.client.storage.from_(bucket).list(prefix_str)
        except Exception as e:
            logger.warning(f"Failed to list files in {bucket}/{prefix_str}: {e}")
            return []


# Global singleton
storage_manager = StorageManager()
