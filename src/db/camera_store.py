"""SQLite helpers for discovered camera metadata and runtime toggles."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_UNSET = object()


@dataclass(slots=True)
class CameraRuntimeSettings:
    enabled: bool
    process_end_events: bool
    process_update_events: bool
    updates_per_event: int


@dataclass(slots=True)
class CameraPolicySettings:
    display_name: str
    prompt_preset: str | None
    confidence_threshold: float
    cooldown_s: int
    vision_detail: str
    phash_threshold: int | None
    guest_preview_enabled: bool


@dataclass(slots=True)
class CameraStore:
    db_path: Path

    def list_camera_keys(self) -> list[str]:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            rows = conn.execute(
                "SELECT camera_key FROM cameras ORDER BY camera_key ASC"
            ).fetchall()
        return [str(row[0]) for row in rows]

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

    def get_policy_settings(
        self,
        camera_key: str,
        *,
        default_display_name: str,
        default_confidence_threshold: float,
        default_cooldown_s: int,
        default_vision_detail: str,
    ) -> CameraPolicySettings:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            row = conn.execute(
                """
                SELECT display_name, prompt_preset, confidence_threshold, cooldown_s, vision_detail, phash_threshold, guest_preview_enabled
                FROM cameras
                WHERE camera_key = ?
                """,
                (camera_key,),
            ).fetchone()
        if row is None:
            return CameraPolicySettings(
                display_name=default_display_name,
                prompt_preset=None,
                confidence_threshold=default_confidence_threshold,
                cooldown_s=default_cooldown_s,
                vision_detail=default_vision_detail,
                phash_threshold=None,
                guest_preview_enabled=False,
            )
        display_name = str(row[0]) if row[0] else default_display_name
        prompt_preset = str(row[1]) if row[1] else None
        confidence_threshold = (
            default_confidence_threshold
            if row[2] is None
            else max(0.0, min(1.0, float(row[2])))
        )
        cooldown_s = default_cooldown_s if row[3] is None else max(0, int(row[3]))
        vision_detail = (
            default_vision_detail
            if row[4] not in {"low", "high", "auto"}
            else str(row[4])
        )
        phash_threshold = None if row[5] is None else max(0, int(row[5]))
        guest_preview_enabled = False
        if len(row) > 6 and row[6] is not None:
            guest_preview_enabled = bool(int(row[6]))
        return CameraPolicySettings(
            display_name=display_name,
            prompt_preset=prompt_preset,
            confidence_threshold=confidence_threshold,
            cooldown_s=cooldown_s,
            vision_detail=vision_detail,
            phash_threshold=phash_threshold,
            guest_preview_enabled=guest_preview_enabled,
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

    def set_camera_policy_fields(
        self,
        camera_key: str,
        *,
        display_name: str | object = _UNSET,
        prompt_preset: str | None | object = _UNSET,
        confidence_threshold: float | object = _UNSET,
        cooldown_s: int | object = _UNSET,
        vision_detail: str | object = _UNSET,
        phash_threshold: int | object = _UNSET,
        enabled: bool | object = _UNSET,
        guest_preview_enabled: bool | object = _UNSET,
    ) -> None:
        self._ensure_camera_row(camera_key)
        updates: list[str] = []
        params: list[object] = []
        if display_name is not _UNSET:
            updates.append("display_name = ?")
            params.append(str(display_name))
        if prompt_preset is not _UNSET:
            updates.append("prompt_preset = ?")
            params.append(None if prompt_preset is None else str(prompt_preset))
        if confidence_threshold is not _UNSET:
            updates.append("confidence_threshold = ?")
            params.append(max(0.0, min(1.0, float(confidence_threshold))))
        if cooldown_s is not _UNSET:
            updates.append("cooldown_s = ?")
            params.append(max(0, int(cooldown_s)))
        if vision_detail is not _UNSET:
            normalized_detail = str(vision_detail).lower()
            if normalized_detail in {"low", "high", "auto"}:
                updates.append("vision_detail = ?")
                params.append(normalized_detail)
        if phash_threshold is not _UNSET:
            updates.append("phash_threshold = ?")
            params.append(max(0, int(phash_threshold)))
        if enabled is not _UNSET:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)
        if guest_preview_enabled is not _UNSET:
            updates.append("guest_preview_enabled = ?")
            params.append(1 if guest_preview_enabled else 0)
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

    def get_last_phash(self, camera_key: str) -> str | None:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            row = conn.execute(
                "SELECT last_phash FROM cameras WHERE camera_key = ?",
                (camera_key,),
            ).fetchone()
        if row is None:
            return None
        value = row[0]
        if value is None:
            return None
        return str(value)

    def set_last_phash(self, camera_key: str, phash_hex: str) -> None:
        self._ensure_camera_row(camera_key)
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                "UPDATE cameras SET last_phash = ?, last_phash_ts = ?, last_seen_ts = ? WHERE camera_key = ?",
                (str(phash_hex), now, now, camera_key),
            )
            conn.commit()

    def _ensure_camera_row(self, camera_key: str) -> None:
        self.upsert_discovered_camera(camera_key)
