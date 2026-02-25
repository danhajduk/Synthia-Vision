"""Frigate HTTP client with retry/backoff and safe logging."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

from src.config import ServiceConfig
from src.errors import ExternalServiceError

LOGGER = logging.getLogger("synthia_vision.frigate")

_RTSP_URL_PATTERN = re.compile(r"rtsp://[^\s\"']+", re.IGNORECASE)
_SENSITIVE_KEY_TOKENS = ("api_key", "password")
_REDACTED = "***redacted***"


def redact_sensitive_data(value: Any) -> Any:
    """Redact sensitive values in nested mappings/lists/strings."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(token in lowered for token in _SENSITIVE_KEY_TOKENS):
                redacted[key_text] = _REDACTED
            else:
                redacted[key_text] = redact_sensitive_data(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, str):
        return _RTSP_URL_PATTERN.sub("rtsp://***redacted***", value)
    return value


class FrigateClient:
    """Small Frigate API abstraction."""

    def __init__(
        self,
        config: ServiceConfig,
        *,
        timeout_seconds: float = 3.0,
        retries: int = 2,
        retry_backoff_seconds: tuple[float, ...] = (0.3, 0.8),
    ) -> None:
        self._base_url = config.frigate.base_url.rstrip("/")
        self._timeout_seconds = float(timeout_seconds)
        self._retries = max(1, int(retries))
        self._retry_backoff_seconds = tuple(retry_backoff_seconds) or (0.3,)

    def get_config(self) -> dict[str, Any]:
        payload = self._request_json("/api/config")
        cameras = payload.get("cameras")
        camera_count = len(cameras) if isinstance(cameras, dict) else 0
        go2rtc = payload.get("go2rtc")
        stream_count = 0
        if isinstance(go2rtc, dict) and isinstance(go2rtc.get("streams"), dict):
            stream_count = len(go2rtc["streams"])
        LOGGER.info(
            "Frigate config fetched cameras=%s go2rtc_streams=%s top_keys=%s",
            camera_count,
            stream_count,
            list(payload.keys())[:20],
        )
        return payload

    def get_stats(self) -> dict[str, Any]:
        payload = self._request_json("/api/stats")
        camera_stats = payload.get("cameras")
        camera_count = len(camera_stats) if isinstance(camera_stats, dict) else 0
        LOGGER.info(
            "Frigate stats fetched cameras=%s top_keys=%s",
            camera_count,
            list(payload.keys())[:20],
        )
        return payload

    def get_latest_jpg(self, camera_name: str) -> bytes:
        camera = str(camera_name or "").strip()
        if not camera:
            raise ExternalServiceError("camera name is required")
        endpoint = f"/api/{camera}/latest.jpg"
        return self._request_bytes(endpoint)

    def _request_json(self, endpoint: str) -> dict[str, Any]:
        response = self._request(endpoint)
        try:
            payload = response.json()
        except Exception as exc:
            raise ExternalServiceError(f"Frigate returned invalid JSON for {endpoint}") from exc
        if not isinstance(payload, dict):
            raise ExternalServiceError(f"Frigate JSON payload must be object for {endpoint}")
        return payload

    def _request_bytes(self, endpoint: str) -> bytes:
        response = self._request(endpoint)
        return bytes(response.content)

    def _request(self, endpoint: str) -> Any:
        if httpx is None:
            raise ExternalServiceError("httpx is required for Frigate client")
        url = f"{self._base_url}{endpoint}"
        for attempt_idx in range(self._retries):
            try:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.get(url)
                if response.status_code >= 400:
                    raise ExternalServiceError(
                        f"Frigate request failed endpoint={endpoint} status={response.status_code}"
                    )
                return response
            except Exception as exc:
                if attempt_idx >= self._retries - 1:
                    raise ExternalServiceError(
                        f"Frigate request failed endpoint={endpoint}: {redact_sensitive_data(str(exc))}"
                    ) from exc
                backoff = self._retry_backoff_seconds[
                    min(attempt_idx, len(self._retry_backoff_seconds) - 1)
                ]
                time.sleep(float(backoff))
        raise ExternalServiceError(f"Frigate request failed endpoint={endpoint}")

