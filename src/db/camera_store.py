"""SQLite helpers for discovered camera metadata and runtime toggles."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


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
