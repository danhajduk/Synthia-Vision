"""Tests for camera setup profile/view DB helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.db import DatabaseBootstrap
from src.db.camera_setup_store import (
    db_get_camera_profile,
    db_get_camera_view,
    db_list_camera_views,
    db_upsert_camera_profile,
    db_upsert_camera_view,
)


class CameraSetupStoreTests(unittest.TestCase):
    def test_profile_crud_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()

            created = db_upsert_camera_profile(
                db_path,
                "doorbell",
                {
                    "environment": "outdoor",
                    "purpose": "doorbell_entry",
                    "view_type": "fixed",
                    "mounting_location": "front_porch",
                    "view_notes": "entry area",
                    "delivery_focus": ["package", "food"],
                    "setup_completed": True,
                    "default_view_id": "main",
                },
            )
            self.assertEqual(created["camera_key"], "doorbell")
            self.assertEqual(created["purpose"], "doorbell_entry")
            self.assertEqual(created["delivery_focus"], ["package", "food"])
            self.assertTrue(created["setup_completed"])

            loaded = db_get_camera_profile(db_path, "doorbell")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["environment"], "outdoor")
            self.assertEqual(loaded["default_view_id"], "main")

    def test_views_crud_roundtrip_and_context_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()

            saved = db_upsert_camera_view(
                db_path,
                "doorbell",
                "main",
                {
                    "label": "Main View",
                    "ha_preset_id": "ha_entry",
                    "setup_snapshot_path": "/tmp/setup.jpg",
                    "context_summary": "Entry coverage with front path.",
                    "expected_activity": ["approaching_entry", "passing_by", "delivery_dropoff"],
                    "zones": [{"zone_id": "entry_area", "label": "Entry", "notes": "front step"}],
                    "focus_notes": "Prioritize doorway interactions.",
                },
            )
            self.assertEqual(saved["camera_key"], "doorbell")
            self.assertEqual(saved["view_id"], "main")
            self.assertEqual(saved["ha_preset_id"], "ha_entry")
            self.assertEqual(len(saved["expected_activity"]), 3)
            self.assertEqual(saved["zones"][0]["zone_id"], "entry_area")

            loaded = db_get_camera_view(db_path, "doorbell", "main")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["context_summary"], "Entry coverage with front path.")
            self.assertIn("delivery_dropoff", loaded["expected_activity"])

            all_views = db_list_camera_views(db_path, "doorbell")
            self.assertEqual(len(all_views), 1)
            self.assertEqual(all_views[0]["view_id"], "main")


if __name__ == "__main__":
    unittest.main()

