"""SQLite helpers for discovered camera metadata and runtime toggles."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class CameraRuntimeSettings:
    enabled: bool
    process_end_events: bool
    process_update_events: bool
    updates_per_event: int


@dataclass(slots=True)
class CameraStore:
    db_path: Path

    def upsert_discovered_camera(self, camera_key: str, *, last_seen_ts: float | None = None) -> None:
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        seen_iso = (
            datetime.fromtimestamp(float(last_seen_ts), tz=timezone.utc).isoformat()
            if last_seen_ts is not None
            else now_iso
        )
        display_name = camera_key.replace("_", " ").title()
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                """
                INSERT INTO cameras(
                  camera_key, display_name, enabled, discovered_first_ts, last_seen_ts
                ) VALUES(?, ?, 0, ?, ?)
                ON CONFLICT(camera_key) DO UPDATE SET
                  last_seen_ts=excluded.last_seen_ts
                """,
                (camera_key, display_name, now_iso, seen_iso),
            )
            conn.commit()

    def get_camera_enabled(self, camera_key: str) -> bool | None:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            row = conn.execute(
                "SELECT enabled FROM cameras WHERE camera_key = ?",
                (camera_key,),
            ).fetchone()
        if row is None:
            return None
        return bool(int(row[0]))

    def get_runtime_settings(
        self,
        camera_key: str,
        *,
        default_process_end_events: bool,
        default_process_update_events: bool,
        default_updates_per_event: int,
    ) -> CameraRuntimeSettings:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            row = conn.execute(
                """
                SELECT enabled, process_end_events, process_update_events, updates_per_event
                FROM cameras
                WHERE camera_key = ?
                """,
                (camera_key,),
            ).fetchone()
        if row is None:
            return CameraRuntimeSettings(
                enabled=False,
                process_end_events=default_process_end_events,
                process_update_events=default_process_update_events,
                updates_per_event=default_updates_per_event,
            )
        enabled = bool(int(row[0]))
        process_end = (
            default_process_end_events if row[1] is None else bool(int(row[1]))
        )
        process_update = (
            default_process_update_events if row[2] is None else bool(int(row[2]))
        )
        updates_per_event = (
            default_updates_per_event
            if row[3] is None
            else max(1, int(row[3]))
        )
        return CameraRuntimeSettings(
            enabled=enabled,
            process_end_events=process_end,
            process_update_events=process_update,
            updates_per_event=updates_per_event,
        )

    def set_camera_enabled(self, camera_key: str, enabled: bool) -> None:
        self._ensure_camera_row(camera_key)
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                "UPDATE cameras SET enabled = ?, last_seen_ts = ? WHERE camera_key = ?",
                (1 if enabled else 0, datetime.now(timezone.utc).isoformat(), camera_key),
            )
            conn.commit()

    def set_camera_event_controls(
        self,
        camera_key: str,
        *,
        process_end_events: bool | None = None,
        process_update_events: bool | None = None,
    ) -> None:
        self._ensure_camera_row(camera_key)
        updates: list[str] = []
        params: list[object] = []
        if process_end_events is not None:
            updates.append("process_end_events = ?")
            params.append(1 if process_end_events else 0)
        if process_update_events is not None:
            updates.append("process_update_events = ?")
            params.append(1 if process_update_events else 0)
        if not updates:
            return
        updates.append("last_seen_ts = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(camera_key)
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                f"UPDATE cameras SET {', '.join(updates)} WHERE camera_key = ?",
                tuple(params),
            )
            conn.commit()

    def upsert_kv(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                """
                INSERT INTO kv(k, v, updated_ts) VALUES(?, ?, ?)
                ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_ts = excluded.updated_ts
                """,
                (key, value, now),
            )
            conn.commit()

    def _ensure_camera_row(self, camera_key: str) -> None:
        self.upsert_discovered_camera(camera_key)
