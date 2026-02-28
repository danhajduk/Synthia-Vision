"""Tests for admin API persistence helpers."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.db import AdminStore, CameraStore, DatabaseBootstrap, EventStore
from src.models import FrigateEvent


class AdminStoreTests(unittest.TestCase):
    def test_events_errors_cameras_and_controls(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            camera_store = CameraStore(db_path)
            camera_store.upsert_discovered_camera("doorbell")
            event_store = EventStore(db_path)
            event = FrigateEvent(
                event_id="evt-admin-1",
                camera="doorbell",
                label="person",
                event_type="end",
                event_ts=datetime.now(timezone.utc).timestamp(),
            )
            event_store.upsert_event(event=event, accepted=True, result_status="ok")
            event_store.upsert_event(
                event=FrigateEvent(
                    event_id="evt-admin-2",
                    camera="doorbell",
                    label="person",
                    event_type="end",
                    event_ts=datetime.now(timezone.utc).timestamp(),
                ),
                accepted=True,
                result_status="ok",
                ai_confidence=0.91,
                risk_score=0.88,
            )
            event_store.insert_metric(event_id=event.event_id, prompt_tokens=10, completion_tokens=2)
            event_store.insert_error(
                component="ai",
                message="openai_failed",
                detail="mock",
                event_id=event.event_id,
                camera=event.camera,
            )

            store = AdminStore(db_path)
            events = store.list_events(limit=10)
            self.assertEqual(events["total"], 2)
            sorted_events = store.list_events(limit=10, sort_by="risk_score", sort_dir="desc")
            self.assertEqual(sorted_events["items"][0]["event_id"], "evt-admin-2")
            self.assertAlmostEqual(float(sorted_events["items"][0]["risk_score"]), 0.88, places=6)
            detail = store.get_event("evt-admin-1")
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["event_id"], "evt-admin-1")
            self.assertEqual(len(detail["metrics"]), 1)

            errors = store.list_errors(limit=10)
            self.assertEqual(errors["total"], 1)
            self.assertEqual(errors["items"][0]["component"], "ai")

            updated = store.update_camera(
                "doorbell",
                {
                    "enabled": True,
                    "display_name": "Front Door",
                    "process_end_events": True,
                    "process_update_events": False,
                    "updates_per_event": 2,
                    "phash_threshold": 7,
                },
            )
            self.assertEqual(updated["display_name"], "Front Door")
            self.assertEqual(int(updated["enabled"]), 1)
            self.assertEqual(int(updated["updates_per_event"]), 2)

            control = store.update_control("enabled", True)
            self.assertEqual(control["kv_key"], "runtime.enabled")
            self.assertEqual(control["value"], "1")

            heatmap = store.get_timeline_heatmap(hours=24)
            self.assertEqual(heatmap["window_hours"], 24)
            self.assertGreaterEqual(len(heatmap["items"]), 1)
            first = heatmap["items"][0]
            self.assertEqual(first["camera"], "doorbell")
            self.assertGreaterEqual(int(first["events_count"]), 1)

    def test_metrics_heatmap_ranges_and_complete_day_rules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            event_store = EventStore(db_path)
            now_local = datetime.now().astimezone().replace(minute=23, second=0, microsecond=0)
            now_utc = now_local.astimezone(timezone.utc)
            today_local = now_local.replace(hour=10, minute=0, second=0, microsecond=0)
            yesterday_local = today_local - timedelta(days=1)
            older_local = today_local - timedelta(days=8)

            event_store.upsert_event(
                event=FrigateEvent(
                    event_id="evt-today",
                    camera="doorbell",
                    label="person",
                    event_type="end",
                    event_ts=today_local.astimezone(timezone.utc).timestamp(),
                ),
                accepted=True,
                result_status="ok",
            )
            event_store.upsert_event(
                event=FrigateEvent(
                    event_id="evt-yesterday",
                    camera="doorbell",
                    label="person",
                    event_type="end",
                    event_ts=yesterday_local.astimezone(timezone.utc).timestamp(),
                ),
                accepted=True,
                result_status="suppressed",
                reject_reason="suppressed_duplicate",
            )
            event_store.insert_metric(event_id="evt-yesterday", prompt_tokens=12, completion_tokens=2)
            event_store.upsert_event(
                event=FrigateEvent(
                    event_id="evt-older",
                    camera="livingroom",
                    label="person",
                    event_type="end",
                    event_ts=older_local.astimezone(timezone.utc).timestamp(),
                ),
                accepted=True,
                result_status="ok",
            )

            store = AdminStore(db_path)
            heatmap_24h = store.get_metrics_heatmap(range_type="24h", camera="all", now_utc=now_utc)
            self.assertEqual(heatmap_24h["range_type"], "24h")
            self.assertEqual(len(heatmap_24h["buckets"]), 24)
            self.assertFalse(bool(heatmap_24h["is_complete_days_only"]))
            self.assertIn("per_camera", heatmap_24h)

            heatmap_avg7d = store.get_metrics_heatmap(range_type="avg7d", camera="all", now_utc=now_utc)
            self.assertEqual(heatmap_avg7d["range_type"], "avg7d")
            self.assertEqual(len(heatmap_avg7d["buckets"]), 24)
            self.assertTrue(bool(heatmap_avg7d["is_complete_days_only"]))
            self.assertEqual(int(heatmap_avg7d["days_covered"]), 1)
            hour_bucket = heatmap_avg7d["buckets"][10]
            self.assertEqual(int(hour_bucket["hour"]), 10)
            self.assertEqual(float(hour_bucket["events"]), 1.0)
            self.assertEqual(float(hour_bucket["ai_calls"]), 1.0)
            self.assertEqual(float(hour_bucket["suppressed"]), 1.0)

            heatmap_avg30d = store.get_metrics_heatmap(range_type="avg30d", camera="doorbell", now_utc=now_utc)
            self.assertEqual(heatmap_avg30d["range_type"], "avg30d")
            self.assertEqual(len(heatmap_avg30d["buckets"]), 24)
            self.assertTrue(bool(heatmap_avg30d["is_complete_days_only"]))


if __name__ == "__main__":
    unittest.main()
