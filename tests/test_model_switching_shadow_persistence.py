"""
AAGAM — Shadow Evidence Cross-Runner Persistence Tests (CHECK 2).

Authoritative source: AAGAM_MODEL_VERSIONING_DESIGN.md §L, §S
                      AAGAM_MODEL_VERSIONING_ANTIGRAVITY_SPEC.md Phase 3

Validates that shadow evaluation evidence survives across separate GitHub Actions
runner executions where local filesystems are ephemeral and destroyed upon job completion.

Simulates:
Run A -> write shadow evidence to local runner + sync to durable storage
Runner A disappears (filesystem deleted)
Run B -> recover previous shadow evidence from durable storage, append new cycle data
Runner B disappears (filesystem deleted)
Run C -> recover complete accumulated shadow evidence, finish scoring
Final shadow evaluation uses ALL required multi-run evidence. Zero data lost!
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from pipeline.versioning.shadow import (
    SHADOW_STORAGE_BUCKET,
    get_shadow_storage_path,
    recover_shadow_predictions,
    save_shadow_predictions,
)


class MockCloudStorageClient:
    """Simulates durable Supabase cloud storage bucket for ephemeral runner testing."""

    def __init__(self):
        self.store: Dict[str, Dict[str, bytes]] = {SHADOW_STORAGE_BUCKET: {}}

    def from_(self, bucket: str):
        class BucketOps:
            def __init__(self, parent: MockCloudStorageClient, bucket_name: str):
                self.parent = parent
                self.bucket = bucket_name

            def upload(self, path: str, file: bytes, file_options: Dict[str, Any] = None):
                self.parent.store.setdefault(self.bucket, {})[path] = file
                return {"path": path}

            def download(self, path: str) -> bytes:
                if path not in self.parent.store.get(self.bucket, {}):
                    raise FileNotFoundError(f"Key {path} not found in bucket {self.bucket}")
                return self.parent.store[self.bucket][path]

            def list(self, prefix: str = ""):
                return [{"name": k} for k in self.parent.store.get(self.bucket, {}).keys() if k.startswith(prefix)]

        return BucketOps(self, bucket)


class MockDurableStorageManager:
    """Wraps MockCloudStorageClient to provide the StorageManager interface."""

    def __init__(self):
        self.client = MockCloudStorageClient()

    def upload_file(self, bucket: str, source_path: Path | str, target_path: str, content_type: str = "application/octet-stream") -> bool:
        with open(source_path, "rb") as f:
            data = f.read()
        self.client.from_(bucket).upload(target_path, data)
        return True

    def download_file(self, bucket: str, source_path: str, target_path: Path | str) -> Path:
        data = self.client.from_(bucket).download(source_path)
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        return target


def create_sample_shadow_dataframe(version_id: int, cycle_offset: int) -> pd.DataFrame:
    """Generates synthetic forecast predictions for a 6-hourly cycle (20 distinct forecasts)."""
    rows = []
    for loc_id in range(1, 6):
        for var in ["rain_mm", "tmax_c"]:
            for lead_day in [1, 2]:
                rows.append(
                    {
                        "location_id": loc_id,
                        "variable": var,
                        "valid_date": f"2026-10-0{lead_day}",
                        "issue_time": f"2026-10-01 {cycle_offset:02d}:00:00",
                        "lead_days": lead_day,
                        "blended": 12.5 + loc_id,
                        "ridge": 11.0 + loc_id,
                        "lgbm": 13.0 + loc_id,
                        "equal_mean": 12.0 + loc_id,
                        "spread": 1.5,
                        "models_over_threshold": 1,
                        "degraded": False,
                        "version_id": version_id,
                    }
                )
    return pd.DataFrame(rows)


class TestShadowEvidencePersistenceAcrossRunners:
    """Proves shadow evidence durability across independent, ephemeral GitHub Actions runners."""

    def test_shadow_evidence_survives_runner_destruction(self, tmp_path):
        """Case: Run A -> wipe runner -> Run B -> wipe runner -> Run C -> complete scoring.

        Verifies that all evidence accumulates across runners with zero loss.
        """
        cloud_storage = MockDurableStorageManager()
        candidate_version_id = 3

        # =====================================================================
        # 1. RUN A: Initial runner execution (Day 1, Cycle 1)
        # =====================================================================
        runner_a_dir = tmp_path / "runner_a_fs" / "data" / "shadow"
        df_run_a = create_sample_shadow_dataframe(candidate_version_id, cycle_offset=0)

        path_a, total_a = save_shadow_predictions(
            df_shadow=df_run_a,
            version_id=candidate_version_id,
            base_dir=runner_a_dir,
            storage_mgr=cloud_storage,
        )
        assert path_a.exists()
        assert total_a == 20
        assert len(pd.read_parquet(path_a)) == 20

        # Verify cloud storage received the object
        expected_cloud_key = get_shadow_storage_path(candidate_version_id)
        assert expected_cloud_key in cloud_storage.client.store[SHADOW_STORAGE_BUCKET]

        # SIMULATE RUNNER A TERMINATION / DISAPPEARANCE:
        # Ephemeral runner filesystem is completely deleted!
        shutil.rmtree(tmp_path / "runner_a_fs")
        assert not runner_a_dir.exists()

        # =====================================================================
        # 2. RUN B: Second runner execution (Day 1, Cycle 2, 6 hours later)
        # =====================================================================
        runner_b_dir = tmp_path / "runner_b_fs" / "data" / "shadow"
        assert not runner_b_dir.exists()  # Clean filesystem on new VM

        df_run_b = create_sample_shadow_dataframe(candidate_version_id, cycle_offset=6)

        path_b, total_b = save_shadow_predictions(
            df_shadow=df_run_b,
            version_id=candidate_version_id,
            base_dir=runner_b_dir,
            storage_mgr=cloud_storage,
        )
        assert path_b.exists()
        # Must have recovered Run A's 20 rows and appended Run B's 20 rows = 40 rows
        assert total_b == 40
        df_loaded_b = pd.read_parquet(path_b)
        assert len(df_loaded_b) == 40
        assert set(df_loaded_b["issue_time"]) == {"2026-10-01 00:00:00", "2026-10-01 06:00:00"}

        # SIMULATE RUNNER B TERMINATION / DISAPPEARANCE:
        shutil.rmtree(tmp_path / "runner_b_fs")
        assert not runner_b_dir.exists()

        # =====================================================================
        # 3. RUN C: Third runner execution (Day 1, Cycle 3, 12 hours later)
        # =====================================================================
        runner_c_dir = tmp_path / "runner_c_fs" / "data" / "shadow"
        assert not runner_c_dir.exists()  # Clean filesystem on third VM

        df_run_c = create_sample_shadow_dataframe(candidate_version_id, cycle_offset=12)

        path_c, total_c = save_shadow_predictions(
            df_shadow=df_run_c,
            version_id=candidate_version_id,
            base_dir=runner_c_dir,
            storage_mgr=cloud_storage,
        )
        assert path_c.exists()
        # 40 recovered + 20 new = 60 rows
        assert total_c == 60
        df_loaded_c = pd.read_parquet(path_c)
        assert len(df_loaded_c) == 60

        # =====================================================================
        # 4. FINAL SCORING RECOVERY: Simulating end of 7-day shadow window
        # =====================================================================
        # Even on yet another fresh runner D with zero local files:
        runner_eval_dir = tmp_path / "runner_eval_fs" / "data" / "shadow"
        assert not runner_eval_dir.exists()

        df_final_evidence = recover_shadow_predictions(
            version_id=candidate_version_id,
            base_dir=runner_eval_dir,
            storage_mgr=cloud_storage,
        )
        assert df_final_evidence is not None
        assert len(df_final_evidence) == 60
        # All 3 issue times present and intact
        assert set(df_final_evidence["issue_time"]) == {
            "2026-10-01 00:00:00",
            "2026-10-01 06:00:00",
            "2026-10-01 12:00:00",
        }
        assert all(df_final_evidence["version_id"] == candidate_version_id)

    def test_save_shadow_predictions_upload_exception_retains_local_file(self, tmp_path):
        """If cloud upload fails, local file is still saved and function succeeds gracefully."""
        class FailingStorageManager:
            def __init__(self):
                self.client = object()

            def upload_file(self, *args, **kwargs):
                raise RuntimeError("Cloud connection error")

        fs_dir = tmp_path / "shadow"
        df = create_sample_shadow_dataframe(version_id=4, cycle_offset=0)
        local_path, total_rows = save_shadow_predictions(
            df_shadow=df,
            version_id=4,
            base_dir=fs_dir,
            storage_mgr=FailingStorageManager(),
        )
        assert local_path.exists()
        assert total_rows == 20

    def test_recover_shadow_predictions_corrupted_local_falls_back_to_cloud(self, tmp_path):
        """If local parquet file is corrupted, it attempts to recover from cloud storage."""
        cloud_storage = MockDurableStorageManager()
        df = create_sample_shadow_dataframe(version_id=5, cycle_offset=0)
        # Upload valid copy to cloud
        cloud_key = get_shadow_storage_path(5)
        local_temp = tmp_path / "temp.parquet"
        df.to_parquet(local_temp)
        cloud_storage.upload_file(SHADOW_STORAGE_BUCKET, local_temp, cloud_key)

        # Corrupt the local file
        fs_dir = tmp_path / "shadow"
        fs_dir.mkdir(parents=True, exist_ok=True)
        corrupted_file = fs_dir / "shadow_v5.parquet"
        corrupted_file.write_bytes(b"NOT_A_VALID_PARQUET_FILE")

        df_recovered = recover_shadow_predictions(
            version_id=5,
            base_dir=fs_dir,
            storage_mgr=cloud_storage,
        )
        assert df_recovered is not None
        assert len(df_recovered) == 20

    def test_recover_shadow_predictions_cloud_download_error_returns_none(self, tmp_path):
        """If cloud storage download fails and no local file exists, returns None cleanly."""
        class FailingDownloadManager:
            def __init__(self):
                self.client = object()

            def download_file(self, *args, **kwargs):
                raise RuntimeError("Bucket unavailable")

        fs_dir = tmp_path / "empty_dir"
        recovered = recover_shadow_predictions(
            version_id=999,
            base_dir=fs_dir,
            storage_mgr=FailingDownloadManager(),
        )
        assert recovered is None

