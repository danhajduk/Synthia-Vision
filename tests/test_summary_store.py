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
            camera_store.upsert_kv("runtime.queue_depth", "3")
            camera_store.upsert_kv("service.status", "enabled")

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
                description="someone at door",
            )
            event_store.insert_metric(
                event_id="evt-1",
                prompt_tokens=100,
                completion_tokens=20,
                cost_usd=0.0012,
                model="gpt-4.1-mini",
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

            cameras = store.get_cameras_summary()
            self.assertEqual(cameras["count"], 1)
            self.assertEqual(cameras["items"][0]["camera_key"], "doorbell")

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
