"""Tests for UI guest/admin route wiring."""

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
from src.auth.user_store import UserStore
from src.db import CameraStore, DatabaseBootstrap, EventStore
from src.models import FrigateEvent


class UIRouteTests(unittest.TestCase):
    def _build_client(self) -> TestClient:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        db_path = Path(td.name) / "synthia_vision.db"
        DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
        camera_store = CameraStore(db_path)
        camera_store.upsert_discovered_camera("doorbell")
        camera_store.set_camera_enabled("doorbell", True)
        event_store = EventStore(db_path)
        event = FrigateEvent(
            event_id="evt-1",
            camera="doorbell",
            label="person",
            event_type="end",
        )
        event_store.upsert_event(
            event=event,
            accepted=True,
            result_status="ok",
            action="person_detected",
            subject_type="human",
            confidence=0.97,
            description="someone at the door",
        )
        event_store.insert_metric(
            event_id="evt-1",
            prompt_tokens=100,
            completion_tokens=20,
            cost_usd=0.0012,
            model="gpt-4.1-mini",
        )
        UserStore(db_path).create_user(username="admin", password="supersecurepass", role="admin")
        app = create_guest_api_app(
            SimpleNamespace(
                paths=SimpleNamespace(db_file=db_path),
                service=SimpleNamespace(slug="synthia_vision", name="Synthia Vision"),
            )
        )
        return TestClient(app)

    def test_guest_ui_layout_contract_basics(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        client = self._build_client()
        response = client.get("/ui")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Synthia Vision", html)
        self.assertIn("Health", html)
        self.assertIn("Queue", html)
        self.assertIn("Cost Today", html)
        self.assertIn("AI Calls", html)
        self.assertIn("Cameras", html)
        self.assertIn("Guest view: summaries only", html)
        self.assertNotIn("sidebar", html.lower())

    def test_admin_pages_redirect_to_login_when_unauthenticated(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        client = self._build_client()
        response = client.get("/ui/admin", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/ui/login", response.headers.get("location", ""))

    def test_ui_login_sets_session_and_allows_admin_page(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        client = self._build_client()
        login = client.post(
            "/ui/login",
            data={"username": "admin", "password": "supersecurepass"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)
        self.assertIn("/ui/admin", login.headers.get("location", ""))
        cookie = login.headers.get("set-cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=lax", cookie)

        admin = client.get("/ui/admin")
        self.assertEqual(admin.status_code, 200)
        self.assertIn("Admin", admin.text)
        self.assertIn("/ui/heatmap", admin.text)

    def test_heatmap_page_requires_admin_session(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        client = self._build_client()
        response = client.get("/ui/heatmap", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/ui/login", response.headers.get("location", ""))

    def test_heatmap_page_renders_for_authenticated_admin(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        client = self._build_client()
        login = client.post(
            "/ui/login",
            data={"username": "admin", "password": "supersecurepass"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)
        response = client.get("/ui/heatmap")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Timeline Heatmap", response.text)
        self.assertIn("id=\"heatmap-hours\"", response.text)

    def test_event_detail_page_includes_snapshot_image_url(self) -> None:
        if TestClient is None:
            self.skipTest("fastapi not installed")
        client = self._build_client()
        login = client.post(
            "/ui/login",
            data={"username": "admin", "password": "supersecurepass"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)
        detail = client.get("/ui/events/evt-1")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("/api/events/evt-1/snapshot.jpg", detail.text)


if __name__ == "__main__":
    unittest.main()
