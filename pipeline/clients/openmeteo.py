"""Open-Meteo Client for AAGAM (Adaptive AI-Grid Assimilation Model).

Strictly adheres to:
- FR-DATA-1: Live forecast ingestion for 4 models × 3 variables (8 forecast days).
- FR-DATA-2: Previous Runs API for rolling lead days (previous_day1 .. previous_day7).
- FR-DATA-4: API rate limiting, call-cost estimation, and HTTP 429 resilience.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger("aagam.clients.openmeteo")

# Authoritative Open-Meteo model identifiers
OPENMETEO_MODELS = {
    "GFS": "gfs_seamless",
    "ECMWF": "ecmwf_ifs025",
    "ICON": "icon_global",
    "AIFS": "ecmwf_aifs025_single",
}

DEFAULT_VARIABLES = ["precipitation", "temperature_2m", "wind_speed_10m"]

FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_API_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"


class OpenMeteoError(Exception):
    """Base exception for Open-Meteo client errors."""
    pass


class OpenMeteoServerError(OpenMeteoError):
    """5xx Server error retryable by tenacity."""
    pass


class OpenMeteoRateLimitHaltError(OpenMeteoError):
    """Halt error raised when two 429 rate limit responses occur within 1 hour."""
    pass


class RateLimiter:
    """Thread-safe rate limiter enforcing maximum requests per second."""

    def __init__(self, max_per_second: float = 5.0) -> None:
        self.interval = 1.0 / max_per_second
        self.last_called = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_called
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_called = time.monotonic()


def is_retryable_error(exception: BaseException) -> bool:
    """Predicate determining if an exception is retryable by tenacity."""
    if isinstance(exception, (httpx.TransportError, httpx.TimeoutException, OpenMeteoServerError)):
        return True
    return False


class OpenMeteoClient:
    """Robust client for Open-Meteo APIs with throttling, retry, and rate limit defense."""

    def __init__(
        self,
        rate_limit_per_sec: float = 5.0,
        timeout: float = 30.0,
    ) -> None:
        self.rate_limiter = RateLimiter(rate_limit_per_sec)
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)
        self._429_history: List[float] = []
        self._lock = threading.Lock()

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> OpenMeteoClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def estimate_calls(self, num_locations: int, num_models: int, num_batches: int = 1) -> int:
        """Calculates and logs estimated API calls for a planned batch operation."""
        # Since models can be bundled, bundled calls = num_locations * num_batches
        estimated_calls = num_locations * num_batches
        logger.info(
            f"API Call Estimation: {estimated_calls} requests planned "
            f"({num_locations} locations × {num_batches} batches; {num_models} models bundled)."
        )
        return estimated_calls

    def _handle_429(self, resp: httpx.Response) -> None:
        """Enforces FR-DATA-4: 429 response handling and circuit breaker."""
        now = time.time()
        with self._lock:
            # Clean history older than 1 hour (3600 seconds)
            self._429_history = [t for t in self._429_history if now - t < 3600]
            self._429_history.append(now)

            retry_after = resp.headers.get("Retry-After")
            sleep_duration = float(retry_after) if retry_after and retry_after.isdigit() else 60.0

            logger.error(
                f"HTTP 429 (Too Many Requests) received at {datetime.now(timezone.utc).isoformat()}. "
                f"Count in last hour: {len(self._429_history)}. Pausing for {sleep_duration}s."
            )

            if len(self._429_history) >= 2:
                logger.critical(
                    "FR-DATA-4 violation prevention: Second HTTP 429 within 1 hour! Halting pipeline gracefully."
                )
                raise OpenMeteoRateLimitHaltError(
                    f"Second HTTP 429 received within 1 hour at {datetime.now(timezone.utc).isoformat()}."
                )

        time.sleep(sleep_duration)

    @retry(
        retry=retry_if_exception(is_retryable_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    def _get_with_retry(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Internal HTTP GET with rate limiting and exponential backoff on 5xx."""
        self.rate_limiter.wait()
        try:
            resp = self.client.get(url, params=params)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.warning(f"Network transport error connecting to {url}: {exc}")
            raise

        if resp.status_code == 429:
            self._handle_429(resp)
            # After waiting out the 429, retry once manually
            self.rate_limiter.wait()
            resp = self.client.get(url, params=params)

        if resp.status_code >= 500:
            logger.warning(f"Server error {resp.status_code} from {url}: {resp.text[:200]}")
            raise OpenMeteoServerError(f"Open-Meteo 5xx error: HTTP {resp.status_code}")

        if resp.status_code != 200:
            raise OpenMeteoError(f"HTTP {resp.status_code} error from {url}: {resp.text[:200]}")

        if not resp.content or len(resp.content.strip()) == 0:
            logger.warning(f"Empty response body (0 bytes) received from {url}")
            raise OpenMeteoServerError(f"Empty response body received from {url}")

        try:
            return resp.json()
        except Exception as json_err:
            logger.warning(f"JSON decode error from {url}: {json_err} - raw content: {resp.text[:100]}")
            raise OpenMeteoServerError(f"Invalid JSON from {url}: {json_err}")

    def fetch_live_forecast(
        self,
        latitude: float,
        longitude: float,
        models: Optional[List[str]] = None,
        variables: Optional[List[str]] = None,
        forecast_days: int = 8,
    ) -> Dict[str, Any]:
        """Fetches live multi-model forecast data (FR-DATA-1).

        Args:
            latitude: Latitude of location.
            longitude: Longitude of location.
            models: List of model identifiers (defaults to all 4 authoritative models).
            variables: List of variable names (defaults to rain, temp, wind).
            forecast_days: Forecast horizon (minimum 8 days).
        """
        if models is None:
            models = list(OPENMETEO_MODELS.values())
        if variables is None:
            variables = DEFAULT_VARIABLES

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(variables),
            "models": ",".join(models),
            "forecast_days": forecast_days,
            "timezone": "UTC",
        }
        return self._get_with_retry(FORECAST_API_URL, params)

    def fetch_previous_runs(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
        models: Optional[List[str]] = None,
        variables: Optional[List[str]] = None,
        lead_days: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Fetches rolling lead-day previous runs from Open-Meteo Previous Runs API (FR-DATA-2).

        Args:
            latitude: Latitude.
            longitude: Longitude.
            start_date: Start date string (YYYY-MM-DD).
            end_date: End date string (YYYY-MM-DD).
            models: Target models.
            variables: Base weather variables (precipitation, temperature_2m, wind_speed_10m).
            lead_days: List of lead days (e.g., [1, 2, 3, 4, 5, 6, 7]).
        """
        if models is None:
            models = list(OPENMETEO_MODELS.values())
        if variables is None:
            variables = DEFAULT_VARIABLES
        if lead_days is None:
            lead_days = list(range(1, 8))

        # Build variable names with previous_dayX suffix
        hourly_vars = [f"{v}_previous_day{d}" for d in lead_days for v in variables]

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(hourly_vars),
            "models": ",".join(models),
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "UTC",
        }
        return self._get_with_retry(PREVIOUS_RUNS_API_URL, params)

    def fetch_era5_archive(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
        variables: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Fetches ERA5 historical hourly reanalysis for truth calibration.

        Args:
            latitude: Latitude.
            longitude: Longitude.
            start_date: YYYY-MM-DD.
            end_date: YYYY-MM-DD.
            variables: List of variables.
        """
        if variables is None:
            variables = DEFAULT_VARIABLES

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(variables),
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "UTC",
        }
        return self._get_with_retry(ARCHIVE_API_URL, params)
