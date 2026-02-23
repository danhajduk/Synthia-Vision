"""SQLite helpers for camera setup profile and view records."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from src.db.camera_store import CameraStore


def db_get_camera_profile(db_path: Path, camera_key: str) -> dict[str, Any] | None:
    with sqlite3.connect(str(db_path), timeout=5.0) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000;")
        row = conn.execute(
            """
            SELECT camera_key, environment, purpose, view_type, mounting_location, view_notes,
                   delivery_focus_json, privacy_mode, setup_completed, default_view_id
            FROM cameras
            WHERE camera_key = ?
            LIMIT 1
            """,
            (camera_key,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    return {
        "camera_key": str(data.get("camera_key", "")),
        "environment": _nullable_str(data.get("environment")),
        "purpose": _nullable_str(data.get("purpose")),
        "view_type": _nullable_str(data.get("view_type")),
        "mounting_location": _nullable_str(data.get("mounting_location")),
        "view_notes": _nullable_str(data.get("view_notes")),
        "delivery_focus": _decode_json_list(data.get("delivery_focus_json")),
        "privacy_mode": _nullable_str(data.get("privacy_mode")) or "no_identifying_details",
        "setup_completed": bool(int(data.get("setup_completed") or 0)),
        "default_view_id": _nullable_str(data.get("default_view_id")),
    }


def db_upsert_camera_profile(db_path: Path, camera_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    CameraStore(db_path).upsert_discovered_camera(camera_key)
    updates = {
        "environment": _nullable_str(payload.get("environment")),
        "purpose": _nullable_str(payload.get("purpose")),
        "view_type": _nullable_str(payload.get("view_type")),
        "mounting_location": _nullable_str(payload.get("mounting_location")),
        "view_notes": _nullable_str(payload.get("view_notes")),
        "delivery_focus_json": _encode_json(payload.get("delivery_focus", [])),
        "privacy_mode": str(payload.get("privacy_mode") or "no_identifying_details"),
        "setup_completed": 1 if _as_bool(payload.get("setup_completed"), False) else 0,
        "default_view_id": _nullable_str(payload.get("default_view_id")),
    }
    with sqlite3.connect(str(db_path), timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute(
            """
            UPDATE cameras
            SET environment = ?,
                purpose = ?,
                view_type = ?,
                mounting_location = ?,
                view_notes = ?,
                delivery_focus_json = ?,
                privacy_mode = ?,
                setup_completed = ?,
                default_view_id = ?
            WHERE camera_key = ?
            """,
            (
                updates["environment"],
                updates["purpose"],
                updates["view_type"],
                updates["mounting_location"],
                updates["view_notes"],
                updates["delivery_focus_json"],
                updates["privacy_mode"],
                updates["setup_completed"],
                updates["default_view_id"],
                camera_key,
            ),
        )
        conn.commit()
    profile = db_get_camera_profile(db_path, camera_key)
    if profile is None:
        raise KeyError(camera_key)
    return profile


def db_list_camera_views(db_path: Path, camera_key: str) -> list[dict[str, Any]]:
    with sqlite3.connect(str(db_path), timeout=5.0) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000;")
        rows = conn.execute(
            """
            SELECT id, camera_key, view_id, label, ha_preset_id, setup_snapshot_path,
                   context_summary, expected_activity_json, zones_json, focus_notes,
                   created_ts, updated_ts
            FROM camera_views
            WHERE camera_key = ?
            ORDER BY view_id ASC
            """,
            (camera_key,),
        ).fetchall()
    return [_map_camera_view_row(dict(row)) for row in rows]


def db_get_camera_view(db_path: Path, camera_key: str, view_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(str(db_path), timeout=5.0) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000;")
        row = conn.execute(
            """
            SELECT id, camera_key, view_id, label, ha_preset_id, setup_snapshot_path,
                   context_summary, expected_activity_json, zones_json, focus_notes,
                   created_ts, updated_ts
            FROM camera_views
            WHERE camera_key = ? AND view_id = ?
            LIMIT 1
            """,
            (camera_key, view_id),
        ).fetchone()
    if row is None:
        return None
    return _map_camera_view_row(dict(row))


def db_upsert_camera_view(
    db_path: Path,
    camera_key: str,
    view_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    CameraStore(db_path).upsert_discovered_camera(camera_key)
    now_ts = int(time.time())
    with sqlite3.connect(str(db_path), timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000;")
        existing = conn.execute(
            "SELECT created_ts FROM camera_views WHERE camera_key = ? AND view_id = ? LIMIT 1",
            (camera_key, view_id),
        ).fetchone()
        created_ts = int(existing[0]) if existing else now_ts
        conn.execute(
            """
            INSERT INTO camera_views(
              camera_key, view_id, label, ha_preset_id, setup_snapshot_path,
              context_summary, expected_activity_json, zones_json, focus_notes,
              created_ts, updated_ts
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(camera_key, view_id) DO UPDATE SET
              label = excluded.label,
              ha_preset_id = excluded.ha_preset_id,
              setup_snapshot_path = excluded.setup_snapshot_path,
              context_summary = excluded.context_summary,
              expected_activity_json = excluded.expected_activity_json,
              zones_json = excluded.zones_json,
              focus_notes = excluded.focus_notes,
              updated_ts = excluded.updated_ts
            """,
            (
                camera_key,
                view_id,
                str(payload.get("label") or view_id),
                _nullable_str(payload.get("ha_preset_id")),
                _nullable_str(payload.get("setup_snapshot_path")),
                _nullable_str(payload.get("context_summary")),
                _encode_json(payload.get("expected_activity", [])),
                _encode_json(payload.get("zones", [])),
                _nullable_str(payload.get("focus_notes")),
                created_ts,
                now_ts,
            ),
        )
        conn.commit()
    view = db_get_camera_view(db_path, camera_key, view_id)
    if view is None:
        raise KeyError(f"{camera_key}:{view_id}")
    return view


def _map_camera_view_row(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(data.get("id", 0)),
        "camera_key": str(data.get("camera_key", "")),
        "view_id": str(data.get("view_id", "")),
        "label": str(data.get("label", "")),
        "ha_preset_id": _nullable_str(data.get("ha_preset_id")),
        "setup_snapshot_path": _nullable_str(data.get("setup_snapshot_path")),
        "context_summary": _nullable_str(data.get("context_summary")),
        "expected_activity": _decode_json_list(data.get("expected_activity_json")),
        "zones": _decode_json_list(data.get("zones_json")),
        "focus_notes": _nullable_str(data.get("focus_notes")),
        "created_ts": int(data.get("created_ts", 0)),
        "updated_ts": int(data.get("updated_ts", 0)),
    }


def _encode_json(value: Any) -> str:
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    except Exception:
        return "[]"


def _decode_json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    if isinstance(parsed, list):
        return parsed
    return []


def _nullable_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "on", "yes"}:
        return True
    if lowered in {"0", "false", "off", "no"}:
        return False
    return default

