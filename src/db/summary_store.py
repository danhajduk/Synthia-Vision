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
        setup_completed = (self._get_kv("setup.completed") or "0") == "1"
        queue_depth_raw = self._get_kv("runtime.queue_depth") or "0"
        try:
            queue_depth = max(0, int(queue_depth_raw))
        except ValueError:
            queue_depth = 0
        return {
            "service_status": service_status,
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
        cost_monthly_by_camera = {
            str(camera): float(total) for camera, total in monthly_by_camera_rows
        }
        count_total = max(0, int(accepted_total))
        count_today = max(0, int(accepted_today))
        cost_avg_per_event = (cost_month2day_total / count_total) if count_total > 0 else 0.0
        tokens_avg_per_day = float(tokens_avg_per_request) * float(count_today)
        return {
            "cost_avg_per_event": float(cost_avg_per_event),
            "cost_daily_total": float(cost_daily_total),
            "cost_last": float(cost_last),
            "cost_month2day_total": float(cost_month2day_total),
            "cost_monthly_by_camera": cost_monthly_by_camera,
            "count_today": count_today,
            "count_today_date": today,
            "count_total": count_total,
            "tokens_avg_per_day": float(tokens_avg_per_day),
            "tokens_avg_per_request": float(tokens_avg_per_request),
        }

    def get_cameras_summary(self) -> dict[str, Any]:
        month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            cameras = conn.execute(
                """
                SELECT camera_key, display_name, enabled, discovered_first_ts, last_seen_ts
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
        for camera_key, display_name, enabled, first_ts, last_seen in cameras:
            key = str(camera_key)
            items.append(
                {
                    "camera_key": key,
                    "display_name": str(display_name),
                    "enabled": bool(int(enabled)),
                    "discovered_first_ts": str(first_ts),
                    "last_seen_ts": str(last_seen),
                    "monthly_cost": float(cost_map.get(key, 0.0)),
                }
            )
        return {
            "count": len(items),
            "items": items,
        }

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
