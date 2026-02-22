"""Tests for admin API persistence helpers."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
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
            self.assertEqual(events["total"], 1)
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


if __name__ == "__main__":
    unittest.main()
