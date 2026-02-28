"""SQLite summary queries used by guest/admin APIs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SummaryStore:
    db_path: Path

    def get_status_summary(self) -> dict[str, Any]:
        service_status = self._get_kv("service.status") or "unknown"
        heartbeat_ts = self._get_kv("runtime.heartbeat_ts") or ""
        current_mode = self._get_kv("runtime.current_mode") or self._get_kv("modes.current") or "normal"
        setup_completed = (self._get_kv("setup.completed") or "0") == "1"
        queue_depth_raw = self._get_kv("runtime.queue_depth") or "0"
        try:
            queue_depth = max(0, int(queue_depth_raw))
        except ValueError:
            queue_depth = 0
        return {
            "service_status": service_status,
            "heartbeat_ts": heartbeat_ts,
            "current_mode": str(current_mode),
            "setup_completed": setup_completed,
            "queue_depth": queue_depth,
            "db_ready": self.db_path.exists(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_metrics_summary(self) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date().isoformat()
        month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            accepted_total = _single_int(
                conn,
                "SELECT COUNT(*) FROM events WHERE accepted=1",
            )
            accepted_today = _single_int(
                conn,
                "SELECT COUNT(*) FROM events WHERE accepted=1 AND substr(ts,1,10)=?",
                (today,),
            )
            suppressed_total = _single_int(
                conn,
                """
                SELECT COUNT(*) FROM events
                WHERE result_status='suppressed' AND reject_reason='suppressed_duplicate'
                """,
            )
            suppressed_today = _single_int(
                conn,
                """
                SELECT COUNT(*) FROM events
                WHERE result_status='suppressed' AND reject_reason='suppressed_duplicate' AND substr(ts,1,10)=?
                """,
                (today,),
            )
            cost_last = _single_float(
                conn,
                "SELECT COALESCE(cost_usd, 0) FROM metrics ORDER BY created_ts DESC LIMIT 1",
            )
            cost_daily_total = _single_float(
                conn,
                """
                SELECT COALESCE(SUM(m.cost_usd), 0)
                FROM metrics m
                JOIN events e ON e.event_id = m.event_id
                WHERE substr(e.ts,1,10)=?
                """,
                (today,),
            )
            cost_month2day_total = _single_float(
                conn,
                """
                SELECT COALESCE(SUM(m.cost_usd), 0)
                FROM metrics m
                JOIN events e ON e.event_id = m.event_id
                WHERE substr(e.ts,1,7)=?
                """,
                (month_prefix,),
            )
            tokens_avg_per_request = _single_float(
                conn,
                """
                SELECT COALESCE(AVG(COALESCE(prompt_tokens,0) + COALESCE(completion_tokens,0)), 0)
                FROM metrics
                """,
            )
            tokens_today_total = _single_int(
                conn,
                """
                SELECT COALESCE(SUM(COALESCE(m.prompt_tokens,0) + COALESCE(m.completion_tokens,0)), 0)
                FROM metrics m
                JOIN events e ON e.event_id = m.event_id
                WHERE substr(e.ts,1,10)=?
                """,
                (today,),
            )
            avg_ai_confidence_today = _single_float(
                conn,
                """
                SELECT COALESCE(AVG(ai_confidence), 0)
                FROM events
                WHERE ai_confidence IS NOT NULL AND substr(ts,1,10)=?
                """,
                (today,),
            )
            monthly_by_camera_rows = conn.execute(
                """
                SELECT e.camera, COALESCE(SUM(m.cost_usd), 0)
                FROM metrics m
                JOIN events e ON e.event_id = m.event_id
                WHERE substr(e.ts,1,7)=?
                GROUP BY e.camera
                ORDER BY e.camera ASC
                """,
                (month_prefix,),
            ).fetchall()
            suppressed_by_camera_rows = conn.execute(
                """
                SELECT camera, COUNT(*)
                FROM events
                WHERE result_status='suppressed' AND reject_reason='suppressed_duplicate'
                GROUP BY camera
                ORDER BY camera ASC
                """
            ).fetchall()
            queue_depth = _single_int(
                conn,
                "SELECT COALESCE(v, '0') FROM kv WHERE k = 'runtime.queue_depth'",
            )
            dropped_events_total = _single_int(
                conn,
                "SELECT COALESCE(v, '0') FROM kv WHERE k = 'counters.dropped_events_total'",
            )
            dropped_update_total = _single_int(
                conn,
                "SELECT COALESCE(v, '0') FROM kv WHERE k = 'counters.dropped_update_total'",
            )
            dropped_queue_full_total = _single_int(
                conn,
                "SELECT COALESCE(v, '0') FROM kv WHERE k = 'counters.dropped_queue_full_total'",
            )
        cost_monthly_by_camera = {
            str(camera): float(total) for camera, total in monthly_by_camera_rows
        }
        count_total = max(0, int(accepted_total))
        count_today = max(0, int(accepted_today))
        suppressed_total_count = max(0, int(suppressed_total))
        suppressed_today_count = max(0, int(suppressed_today))
        suppressed_rate_today = (
            float(suppressed_today_count) / float(suppressed_today_count + count_today)
            if (suppressed_today_count + count_today) > 0
            else 0.0
        )
        cost_avg_per_event = (cost_month2day_total / count_total) if count_total > 0 else 0.0
        tokens_avg_per_day = float(tokens_avg_per_request) * float(count_today)
        avg_tokens_per_event = (float(tokens_today_total) / float(count_today)) if count_today > 0 else 0.0
        suppressed_count_by_camera = {
            str(camera): int(total) for camera, total in suppressed_by_camera_rows
        }
        return {
            "cost_avg_per_event": float(cost_avg_per_event),
            "cost_daily_total": float(cost_daily_total),
            "cost_last": float(cost_last),
            "cost_month2day_total": float(cost_month2day_total),
            "cost_monthly_by_camera": cost_monthly_by_camera,
            "count_today": count_today,
            "count_today_date": today,
            "count_total": count_total,
            "suppressed_count_total": suppressed_total_count,
            "suppressed_count_today": suppressed_today_count,
            "suppressed_rate_today": float(suppressed_rate_today),
            "suppressed_count_by_camera": suppressed_count_by_camera,
            "queue_depth": max(0, int(queue_depth)),
            "dropped_events_total": max(0, int(dropped_events_total)),
            "dropped_update_total": max(0, int(dropped_update_total)),
            "dropped_queue_full_total": max(0, int(dropped_queue_full_total)),
            "tokens_avg_per_day": float(tokens_avg_per_day),
            "tokens_avg_per_request": float(tokens_avg_per_request),
            "tokens_today_total": int(tokens_today_total),
            "avg_tokens_per_event": float(avg_tokens_per_event),
            "avg_ai_confidence_today": float(avg_ai_confidence_today),
        }

    def get_cameras_summary(self) -> dict[str, Any]:
        month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            cameras = conn.execute(
                """
                SELECT camera_key, display_name, enabled, discovered_first_ts, last_seen_ts, setup_completed
                FROM cameras
                ORDER BY camera_key ASC
                """
            ).fetchall()
            costs = conn.execute(
                """
                SELECT e.camera, COALESCE(SUM(m.cost_usd), 0)
                FROM metrics m
                JOIN events e ON e.event_id = m.event_id
                WHERE substr(e.ts,1,7)=?
                GROUP BY e.camera
                """,
                (month_prefix,),
            ).fetchall()
            cost_map = {str(camera): float(total) for camera, total in costs}
        items: list[dict[str, Any]] = []
        for camera_key, display_name, enabled, first_ts, last_seen, setup_completed in cameras:
            key = str(camera_key)
            items.append(
                {
                    "camera_key": key,
                    "display_name": str(display_name),
                    "enabled": bool(int(enabled)),
                    "setup_completed": bool(int(setup_completed or 0)),
                    "discovered_first_ts": str(first_ts),
                    "last_seen_ts": str(last_seen),
                    "monthly_cost": float(cost_map.get(key, 0.0)),
                }
            )
        return {
            "count": len(items),
            "items": items,
        }

    def get_guest_status_payload(self) -> dict[str, Any]:
        # Keep guest payload intentionally narrow for iframe-safe dashboards.
        status = self.get_status_summary()
        return {
            "service_status": status.get("service_status", "unknown"),
            "db_ready": bool(status.get("db_ready", False)),
            "heartbeat_ts": str(status.get("heartbeat_ts", "")),
            "timestamp": status.get("timestamp"),
        }

    def get_guest_metrics_payload(self) -> dict[str, Any]:
        metrics = self.get_metrics_summary()
        return {
            "count_total": int(metrics.get("count_total", 0)),
            "ai_calls_today": int(metrics.get("count_today", 0)),
            "count_today": int(metrics.get("count_today", 0)),
            "count_today_date": str(metrics.get("count_today_date", "")),
            "queue_depth": int(metrics.get("queue_depth", 0)),
            "suppressed_count_total": int(metrics.get("suppressed_count_total", 0)),
            "suppressed_count_today": int(metrics.get("suppressed_count_today", 0)),
            "suppressed_rate_today": float(metrics.get("suppressed_rate_today", 0.0)),
            "suppressed_count_by_camera": dict(metrics.get("suppressed_count_by_camera", {})),
            "dropped_events_total": int(metrics.get("dropped_events_total", 0)),
            "dropped_update_total": int(metrics.get("dropped_update_total", 0)),
            "dropped_queue_full_total": int(metrics.get("dropped_queue_full_total", 0)),
            "cost_last": float(metrics.get("cost_last", 0.0)),
            "cost_daily_total": float(metrics.get("cost_daily_total", 0.0)),
            "cost_month2day_total": float(metrics.get("cost_month2day_total", 0.0)),
            "cost_avg_per_event": float(metrics.get("cost_avg_per_event", 0.0)),
            "avg_cost_per_event_usd": float(metrics.get("cost_avg_per_event", 0.0)),
            "tokens_avg_per_request": float(metrics.get("tokens_avg_per_request", 0.0)),
            "tokens_avg_per_day": float(metrics.get("tokens_avg_per_day", 0.0)),
            "tokens_today_total": int(metrics.get("tokens_today_total", 0)),
            "avg_tokens_per_event": float(metrics.get("avg_tokens_per_event", 0.0)),
            "avg_ai_confidence_today": float(metrics.get("avg_ai_confidence_today", 0.0)),
            "cost_monthly_by_camera": dict(metrics.get("cost_monthly_by_camera", {})),
        }

    def get_guest_cameras_payload(self) -> dict[str, Any]:
        cameras = self.get_cameras_summary()
        sanitized_items: list[dict[str, Any]] = []
        for item in cameras.get("items", []):
            if not isinstance(item, dict):
                continue
            if not bool(item.get("setup_completed", False)):
                continue
            sanitized_items.append(
                {
                    "camera_key": str(item.get("camera_key", "")),
                    "display_name": str(item.get("display_name", "")),
                    "enabled": bool(item.get("enabled", False)),
                    "last_seen_ts": str(item.get("last_seen_ts", "")),
                    "monthly_cost": float(item.get("monthly_cost", 0.0)),
                }
            )
        return {
            "count": len(sanitized_items),
            "items": sanitized_items,
        }

    def get_guest_camera_cards(self, *, service_status: str = "unknown") -> list[dict[str, Any]]:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000;")
            rows = conn.execute(
                """
                SELECT
                  c.camera_key,
                  c.display_name,
                  c.enabled,
                  c.guest_preview_enabled,
                  c.last_seen_ts,
                  e.action AS last_action,
                  e.confidence AS last_confidence,
                  COALESCE(cm.monthly_cost, 0.0) AS mtd_cost
                FROM cameras c
                LEFT JOIN (
                  SELECT e1.camera, e1.action, e1.confidence, e1.id
                  FROM events e1
                  JOIN (
                    SELECT camera, MAX(id) AS max_id
                    FROM events
                    GROUP BY camera
                  ) latest ON latest.camera = e1.camera AND latest.max_id = e1.id
                ) e ON e.camera = c.camera_key
                LEFT JOIN (
                  SELECT e.camera, COALESCE(SUM(m.cost_usd), 0.0) AS monthly_cost
                  FROM metrics m
                  JOIN events e ON e.event_id = m.event_id
                  WHERE substr(e.ts, 1, 7) = ?
                  GROUP BY e.camera
                ) cm ON cm.camera = c.camera_key
                WHERE c.setup_completed = 1
                ORDER BY c.camera_key ASC
                """,
                (datetime.now(timezone.utc).strftime("%Y-%m"),),
            ).fetchall()

        cards: list[dict[str, Any]] = []
        for row in rows:
            enabled = bool(int(row["enabled"]))
            status = "disabled"
            if enabled:
                status = "degraded" if service_status == "degraded" else "ok"
            confidence_raw = row["last_confidence"]
            confidence_pct: int | None
            if confidence_raw is None:
                confidence_pct = None
            else:
                confidence_pct = max(0, min(100, int(round(float(confidence_raw) * 100.0))))
            cards.append(
                {
                    "camera_key": str(row["camera_key"]),
                    "display_name": str(row["display_name"]),
                    "enabled": enabled,
                    "guest_preview_enabled": bool(int(row["guest_preview_enabled"])),
                    "status": status,
                    "last_seen_ts": str(row["last_seen_ts"]),
                    "last_action": str(row["last_action"]) if row["last_action"] else None,
                    "last_confidence": confidence_pct,
                    "mtd_cost": float(row["mtd_cost"]),
                }
            )
        return cards

    def _get_kv(self, key: str) -> str | None:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            row = conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
        if row is None:
            return None
        return str(row[0])


def _single_int(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return 0
    return int(row[0])


def _single_float(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> float:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return 0.0
    return float(row[0])
