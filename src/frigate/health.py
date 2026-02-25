"""Frigate stats poller and health persistence helpers."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import ServiceConfig
from src.db.camera_store import CameraStore
from src.frigate.client import FrigateClient

LOGGER = logging.getLogger("synthia_vision.frigate")


class FrigateHealthPoller:
    """Background poller for Frigate camera health."""

    def __init__(self, config: ServiceConfig) -> None:
        self._config = config
        self._db_path = config.paths.db_file
        self._client = FrigateClient(config)
        self._interval_seconds = max(5, int(config.frigate.stats_poll_seconds))
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="frigate-health-poller")
        LOGGER.info("Started Frigate health poller interval_s=%s", self._interval_seconds)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return
        await self._task
        self._task = None
        LOGGER.info("Stopped Frigate health poller")

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            await self._run_once()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=float(self._interval_seconds),
                )
            except asyncio.TimeoutError:
                pass

    async def _run_once(self) -> None:
        try:
            payload = await asyncio.to_thread(self._client.get_stats)
            await asyncio.to_thread(_persist_health_success, self._db_path, payload)
        except Exception as exc:
            await asyncio.to_thread(_persist_health_failure, self._db_path, str(exc))


def _persist_health_success(db_path: Path, payload: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    stats_cameras = payload.get("cameras")
    camera_stats = stats_cameras if isinstance(stats_cameras, dict) else {}
    camera_keys = CameraStore(db_path).list_camera_keys()
    with sqlite3.connect(str(db_path), timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000;")
        _upsert_kv(conn, "frigate.health.status", "ok", now)
        _upsert_kv(conn, "frigate.health.last_ok_at", now, now)
        _upsert_kv(conn, "frigate.health.updated_at", now, now)
        updated_count = 0
        for camera_key in camera_keys:
            raw = camera_stats.get(camera_key)
            status, detail = _camera_health_from_stats(raw)
            conn.execute(
                """
                UPDATE cameras
                SET health_status = ?,
                    health_detail = ?,
                    health_updated_ts = ?,
                    last_seen_ts = CASE WHEN ? != 'down' THEN ? ELSE last_seen_ts END
                WHERE camera_key = ?
                """,
                (status, detail, now, status, now, camera_key),
            )
            updated_count += 1
        conn.commit()
    LOGGER.info("Frigate health poll success cameras=%s", updated_count)


def _persist_health_failure(db_path: Path, error_text: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    reason = str(error_text or "request_failed")
    with sqlite3.connect(str(db_path), timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000;")
        _upsert_kv(conn, "frigate.health.status", "down", now)
        _upsert_kv(conn, "frigate.health.updated_at", now, now)
        conn.execute(
            """
            UPDATE cameras
            SET health_status = 'down',
                health_detail = ?,
                health_updated_ts = ?
            """,
            ("stats_unavailable", now),
        )
        conn.commit()
    LOGGER.warning("Frigate health poll failed error=%s", reason)


def _camera_health_from_stats(raw: Any) -> tuple[str, str]:
    if not isinstance(raw, dict):
        return "down", "missing_from_stats"
    camera_fps = _numeric_value(raw.get("camera_fps"))
    process_fps = _numeric_value(raw.get("process_fps"))
    detection_fps = _numeric_value(raw.get("detection_fps"))
    if camera_fps is not None and camera_fps <= 0.0:
        return "degraded", "camera_fps_zero"
    if process_fps is not None and process_fps <= 0.0:
        return "degraded", "process_fps_zero"
    if detection_fps is not None and detection_fps <= 0.0:
        return "degraded", "detection_fps_zero"
    if _looks_stopped(raw):
        return "down", "pipeline_stopped"
    detail = []
    if camera_fps is not None:
        detail.append(f"camera_fps={camera_fps:.2f}")
    if process_fps is not None:
        detail.append(f"process_fps={process_fps:.2f}")
    if detection_fps is not None:
        detail.append(f"detection_fps={detection_fps:.2f}")
    return "ok", ", ".join(detail) if detail else "stats_ok"


def _looks_stopped(raw: dict[str, Any]) -> bool:
    for key in ("capture_pid", "ffmpeg_pid", "pid"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and int(value) <= 0:
            return True
    for key in ("ffmpeg_running", "capture_running", "detect_running"):
        value = raw.get(key)
        if isinstance(value, bool) and not value:
            return True
    return False


def _numeric_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _upsert_kv(conn: sqlite3.Connection, key: str, value: str, now: str) -> None:
    conn.execute(
        """
        INSERT INTO kv(k, v, updated_ts) VALUES(?, ?, ?)
        ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_ts=excluded.updated_ts
        """,
        (key, value, now),
    )

