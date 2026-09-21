"""AAGAM — Phase 6 API Latency and Cold-Start Measurement Benchmark.

Measures:
1. Cold start time (very first request initializing asyncpg pool)
2. First authenticated request time (including JWT verification & profile resolution)
3. Warm request latency distributions (min, p50, p95, p99, max) across core read endpoints.

Target from PRD §13: Warm read endpoint p95 < 500 ms.
"""

from __future__ import annotations

import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from fastapi.testclient import TestClient

from api.app.main import app
from core.config import settings

TEST_JWT_SECRET = "benchmark-phase-6-secret-key-32-chars-long"


def create_token() -> str:
    import jwt
    payload = {
        "sub": str(uuid.uuid4()),
        "email": "benchmark@aagam.gov.in",
        "role": "authenticated",
        "app_metadata": {"role": "viewer"},
        "user_metadata": {"role": "viewer"},
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def run_benchmark():
    settings.SUPABASE_JWT_SECRET = TEST_JWT_SECRET
    token = create_token()
    headers = {"Authorization": f"Bearer {token}"}

    print("=" * 80)
    print("AAGAM Phase 6 API Latency & Cold-Start Benchmark")
    print("=" * 80)

    # 1. Cold-start Measurement
    t0 = time.perf_counter()
    with TestClient(app) as client:
        # First request triggers lifespan startup & connection pool init
        resp_cold = client.get("/health")
        cold_latency_ms = (time.perf_counter() - t0) * 1000.0

        print(f"Cold Start Request (GET /health): {cold_latency_ms:.2f} ms (Status: {resp_cold.status_code})")

        # 2. First Authenticated Request
        t_auth0 = time.perf_counter()
        resp_first_auth = client.get("/api/v1/meta", headers=headers)
        first_auth_ms = (time.perf_counter() - t_auth0) * 1000.0
        print(f"First Authenticated Request (GET /api/v1/meta): {first_auth_ms:.2f} ms (Status: {resp_first_auth.status_code})")

        # 3. Warm Latency Measurements
        endpoints = [
            ("GET /health", "/health", False),
            ("GET /api/v1/meta", "/api/v1/meta", True),
            ("GET /api/v1/forecast", "/api/v1/forecast?location=bhubaneswar&variable=rain_mm", True),
            ("GET /api/v1/map", "/api/v1/map?variable=rain_mm&lead_days=1", True),
            ("GET /api/v1/weights", "/api/v1/weights", True),
            ("GET /api/v1/alerts", "/api/v1/alerts?limit=20", True),
            ("GET /api/v1/pipeline/status", "/api/v1/pipeline/status", True),
        ]

        iterations = 50
        results: Dict[str, Dict[str, float]] = {}

        print(f"\nBenchmarking {len(endpoints)} core read endpoints over {iterations} warm requests each...")
        print("-" * 80)
        print(f"{'Endpoint':<30} {'p50 (ms)':<10} {'p95 (ms)':<10} {'p99 (ms)':<10} {'Max (ms)':<10} {'PRD Target':<10}")
        print("-" * 80)

        for name, url, use_auth in endpoints:
            h = headers if use_auth else {}
            # Prime warm-up (3 requests)
            for _ in range(3):
                client.get(url, headers=h)

            latencies: List[float] = []
            for _ in range(iterations):
                start = time.perf_counter()
                r = client.get(url, headers=h)
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                if r.status_code == 200:
                    latencies.append(elapsed_ms)

            if latencies:
                p50 = float(np.percentile(latencies, 50))
                p95 = float(np.percentile(latencies, 95))
                p99 = float(np.percentile(latencies, 99))
                max_lat = max(latencies)
                min_lat = min(latencies)
                mean_lat = statistics.mean(latencies)

                meets_target = "PASS" if p95 < 500.0 else "FAIL"

                results[name] = {
                    "min": min_lat,
                    "mean": mean_lat,
                    "p50": p50,
                    "p95": p95,
                    "p99": p99,
                    "max": max_lat,
                    "target": meets_target,
                }

                print(f"{name:<30} {p50:<10.2f} {p95:<10.2f} {p99:<10.2f} {max_lat:<10.2f} {meets_target:<10}")

        print("=" * 80)
        return cold_latency_ms, first_auth_ms, results


if __name__ == "__main__":
    run_benchmark()
