"""Tests for Frigate discovery sync camera-state behavior."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.db import CameraStore, DatabaseBootstrap
from src.frigate.discovery_sync import sync_discovered_cameras_from_config


class FrigateDiscoverySyncTests(unittest.TestCase):
    def test_sync_does_not_override_user_camera_enabled_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            store = CameraStore(db_path)
            store.upsert_discovered_camera("doorbell")
            store.set_camera_enabled("doorbell", False)

            payload = {
                "cameras": {
                    "doorbell": {
                        "name": "Doorbell",
                        "enabled": True,
                        "detect": {"width": 1280, "height": 720, "fps": 5},
                        "audio": {"enabled": True},
                        "objects": {"track": ["person"]},
                        "snapshots": {"enabled": True},
                        "record": {"enabled": True},
                    }
                },
                "go2rtc": {"streams": {"doorbell_sub": "rtsp://example/doorbell_sub"}},
            }

            sync_discovered_cameras_from_config(
                db_path=db_path,
                frigate_config_payload=payload,
            )

            self.assertFalse(store.get_camera_enabled("doorbell"))


if __name__ == "__main__":
    unittest.main()
