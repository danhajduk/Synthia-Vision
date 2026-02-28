"""SQLite admin query/update helpers for admin APIs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.db.camera_store import CameraStore
from src.db.camera_store import _UNSET


@dataclass(slots=True)
class AdminStore:
    db_path: Path

    def list_events(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        camera: str | None = None,
        status: str | None = None,
        event_id_query: str | None = None,
        accepted: bool | None = None,
        sort_by: str = "ts",
        sort_dir: str = "desc",
    ) -> dict[str, Any]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))
        where: list[str] = []
        params: list[Any] = []
        if camera:
            where.append("camera = ?")
            params.append(camera)
        if status:
            where.append("result_status = ?")
            params.append(status)
        if event_id_query:
            where.append("event_id LIKE ?")
            params.append(f"%{event_id_query}%")
        if accepted is not None:
            where.append("accepted = ?")
            params.append(1 if accepted else 0)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        normalized_sort_by = str(sort_by or "ts").strip().lower()
        normalized_sort_dir = "asc" if str(sort_dir or "").strip().lower() == "asc" else "desc"
        order_sql = "ORDER BY ts DESC, id DESC"
        if normalized_sort_by == "risk_score":
            if normalized_sort_dir == "asc":
                order_sql = "ORDER BY (risk_score IS NULL) ASC, risk_score ASC, ts DESC, id DESC"
            else:
                order_sql = "ORDER BY (risk_score IS NULL) ASC, risk_score DESC, ts DESC, id DESC"
        elif normalized_sort_by == "ai_confidence":
            if normalized_sort_dir == "asc":
                order_sql = (
                    "ORDER BY (ai_confidence IS NULL) ASC, ai_confidence ASC, ts DESC, id DESC"
                )
            else:
                order_sql = (
                    "ORDER BY (ai_confidence IS NULL) ASC, ai_confidence DESC, ts DESC, id DESC"
                )
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000;")
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM events {where_sql}",
                    tuple(params),
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"""
                SELECT event_id, ts, camera, event_type, accepted, reject_reason, cooldown_remaining_s, dedupe_hit, suppressed_by_event_id,
                       result_status, action, subject_type, frigate_score, confidence, ai_confidence, ai_reason, risk_score, description,
                       snapshot_bytes, image_width, image_height, vision_detail, created_ts
                FROM events
                {where_sql}
                {order_sql}
                LIMIT ? OFFSET ?
                """,
                tuple([*params, limit, offset]),
            ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [dict(row) for row in rows],
        }

    def list_event_cameras(self) -> list[str]:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            rows = conn.execute(
                """
                SELECT DISTINCT camera
                FROM events
                WHERE camera IS NOT NULL AND TRIM(camera) != ''
                ORDER BY camera ASC
                """
            ).fetchall()
        return [str(row[0]) for row in rows if row and str(row[0]).strip()]

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000;")
            event = conn.execute(
                """
                SELECT event_id, ts, camera, event_type, accepted, reject_reason, cooldown_remaining_s, dedupe_hit, suppressed_by_event_id,
                       result_status, action, subject_type, frigate_score, confidence, ai_confidence, ai_reason, risk_score, description,
                       snapshot_bytes, image_width, image_height, vision_detail, created_ts
                FROM events
                WHERE event_id = ?
                LIMIT 1
                """,
                (event_id,),
            ).fetchone()
            if event is None:
                return None
            metrics = conn.execute(
                """
                SELECT id, event_id, latency_snapshot_ms, latency_openai_ms, latency_total_ms,
                       prompt_tokens, completion_tokens, cost_usd, model,
                       phash, phash_distance, skipped_openai_reason, created_ts
                FROM metrics
                WHERE event_id = ?
                ORDER BY id ASC
                """,
                (event_id,),
            ).fetchall()
        return {
            **dict(event),
            "metrics": [dict(row) for row in metrics],
        }

    def list_errors(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000;")
            total = int(conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0])
            rows = conn.execute(
                """
                SELECT id, ts, component, message, detail, event_id, camera
                FROM errors
                ORDER BY ts DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [dict(row) for row in rows],
        }

    def get_timeline_heatmap(self, *, hours: int = 24) -> dict[str, Any]:
        window_hours = 168 if int(hours) >= 168 else 24
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000;")
            rows = conn.execute(
                """
                WITH metric_events AS (
                  SELECT DISTINCT event_id
                  FROM metrics
                )
                SELECT
                  substr(e.ts, 1, 13) AS hour_key,
                  e.camera AS camera,
                  COUNT(*) AS events_count,
                  SUM(CASE WHEN me.event_id IS NOT NULL THEN 1 ELSE 0 END) AS ai_calls_count,
                  SUM(
                    CASE
                      WHEN e.result_status='suppressed' AND e.reject_reason='suppressed_duplicate' THEN 1
                      ELSE 0
                    END
                  ) AS suppressed_count
                FROM events e
                LEFT JOIN metric_events me ON me.event_id = e.event_id
                WHERE e.ts >= ?
                GROUP BY hour_key, e.camera
                ORDER BY hour_key ASC, e.camera ASC
                """,
                (cutoff_iso,),
            ).fetchall()
        return {
            "window_hours": window_hours,
            "cutoff_ts": cutoff_iso,
            "items": [dict(row) for row in rows],
        }

    def get_metrics_heatmap(
        self,
        *,
        range_type: str = "24h",
        camera: str = "all",
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_range = str(range_type or "24h").strip().lower()
        if normalized_range not in {"24h", "avg7d", "avg30d"}:
            normalized_range = "24h"
        normalized_camera = str(camera or "all").strip()
        if not normalized_camera:
            normalized_camera = "all"
        local_tz = datetime.now().astimezone().tzinfo
        timezone_name = str(getattr(local_tz, "key", "") or str(local_tz or "local"))
        now_utc_value = now_utc or datetime.now(timezone.utc)
        if now_utc_value.tzinfo is None:
            now_utc_value = now_utc_value.replace(tzinfo=timezone.utc)
        now_local = now_utc_value.astimezone(local_tz) if local_tz is not None else now_utc_value
        is_complete_days_only = normalized_range in {"avg7d", "avg30d"}
        if normalized_range == "24h":
            start_local = now_local - timedelta(hours=24)
            end_local = now_local
        else:
            full_days = 7 if normalized_range == "avg7d" else 30
            local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            start_local = local_midnight - timedelta(days=full_days)
            end_local = local_midnight
        start_utc = start_local.astimezone(timezone.utc).isoformat()
        end_utc = end_local.astimezone(timezone.utc).isoformat()

        where: list[str] = ["e.ts >= ?", "e.ts < ?"]
        params: list[Any] = [start_utc, end_utc]
        if normalized_camera != "all":
            where.append("e.camera = ?")
            params.append(normalized_camera)
        where_sql = " AND ".join(where)
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000;")
            rows = conn.execute(
                f"""
                WITH metric_events AS (
                  SELECT DISTINCT event_id
                  FROM metrics
                )
                SELECT
                  e.camera AS camera,
                  strftime('%Y-%m-%d', datetime(e.ts, 'localtime')) AS local_day,
                  CAST(strftime('%H', datetime(e.ts, 'localtime')) AS INTEGER) AS local_hour,
                  COUNT(*) AS events_count,
                  SUM(CASE WHEN me.event_id IS NOT NULL THEN 1 ELSE 0 END) AS ai_calls_count,
                  SUM(
                    CASE
                      WHEN e.result_status='suppressed' AND e.reject_reason='suppressed_duplicate' THEN 1
                      ELSE 0
                    END
                  ) AS suppressed_count
                FROM events e
                LEFT JOIN metric_events me ON me.event_id = e.event_id
                WHERE {where_sql}
                GROUP BY e.camera, local_day, local_hour
                ORDER BY e.camera ASC, local_day ASC, local_hour ASC
                """,
                tuple(params),
            ).fetchall()
        items = [dict(row) for row in rows]
        per_camera_rows: dict[str, list[dict[str, Any]]] = {}
        for row in items:
            camera_key = str(row.get("camera", "") or "")
            per_camera_rows.setdefault(camera_key, []).append(row)
        global_rows = _merge_rows_across_cameras(items)
        global_series = _series_from_rows(
            global_rows,
            average=is_complete_days_only,
        )

        response: dict[str, Any] = {
            "timezone": timezone_name,
            "range_type": normalized_range,
            "camera": normalized_camera,
            "start_local": start_local.isoformat(),
            "end_local": end_local.isoformat(),
            "is_complete_days_only": is_complete_days_only,
            "days_covered": global_series["days_covered"] if is_complete_days_only else None,
            "buckets": global_series["buckets"],
            "totals": global_series["totals"],
        }
        if normalized_camera == "all":
            per_camera_payload: dict[str, Any] = {}
            for camera_key, camera_rows in sorted(per_camera_rows.items()):
                camera_series = _series_from_rows(
                    camera_rows,
                    average=is_complete_days_only,
                )
                per_camera_payload[camera_key] = {
                    "days_covered": camera_series["days_covered"]
                    if is_complete_days_only
                    else None,
                    "buckets": camera_series["buckets"],
                    "totals": camera_series["totals"],
                }
            response["per_camera"] = per_camera_payload
        return response

    def list_cameras(self) -> dict[str, Any]:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000;")
            rows = conn.execute(
                """
                SELECT camera_key, display_name, enabled, discovered_first_ts, last_seen_ts,
                       prompt_preset, confidence_threshold, cooldown_s,
                       process_end_events, process_update_events, updates_per_event,
                       guest_preview_enabled, security_capable, security_mode,
                       setup_completed, vision_detail, phash_threshold, last_phash, last_phash_ts
                FROM cameras
                ORDER BY camera_key ASC
                """
            ).fetchall()
        return {
            "count": len(rows),
            "items": [dict(row) for row in rows],
        }

    def update_camera(self, camera_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        camera_store = CameraStore(self.db_path)
        enabled = payload.get("enabled")
        if isinstance(enabled, bool):
            camera_store.set_camera_enabled(camera_key, enabled)
        camera_store.set_camera_event_controls(
            camera_key,
            process_end_events=payload.get("process_end_events")
            if isinstance(payload.get("process_end_events"), bool)
            else None,
            process_update_events=payload.get("process_update_events")
            if isinstance(payload.get("process_update_events"), bool)
            else None,
        )
        updates_per_event = payload.get("updates_per_event")
        if updates_per_event is not None:
            try:
                updates_per_event = max(1, min(2, int(updates_per_event)))
            except Exception:
                updates_per_event = None
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            if updates_per_event is not None:
                conn.execute(
                    "UPDATE cameras SET updates_per_event = ? WHERE camera_key = ?",
                    (updates_per_event, camera_key),
                )
                conn.commit()
        camera_store.set_camera_policy_fields(
            camera_key,
            display_name=payload.get("display_name")
            if isinstance(payload.get("display_name"), str)
            else _UNSET,
            prompt_preset=payload.get("prompt_preset")
            if payload.get("prompt_preset") is None or isinstance(payload.get("prompt_preset"), str)
            else _UNSET,
            confidence_threshold=payload.get("confidence_threshold")
            if isinstance(payload.get("confidence_threshold"), (int, float))
            else _UNSET,
            cooldown_s=payload.get("cooldown_s")
            if isinstance(payload.get("cooldown_s"), int)
            else _UNSET,
            vision_detail=payload.get("vision_detail")
            if isinstance(payload.get("vision_detail"), str)
            else _UNSET,
            phash_threshold=payload.get("phash_threshold")
            if isinstance(payload.get("phash_threshold"), int)
            else _UNSET,
            guest_preview_enabled=payload.get("guest_preview_enabled")
            if isinstance(payload.get("guest_preview_enabled"), bool)
            else _UNSET,
            security_capable=payload.get("security_capable")
            if isinstance(payload.get("security_capable"), bool)
            else _UNSET,
            security_mode=payload.get("security_mode")
            if isinstance(payload.get("security_mode"), bool)
            else _UNSET,
        )
        return self.get_camera(camera_key)

    def get_camera(self, camera_key: str) -> dict[str, Any]:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000;")
            row = conn.execute(
                """
                SELECT camera_key, display_name, enabled, discovered_first_ts, last_seen_ts,
                       prompt_preset, confidence_threshold, cooldown_s,
                       process_end_events, process_update_events, updates_per_event,
                       guest_preview_enabled, security_capable, security_mode,
                       setup_completed, vision_detail, phash_threshold, last_phash, last_phash_ts
                FROM cameras
                WHERE camera_key = ?
                LIMIT 1
                """,
                (camera_key,),
            ).fetchone()
        if row is None:
            raise KeyError(camera_key)
        return dict(row)

    def update_control(self, name: str, value: Any) -> dict[str, Any]:
        key, serialized = _normalize_control(name, value)
        camera_store = CameraStore(self.db_path)
        camera_store.upsert_kv(key, serialized)
        # Keep legacy key in sync for older readers.
        if name == "confidence_threshold":
            camera_store.upsert_kv("policy.default_confidence_threshold", serialized)
        return {"name": name, "kv_key": key, "value": serialized}

    def get_kv_many(self, keys: list[str]) -> dict[str, str]:
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            rows = conn.execute(
                f"SELECT k, v FROM kv WHERE k IN ({placeholders})",
                tuple(keys),
            ).fetchall()
        return {str(k): str(v) for k, v in rows}

    def upsert_kv_many(self, kv_pairs: dict[str, str]) -> None:
        if not kv_pairs:
            return
        camera_store = CameraStore(self.db_path)
        for key, value in kv_pairs.items():
            camera_store.upsert_kv(key, value)


def _normalize_control(name: str, value: Any) -> tuple[str, str]:
    mapping = {
        "enabled": "runtime.enabled",
        "monthly_budget": "budget.monthly_limit_usd",
        "confidence_threshold": "policy.defaults.confidence_threshold",
        "doorbell_only_mode": "runtime.doorbell_only_mode",
        "high_precision_mode": "runtime.high_precision_mode",
        "updates_per_event": "policy.default_updates_per_event",
    }
    if name not in mapping:
        raise ValueError(f"unsupported control name: {name}")
    key = mapping[name]
    if name in {"enabled", "doorbell_only_mode", "high_precision_mode"}:
        if isinstance(value, bool):
            return key, "1" if value else "0"
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "on", "yes"}:
                return key, "1"
            if lowered in {"0", "false", "off", "no"}:
                return key, "0"
        raise ValueError(f"invalid boolean value for {name}")
    if name == "monthly_budget":
        parsed = float(value)
        if parsed < 0:
            raise ValueError("monthly_budget must be >= 0")
        return key, f"{parsed:.2f}"
    if name == "confidence_threshold":
        parsed = float(value)
        if parsed > 1.0:
            parsed = parsed / 100.0
        if parsed < 0.0 or parsed > 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        return key, f"{parsed:.4f}".rstrip("0").rstrip(".")
    if name == "updates_per_event":
        parsed = int(value)
        if parsed not in {1, 2}:
            raise ValueError("updates_per_event must be 1 or 2")
        return key, str(parsed)
    raise ValueError(f"unsupported control name: {name}")


def _merge_rows_across_cameras(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        local_day = str(row.get("local_day", ""))
        local_hour = int(row.get("local_hour", 0) or 0)
        key = (local_day, local_hour)
        target = merged.setdefault(
            key,
            {
                "local_day": local_day,
                "local_hour": local_hour,
                "events_count": 0,
                "ai_calls_count": 0,
                "suppressed_count": 0,
            },
        )
        target["events_count"] += int(row.get("events_count", 0) or 0)
        target["ai_calls_count"] += int(row.get("ai_calls_count", 0) or 0)
        target["suppressed_count"] += int(row.get("suppressed_count", 0) or 0)
    return list(merged.values())


def _series_from_rows(rows: list[dict[str, Any]], *, average: bool) -> dict[str, Any]:
    by_hour: dict[int, dict[str, float]] = {
        hour: {"events": 0.0, "ai_calls": 0.0, "suppressed": 0.0}
        for hour in range(24)
    }
    covered_days: set[str] = set()
    for row in rows:
        local_day = str(row.get("local_day", "")).strip()
        hour = int(row.get("local_hour", 0) or 0)
        if local_day:
            covered_days.add(local_day)
        if hour < 0 or hour > 23:
            continue
        bucket = by_hour[hour]
        bucket["events"] += float(row.get("events_count", 0) or 0)
        bucket["ai_calls"] += float(row.get("ai_calls_count", 0) or 0)
        bucket["suppressed"] += float(row.get("suppressed_count", 0) or 0)
    days_covered = len(covered_days)
    divisor = float(days_covered) if average and days_covered > 0 else 1.0
    buckets: list[dict[str, Any]] = []
    totals = {"events": 0.0, "ai_calls": 0.0, "suppressed": 0.0}
    for hour in range(24):
        events_value = by_hour[hour]["events"] / divisor
        ai_calls_value = by_hour[hour]["ai_calls"] / divisor
        suppressed_value = by_hour[hour]["suppressed"] / divisor
        if average:
            events_value = round(events_value, 3)
            ai_calls_value = round(ai_calls_value, 3)
            suppressed_value = round(suppressed_value, 3)
        else:
            events_value = int(events_value)
            ai_calls_value = int(ai_calls_value)
            suppressed_value = int(suppressed_value)
        totals["events"] += float(events_value)
        totals["ai_calls"] += float(ai_calls_value)
        totals["suppressed"] += float(suppressed_value)
        buckets.append(
            {
                "hour": hour,
                "events": events_value,
                "ai_calls": ai_calls_value,
                "suppressed": suppressed_value,
            }
        )
    if average:
        totals = {
            "events": round(totals["events"], 3),
            "ai_calls": round(totals["ai_calls"], 3),
            "suppressed": round(totals["suppressed"], 3),
        }
    else:
        totals = {
            "events": int(totals["events"]),
            "ai_calls": int(totals["ai_calls"]),
            "suppressed": int(totals["suppressed"]),
        }
    return {
        "days_covered": days_covered,
        "buckets": buckets,
        "totals": totals,
    }
