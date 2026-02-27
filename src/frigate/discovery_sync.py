"""Sync Frigate camera discovery payload into SV camera registry."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.db.camera_store import CameraStore

LOGGER = logging.getLogger("synthia_vision.frigate")

_RTSP_8554_STREAM = re.compile(r"/8554/([^/?#]+)")


@dataclass(slots=True)
class CameraDiscoveryRecord:
    camera_id: str
    display_name: str
    enabled: bool
    detect_width: int | None
    detect_height: int | None
    detect_fps: float | None
    audio_enabled: bool
    tracked_objects: list[str]
    snapshots_enabled: bool
    record_enabled: bool
    detect_stream_name: str | None
    record_stream_name: str | None


def sync_discovered_cameras_from_config(
    *,
    db_path: Path,
    frigate_config_payload: dict[str, Any],
) -> dict[str, Any]:
    cameras_raw = frigate_config_payload.get("cameras")
    if not isinstance(cameras_raw, dict):
        return {"count": 0, "camera_ids": [], "items": []}
    go2rtc_stream_keys = _extract_go2rtc_stream_keys(frigate_config_payload)
    records: list[CameraDiscoveryRecord] = []
    for camera_id, raw in cameras_raw.items():
        if not isinstance(raw, dict):
            continue
        camera_key = str(camera_id).strip()
        if not camera_key:
            continue
        display_name = str(raw.get("name") or camera_key).strip() or camera_key
        detect = raw.get("detect")
        detect_width = _to_int((detect or {}).get("width")) if isinstance(detect, dict) else None
        detect_height = _to_int((detect or {}).get("height")) if isinstance(detect, dict) else None
        detect_fps = _to_float((detect or {}).get("fps")) if isinstance(detect, dict) else None
        audio_enabled = bool(_to_bool((raw.get("audio") or {}).get("enabled"), False))
        tracked_objects = _to_string_list((raw.get("objects") or {}).get("track"))
        snapshots_enabled = bool(_to_bool((raw.get("snapshots") or {}).get("enabled"), False))
        record_enabled = bool(_to_bool((raw.get("record") or {}).get("enabled"), False))
        detect_stream_name, record_stream_name = _extract_ffmpeg_stream_names(raw.get("ffmpeg"))
        records.append(
            CameraDiscoveryRecord(
                camera_id=camera_key,
                display_name=display_name,
                enabled=bool(_to_bool(raw.get("enabled"), False)),
                detect_width=detect_width,
                detect_height=detect_height,
                detect_fps=detect_fps,
                audio_enabled=audio_enabled,
                tracked_objects=tracked_objects,
                snapshots_enabled=snapshots_enabled,
                record_enabled=record_enabled,
                detect_stream_name=detect_stream_name,
                record_stream_name=record_stream_name,
            )
        )

    store = CameraStore(db_path)
    for record in records:
        store.upsert_discovered_camera(record.camera_id)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(db_path), timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000;")
        for record in records:
            conn.execute(
                """
                UPDATE cameras
                SET display_name = ?,
                    frigate_camera_id = ?,
                    detect_width = ?,
                    detect_height = ?,
                    detect_fps = ?,
                    audio_enabled = ?,
                    tracked_objects_json = ?,
                    snapshots_enabled = ?,
                    record_enabled = ?,
                    detect_stream_name = ?,
                    record_stream_name = ?,
                    last_seen_ts = ?
                WHERE camera_key = ?
                """,
                (
                    record.display_name,
                    record.camera_id,
                    record.detect_width,
                    record.detect_height,
                    record.detect_fps,
                    1 if record.audio_enabled else 0,
                    json.dumps(record.tracked_objects, separators=(",", ":"), ensure_ascii=True),
                    1 if record.snapshots_enabled else 0,
                    1 if record.record_enabled else 0,
                    record.detect_stream_name,
                    record.record_stream_name,
                    now,
                    record.camera_id,
                ),
            )
        conn.commit()

    camera_ids = [item.camera_id for item in records]
    items = [
        {
            "camera_id": item.camera_id,
            "enabled": item.enabled,
            "detect_fps": item.detect_fps,
            "has_detect_stream": bool(item.detect_stream_name and item.detect_stream_name in go2rtc_stream_keys),
            "has_record_stream": bool(item.record_stream_name and item.record_stream_name in go2rtc_stream_keys),
        }
        for item in records
    ]
    return {
        "count": len(records),
        "camera_ids": camera_ids,
        "items": items,
    }


def _extract_go2rtc_stream_keys(payload: dict[str, Any]) -> set[str]:
    go2rtc = payload.get("go2rtc")
    if not isinstance(go2rtc, dict):
        return set()
    streams = go2rtc.get("streams")
    if not isinstance(streams, dict):
        return set()
    return {str(key).strip() for key in streams.keys() if str(key).strip()}


def _extract_ffmpeg_stream_names(ffmpeg_raw: Any) -> tuple[str | None, str | None]:
    if not isinstance(ffmpeg_raw, dict):
        return None, None
    inputs = ffmpeg_raw.get("inputs")
    if not isinstance(inputs, list):
        return None, None
    detect_stream: str | None = None
    record_stream: str | None = None
    for item in inputs:
        if not isinstance(item, dict):
            continue
        roles = {str(role).strip().lower() for role in _to_string_list(item.get("roles"))}
        path = str(item.get("path") or "")
        stream_name = _extract_stream_name(path)
        if not stream_name:
            continue
        if "detect" in roles and detect_stream is None:
            detect_stream = stream_name
        if "record" in roles and record_stream is None:
            record_stream = stream_name
    return detect_stream, record_stream


def _extract_stream_name(path: str) -> str | None:
    if not path:
        return None
    match = _RTSP_8554_STREAM.search(path)
    if not match:
        return None
    stream_name = match.group(1).strip()
    return stream_name or None


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _to_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []
