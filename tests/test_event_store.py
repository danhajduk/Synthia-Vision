"""Tests for SQLite event/metrics/error journaling helpers."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.db import DatabaseBootstrap, EventStore
from src.models import FrigateEvent


class EventStoreTests(unittest.TestCase):
    def test_upsert_event_then_update_result_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            store = EventStore(db_path)
            event = FrigateEvent(
                event_id="evt-1",
                camera="doorbell",
                label="person",
                event_type="end",
                event_ts=1700000000.0,
            )
            store.upsert_event(event=event, accepted=True, result_status="processing")
            store.upsert_event(
                event=event,
                accepted=True,
                result_status="ok",
                action="person_at_door",
                subject_type="human",
                confidence=0.88,
                description="visitor at the door",
                snapshot_bytes=12345,
                image_width=1280,
                image_height=720,
                vision_detail="low",
            )

            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                row = conn.execute(
                    """
                    SELECT accepted, result_status, action, subject_type, confidence, description,
                           snapshot_bytes, image_width, image_height, vision_detail
                    FROM events WHERE event_id = 'evt-1'
                    """
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 1)
            self.assertEqual(row[1], "ok")
            self.assertEqual(row[2], "person_at_door")
            self.assertEqual(row[3], "human")
            self.assertAlmostEqual(float(row[4]), 0.88, places=6)
            self.assertEqual(row[5], "visitor at the door")
            self.assertEqual(row[6], 12345)
            self.assertEqual(row[7], 1280)
            self.assertEqual(row[8], 720)
            self.assertEqual(row[9], "low")

    def test_insert_metric_and_error_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            store = EventStore(db_path)
            event = FrigateEvent(
                event_id="evt-2",
                camera="livingroom",
                label="person",
                event_type="end",
                event_ts=1700000001.0,
            )
            store.upsert_event(event=event, accepted=True, result_status="processing")
            store.insert_metric(
                event_id="evt-2",
                prompt_tokens=120,
                completion_tokens=35,
                cost_usd=0.0012,
                model="gpt-4.1-mini",
                skipped_openai_reason=None,
            )
            store.insert_error(
                component="ai",
                message="openai_failed",
                detail="rate limited",
                event_id="evt-2",
                camera="livingroom",
            )

            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                metric_row = conn.execute(
                    "SELECT prompt_tokens, completion_tokens, cost_usd, model FROM metrics WHERE event_id='evt-2'"
                ).fetchone()
                error_row = conn.execute(
                    "SELECT component, message, detail, event_id, camera FROM errors WHERE event_id='evt-2'"
                ).fetchone()
            self.assertEqual(metric_row, (120, 35, 0.0012, "gpt-4.1-mini"))
            self.assertEqual(error_row, ("ai", "openai_failed", "rate limited", "evt-2", "livingroom"))


if __name__ == "__main__":
    unittest.main()
