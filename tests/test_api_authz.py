"""Tests for API auth/login and admin route authorization."""

from __future__ import annotations

import os
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    TestClient = None  # type: ignore[assignment]

from src.api.server import create_guest_api_app
from src.db import (
    CameraStore,
    DatabaseBootstrap,
    db_upsert_camera_view,
)
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
            preview = client.get("/api/cameras/doorbell/preview.jpg")
            self.assertEqual(preview.status_code, 404)

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

    def test_preview_route_enforces_camera_and_global_flags(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            camera_store = CameraStore(db_path)
            camera_store.upsert_discovered_camera("doorbell")
            config = SimpleNamespace(
                paths=SimpleNamespace(db_file=db_path),
                service=SimpleNamespace(slug="synthia_vision"),
            )
            app = create_guest_api_app(config)
            client = TestClient(app)

            # Default is camera preview disabled.
            denied_camera = client.get("/api/cameras/doorbell/preview.jpg")
            self.assertEqual(denied_camera.status_code, 403)

            camera_store.set_camera_policy_fields("doorbell", guest_preview_enabled=True)
            allowed = client.get("/api/cameras/doorbell/preview.jpg")
            # In tests we run without Frigate config, so allowed route returns 204.
            self.assertEqual(allowed.status_code, 204)

            camera_store.upsert_kv("ui.preview_enabled", "0")
            denied_global = client.get("/api/cameras/doorbell/preview.jpg")
            self.assertEqual(denied_global.status_code, 403)

    def test_admin_settings_apply_changes_preview_runtime_without_persist(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            camera_store = CameraStore(db_path)
            camera_store.upsert_discovered_camera("doorbell")
            camera_store.set_camera_policy_fields("doorbell", guest_preview_enabled=True)
            UserStore(db_path).create_user(username="admin", password="supersecurepass", role="admin")
            config = SimpleNamespace(
                paths=SimpleNamespace(db_file=db_path),
                service=SimpleNamespace(slug="synthia_vision"),
            )
            app = create_guest_api_app(config)
            client = TestClient(app)

            login = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "supersecurepass"},
            )
            self.assertEqual(login.status_code, 200)

            initial = client.get("/api/cameras/doorbell/preview.jpg")
            self.assertEqual(initial.status_code, 204)

            apply_resp = client.post(
                "/api/admin/settings/apply",
                json={"ui.preview_enabled": False},
            )
            self.assertEqual(apply_resp.status_code, 200)
            self.assertTrue(apply_resp.json().get("unsaved_changes"))

            runtime_denied = client.get("/api/cameras/doorbell/preview.jpg")
            self.assertEqual(runtime_denied.status_code, 403)

            # Persisted value is unchanged by apply(runtime).
            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                kv_value = conn.execute(
                    "SELECT v FROM kv WHERE k='ui.preview_enabled'"
                ).fetchone()
            self.assertIsNotNone(kv_value)
            self.assertEqual(str(kv_value[0]), "1")

    def test_generate_context_endpoint_saves_profile_and_view(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            snapshot_path = Path(td) / "setup.jpg"
            snapshot_path.write_bytes(b"fake-image-bytes")
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            CameraStore(db_path).upsert_discovered_camera("doorbell")
            db_upsert_camera_view(
                db_path,
                "doorbell",
                "main",
                {
                    "label": "Main",
                    "setup_snapshot_path": str(snapshot_path),
                },
            )
            UserStore(db_path).create_user(username="admin", password="supersecurepass", role="admin")
            config = SimpleNamespace(
                paths=SimpleNamespace(db_file=db_path),
                service=SimpleNamespace(slug="synthia_vision"),
                openai=SimpleNamespace(
                    api_key="test-key",
                    timeout_seconds=5,
                    max_output_tokens=200,
                    model="gpt-4o-mini",
                ),
            )
            app = create_guest_api_app(config)
            client = TestClient(app)
            login = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "supersecurepass"},
            )
            self.assertEqual(login.status_code, 200)

            class _FakeResponses:
                def create(self, **_kwargs):
                    payload = {
                        "schema_version": 1,
                        "environment": "outdoor",
                        "purpose": "doorbell_entry",
                        "view_type": "fixed",
                        "context_summary": "Entry and approach path coverage.",
                        "expected_activity": [
                            "approaching_entry",
                            "passing_by",
                            "delivery_dropoff",
                        ],
                        "zones": [],
                        "focus_notes": "Focus on doorway interactions.",
                        "delivery_focus": ["package"],
                        "privacy_mode": "no_identifying_details",
                    }
                    return SimpleNamespace(output_text=json.dumps(payload))

            class _FakeOpenAI:
                def __init__(self, *args, **kwargs):
                    _ = args, kwargs
                    self.responses = _FakeResponses()

            fake_openai = types.ModuleType("openai")
            fake_openai.OpenAI = _FakeOpenAI

            with patch.dict(sys.modules, {"openai": fake_openai}):
                response = client.post(
                    "/api/admin/cameras/doorbell/views/main/setup/generate_context",
                    json={
                        "environment": "outdoor",
                        "purpose": "doorbell_entry",
                        "view_type": "fixed",
                        "mounting_location": "front_porch",
                        "view_notes": "entry view",
                        "delivery_focus": ["package"],
                    },
                )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data.get("ok"))
            self.assertEqual(data["profile"]["setup_completed"], True)
            self.assertEqual(data["view"]["view_id"], "main")
            self.assertIn("approaching_entry", data["view"]["expected_activity"])


if __name__ == "__main__":
    unittest.main()
