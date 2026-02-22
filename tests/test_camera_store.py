"""Tests for discovered camera persistence behavior."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.db import CameraStore, DatabaseBootstrap


class CameraStoreTests(unittest.TestCase):
    def test_new_camera_defaults_to_disabled_and_updates_last_seen(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            store = CameraStore(db_path)

            store.upsert_discovered_camera("front_door", last_seen_ts=1700000000.0)
            self.assertFalse(store.get_camera_enabled("front_door"))

            store.upsert_discovered_camera("front_door", last_seen_ts=1700000100.0)
            self.assertFalse(store.get_camera_enabled("front_door"))

    def test_missing_camera_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            store = CameraStore(db_path)
            self.assertIsNone(store.get_camera_enabled("unknown_cam"))

    def test_runtime_settings_and_camera_control_updates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            store = CameraStore(db_path)
            store.upsert_discovered_camera("livingroom")

            defaults = store.get_runtime_settings(
                "livingroom",
                default_process_end_events=True,
                default_process_update_events=False,
                default_updates_per_event=1,
            )
            self.assertFalse(defaults.enabled)
            self.assertTrue(defaults.process_end_events)
            self.assertFalse(defaults.process_update_events)
            self.assertEqual(defaults.updates_per_event, 1)

            store.set_camera_enabled("livingroom", True)
            store.set_camera_event_controls(
                "livingroom",
                process_end_events=False,
                process_update_events=True,
            )
            updated = store.get_runtime_settings(
                "livingroom",
                default_process_end_events=True,
                default_process_update_events=False,
                default_updates_per_event=1,
            )
            self.assertTrue(updated.enabled)
            self.assertFalse(updated.process_end_events)
            self.assertTrue(updated.process_update_events)

    def test_kv_upsert_writes_values(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            store = CameraStore(db_path)
            store.upsert_kv("runtime.queue_depth", "17")
            store.upsert_kv("runtime.queue_depth", "18")
            import sqlite3

            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                row = conn.execute("SELECT v FROM kv WHERE k='runtime.queue_depth'").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "18")


if __name__ == "__main__":
    unittest.main()
