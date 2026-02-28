"""Tests for guest API summary query store."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.db import DatabaseBootstrap, SummaryStore
from src.models import FrigateEvent
from src.db.event_store import EventStore
from src.db.camera_store import CameraStore


class SummaryStoreTests(unittest.TestCase):
    def test_metrics_and_cameras_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()

            camera_store = CameraStore(db_path)
            camera_store.upsert_discovered_camera("doorbell")
            camera_store.set_camera_enabled("doorbell", True)
            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                conn.execute(
                    "UPDATE cameras SET setup_completed = 1 WHERE camera_key = ?",
                    ("doorbell",),
                )
                conn.commit()
            camera_store.upsert_kv("runtime.queue_depth", "3")
            camera_store.upsert_kv("service.status", "enabled")
            camera_store.upsert_kv("runtime.heartbeat_ts", "2026-02-23T10:00:00+00:00")

            event_store = EventStore(db_path)
            event = FrigateEvent(
                event_id="evt-1",
                camera="doorbell",
                label="person",
                event_type="end",
                event_ts=datetime.now(timezone.utc).timestamp(),
            )
            event_store.upsert_event(
                event=event,
                accepted=True,
                result_status="ok",
                action="person_at_door",
                subject_type="human",
                confidence=0.91,
                ai_confidence=0.91,
                ai_reason="A person remained at the front door and appeared to wait.",
                description="someone at door",
            )
            event_store.insert_metric(
                event_id="evt-1",
                prompt_tokens=100,
                completion_tokens=20,
                cost_usd=0.0012,
                model="gpt-4.1-mini",
            )
            suppressed_event = FrigateEvent(
                event_id="evt-2",
                camera="doorbell",
                label="person",
                event_type="update",
                event_ts=datetime.now(timezone.utc).timestamp(),
            )
            event_store.upsert_event(
                event=suppressed_event,
                accepted=False,
                reject_reason="suppressed_duplicate",
                dedupe_hit=True,
                suppressed_by_event_id="evt-1",
                result_status="suppressed",
            )

            store = SummaryStore(db_path)
            status = store.get_status_summary()
            self.assertEqual(status["service_status"], "enabled")
            self.assertEqual(status["queue_depth"], 3)
            self.assertTrue(status["db_ready"])

            metrics = store.get_metrics_summary()
            self.assertEqual(metrics["count_total"], 1)
            self.assertGreaterEqual(metrics["cost_last"], 0.0)
            self.assertIn("doorbell", metrics["cost_monthly_by_camera"])
            self.assertEqual(metrics["tokens_today_total"], 120)
            self.assertEqual(metrics["tokens_24h_total"], 120)
            self.assertEqual(metrics["tokens_month2day_total"], 120)
            self.assertEqual(metrics["avg_tokens_per_event"], 120.0)
            self.assertEqual(metrics["suppressed_count_total"], 1)
            self.assertEqual(metrics["suppressed_count_today"], 1)
            self.assertIn("doorbell", metrics["suppressed_count_by_camera"])
            self.assertAlmostEqual(metrics["avg_ai_confidence_today"], 0.91, places=6)
            self.assertGreaterEqual(metrics["cost_24h_total"], 0.0)
            self.assertGreaterEqual(metrics["burn_rate_24h"], 0.0)
            self.assertGreaterEqual(metrics["projected_month_total"], 0.0)

            cameras = store.get_cameras_summary()
            self.assertEqual(cameras["count"], 1)
            self.assertEqual(cameras["items"][0]["camera_key"], "doorbell")

            guest_status = store.get_guest_status_payload()
            self.assertEqual(
                set(guest_status.keys()),
                {"service_status", "db_ready", "heartbeat_ts", "timestamp"},
            )
            self.assertEqual(guest_status["heartbeat_ts"], "2026-02-23T10:00:00+00:00")
            self.assertNotIn("queue_depth", guest_status)
            self.assertNotIn("setup_completed", guest_status)

            guest_metrics = store.get_guest_metrics_payload()
            self.assertNotIn("reject_reason", guest_metrics)
            self.assertNotIn("skipped_openai_reason", guest_metrics)
            self.assertNotIn("description", guest_metrics)
            self.assertEqual(guest_metrics["tokens_today_total"], 120)
            self.assertEqual(guest_metrics["avg_tokens_per_event"], 120.0)
            self.assertEqual(guest_metrics["avg_cost_per_event_usd"], guest_metrics["cost_avg_per_event"])
            self.assertEqual(guest_metrics["ai_calls_today"], guest_metrics["count_today"])
            self.assertEqual(guest_metrics["suppressed_count_total"], 1)
            self.assertEqual(guest_metrics["suppressed_count_today"], 1)
            self.assertAlmostEqual(guest_metrics["avg_ai_confidence_today"], 0.91, places=6)
            self.assertEqual(guest_metrics["tokens_24h_total"], 120)
            self.assertEqual(guest_metrics["tokens_month2day_total"], 120)

            guest_cameras = store.get_guest_cameras_payload()
            self.assertEqual(guest_cameras["count"], 1)
            item = guest_cameras["items"][0]
            self.assertNotIn("discovered_first_ts", item)
            self.assertNotIn("description", item)
            self.assertNotIn("reject_reason", item)

    def test_status_defaults_when_kv_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                conn.execute("DELETE FROM kv WHERE k IN ('service.status', 'runtime.queue_depth')")
                conn.commit()
            status = SummaryStore(db_path).get_status_summary()
            self.assertEqual(status["service_status"], "unknown")
            self.assertEqual(status["queue_depth"], 0)


if __name__ == "__main__":
    unittest.main()
