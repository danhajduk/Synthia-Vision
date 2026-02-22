"""Frigate snapshot retrieval with retry/backoff safeguards."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import httpx

from src.config import ServiceConfig
from src.errors import ExternalServiceError

LOGGER = logging.getLogger("synthia_vision")

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class SnapshotManager:
    """Fetches snapshots from Frigate and optionally persists debug copies."""

    def __init__(self, config: ServiceConfig) -> None:
        self._config = config
        self._base_url = config.frigate.base_url.rstrip("/")
        self._snapshot_config = config.frigate.snapshot
        self._debug_save_enabled = bool(getattr(self._snapshot_config, "debug_save", False))
        self._snapshots_dir = config.paths.snapshots_dir

    def fetch_event_snapshot(self, event_id: str, camera: str | None = None) -> bytes:
        """Fetch snapshot bytes for an event with retry/backoff policy."""
        endpoint = self._snapshot_config.endpoint_template.format(event_id=event_id)
        url = f"{self._base_url}{endpoint}"
        attempts = max(1, self._snapshot_config.retries)
        backoffs = self._snapshot_config.retry_backoff_seconds
        timeout = float(self._snapshot_config.timeout_seconds)

        for attempt_idx in range(attempts):
            attempt_num = attempt_idx + 1
            try:
                snapshot = self._fetch_once(url, timeout)
                if self._debug_save_enabled:
                    self._save_debug_snapshot(event_id=event_id, camera=camera, snapshot=snapshot)
                LOGGER.info(
                    "Snapshot fetched event_id=%s bytes=%s attempt=%s",
                    event_id,
                    len(snapshot),
                    attempt_num,
                )
                return snapshot
            except ExternalServiceError as exc:
                is_last_attempt = attempt_num >= attempts
                if is_last_attempt:
                    raise
                backoff_seconds = backoffs[min(attempt_idx, len(backoffs) - 1)] if backoffs else 0.5
                LOGGER.warning(
                    "Snapshot fetch attempt failed event_id=%s attempt=%s/%s backoff=%ss error=%s",
                    event_id,
                    attempt_num,
                    attempts,
                    backoff_seconds,
                    exc,
                )
                time.sleep(float(backoff_seconds))

        raise ExternalServiceError(f"Exhausted snapshot retries for event_id={event_id}")

    def _fetch_once(self, url: str, timeout: float) -> bytes:
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.get(url)
        except httpx.TimeoutException as exc:
            raise ExternalServiceError(f"Snapshot request timed out: {url}") from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"Snapshot request failed: {url} ({exc})") from exc

        if response.status_code >= 400:
            raise ExternalServiceError(
                f"Snapshot request returned status {response.status_code}: {url}"
            )

        snapshot = response.content
        max_bytes = int(self._snapshot_config.max_bytes)
        if len(snapshot) > max_bytes:
            raise ExternalServiceError(
                f"Snapshot exceeds max_bytes ({len(snapshot)} > {max_bytes})"
            )
        return snapshot

    def _save_debug_snapshot(
        self,
        *,
        event_id: str,
        camera: str | None,
        snapshot: bytes,
    ) -> None:
        if camera:
            safe_name = _SAFE_FILENAME.sub("_", camera)
        else:
            safe_name = _SAFE_FILENAME.sub("_", event_id)
        path = self._snapshots_dir / f"{safe_name}.jpg"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(snapshot)
            LOGGER.debug("Saved debug snapshot path=%s bytes=%s", path, len(snapshot))
        except OSError as exc:
            LOGGER.warning("Failed saving debug snapshot path=%s error=%s", path, exc)
