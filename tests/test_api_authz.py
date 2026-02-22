"""Tests for API auth/login and admin route authorization."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    TestClient = None  # type: ignore[assignment]

from src.api.server import create_guest_api_app
from src.db import CameraStore, DatabaseBootstrap
from src.auth.user_store import UserStore


class APIAuthzTests(unittest.TestCase):
    def test_admin_routes_require_login_and_work_after_login(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            UserStore(db_path).create_user(username="admin", password="supersecurepass", role="admin")
            CameraStore(db_path).upsert_discovered_camera("doorbell")

            config = SimpleNamespace(
                paths=SimpleNamespace(db_file=db_path),
                service=SimpleNamespace(slug="synthia_vision"),
            )
            app = create_guest_api_app(config)
            client = TestClient(app)

            denied = client.get("/api/events")
            self.assertEqual(denied.status_code, 401)

            login = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "supersecurepass"},
            )
            self.assertEqual(login.status_code, 200)
            self.assertTrue(login.json()["ok"])

            allowed = client.get("/api/events")
            self.assertEqual(allowed.status_code, 200)
            self.assertIn("items", allowed.json())

    def test_guest_routes_remain_accessible_without_login(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            config = SimpleNamespace(
                paths=SimpleNamespace(db_file=db_path),
                service=SimpleNamespace(slug="synthia_vision"),
            )
            app = create_guest_api_app(config)
            client = TestClient(app)
            status = client.get("/api/status")
            self.assertEqual(status.status_code, 200)
            metrics = client.get("/api/metrics/summary")
            self.assertEqual(metrics.status_code, 200)
            cameras = client.get("/api/cameras/summary")
            self.assertEqual(cameras.status_code, 200)


if __name__ == "__main__":
    unittest.main()
