"""Tests for API auth/login and admin route authorization."""

from __future__ import annotations

import os
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

    def test_guest_role_cannot_access_admin_routes(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            UserStore(db_path).create_user(username="viewer", password="supersecurepass", role="guest")
            config = SimpleNamespace(
                paths=SimpleNamespace(db_file=db_path),
                service=SimpleNamespace(slug="synthia_vision"),
            )
            app = create_guest_api_app(config)
            client = TestClient(app)

            login = client.post(
                "/api/auth/login",
                json={"username": "viewer", "password": "supersecurepass"},
            )
            self.assertEqual(login.status_code, 200)
            denied = client.get("/api/events")
            self.assertEqual(denied.status_code, 401)

    def test_login_sets_httponly_samesite_cookie(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            UserStore(db_path).create_user(username="admin", password="supersecurepass", role="admin")
            config = SimpleNamespace(
                paths=SimpleNamespace(db_file=db_path),
                service=SimpleNamespace(slug="synthia_vision"),
            )
            app = create_guest_api_app(config)
            client = TestClient(app)
            response = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "supersecurepass"},
            )
            self.assertEqual(response.status_code, 200)
            cookie = response.headers.get("set-cookie", "")
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=lax", cookie)

    def test_first_run_setup_requires_token_and_creates_admin_once(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        old_token = os.environ.get("FIRST_RUN_TOKEN")
        os.environ["FIRST_RUN_TOKEN"] = "abc123"
        try:
            with tempfile.TemporaryDirectory() as td:
                db_path = Path(td) / "synthia_vision.db"
                DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
                config = SimpleNamespace(
                    paths=SimpleNamespace(db_file=db_path),
                    service=SimpleNamespace(slug="synthia_vision"),
                )
                app = create_guest_api_app(config)
                client = TestClient(app)

                denied = client.post(
                    "/api/setup/first-run",
                    json={"username": "admin", "password": "verysecurepass"},
                )
                self.assertEqual(denied.status_code, 403)

                created = client.post(
                    "/api/setup/first-run",
                    json={
                        "username": "admin",
                        "password": "verysecurepass",
                        "token": "abc123",
                    },
                )
                self.assertEqual(created.status_code, 200)
                self.assertTrue(created.json()["ok"])
                self.assertEqual(created.json()["role"], "admin")

                again = client.post(
                    "/api/setup/first-run",
                    json={
                        "username": "admin2",
                        "password": "anothersecurepass",
                        "token": "abc123",
                    },
                )
                self.assertEqual(again.status_code, 403)
        finally:
            if old_token is None:
                os.environ.pop("FIRST_RUN_TOKEN", None)
            else:
                os.environ["FIRST_RUN_TOKEN"] = old_token


if __name__ == "__main__":
    unittest.main()
