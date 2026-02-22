"""Tests for SQLite schema bootstrap and seed behavior."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.db import DatabaseBootstrap


class DatabaseBootstrapTests(unittest.TestCase):
    def test_initialize_creates_schema_indexes_and_seed_kv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            bootstrap = DatabaseBootstrap(
                db_path=db_path,
                schema_sql_path=Path("Documents/schema.sql"),
            )
            bootstrap.initialize()

            self.assertTrue(db_path.exists())
            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                for required in ("kv", "users", "cameras", "events", "metrics", "errors"):
                    self.assertIn(required, tables)

                indexes = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='index'"
                    )
                }
                for required in (
                    "idx_events_ts",
                    "idx_events_camera_ts",
                    "idx_events_accepted_ts",
                    "idx_metrics_event_id",
                    "idx_cameras_last_seen",
                    "idx_errors_ts",
                ):
                    self.assertIn(required, indexes)

                kv = {
                    row[0]: row[1]
                    for row in conn.execute("SELECT k, v FROM kv")
                }
                self.assertEqual(kv.get("db.schema_version"), "1")
                self.assertEqual(kv.get("ai.preprocess.crop_enabled"), "0")
                self.assertIn("budget.current_month", kv)

    def test_initialize_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            bootstrap = DatabaseBootstrap(
                db_path=db_path,
                schema_sql_path=Path("Documents/schema.sql"),
            )
            bootstrap.initialize()
            bootstrap.initialize()
            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                count = conn.execute("SELECT COUNT(*) FROM kv WHERE k='db.schema_version'").fetchone()[0]
                self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
