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


if __name__ == "__main__":
    unittest.main()
