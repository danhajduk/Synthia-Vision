"""Tests for smart-update pHash gating behavior."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.models import FrigateEvent

try:
    from src.mqtt.mqtt_client import MQTTClient
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    MQTTClient = None  # type: ignore[assignment]


class SmartUpdateFlowTests(unittest.TestCase):
    def _event(self, event_type: str, event_id: str = "evt-1") -> FrigateEvent:
        return FrigateEvent(
            event_id=event_id,
            camera="doorbell",
            label="person",
            event_type=event_type,
            event_ts=1700000000.0,
        )

    def test_update_event_skips_openai_when_phash_unchanged(self) -> None:
        if MQTTClient is None:
            self.skipTest("paho-mqtt not installed")
        client = MQTTClient.__new__(MQTTClient)
        journal_events: list[dict[str, object]] = []
        journal_metrics: list[dict[str, object]] = []
        published_status: list[tuple[str, str]] = []
        set_last_phash_calls: list[str] = []

        class _CameraStoreStub:
            def get_last_phash(self, _camera: str) -> str | None:
                return "abc123"

            def set_last_phash(self, _camera: str, phash_hex: str) -> None:
                set_last_phash_calls.append(phash_hex)

        class _SnapshotStub:
            def fetch_event_snapshot(self, _event_id: str, *, camera: str) -> bytes:
                _ = camera
                return b"jpeg-bytes"

        class _OpenAIStub:
            def classify(self, **_kwargs):
                raise AssertionError("OpenAI classify should not be called for unchanged update")

        client._camera_store = _CameraStoreStub()
        client._snapshot_manager = _SnapshotStub()
        client._openai_client = _OpenAIStub()
        client._camera_phash_threshold_by_camera = {"doorbell": 6}
        client._journal_event = lambda **kwargs: journal_events.append(kwargs)  # type: ignore[method-assign]
        client._journal_metric = lambda **kwargs: journal_metrics.append(kwargs)  # type: ignore[method-assign]
        client._publish_camera_status_only = (  # type: ignore[method-assign]
            lambda *, event, result_status: published_status.append((event.event_id, result_status))
        )
        client._journal_error = lambda **_kwargs: None  # type: ignore[method-assign]
        client._publish_last_error = lambda _msg: None  # type: ignore[method-assign]
        client._publish_sync = lambda _topic, _payload, retain=None: None  # type: ignore[method-assign]
        client._status_topic = "home/synthiavision/status"
        client._is_budget_blocked = lambda: False  # type: ignore[method-assign]

        with (
            patch("src.mqtt.mqtt_client.compute_dhash_hex", return_value="abc123"),
            patch("src.mqtt.mqtt_client.hamming_distance_hex", return_value=0),
        ):
            client._fetch_snapshot_for_event(self._event("update"))

        self.assertEqual(published_status, [("evt-1", "unchanged")])
        self.assertEqual(set_last_phash_calls, ["abc123"])
        self.assertEqual(journal_events[-1]["result_status"], "unchanged")
        self.assertEqual(journal_metrics[-1]["skipped_openai_reason"], "phash_unchanged")

    def test_end_event_runs_openai_path(self) -> None:
        if MQTTClient is None:
            self.skipTest("paho-mqtt not installed")
        client = MQTTClient.__new__(MQTTClient)
        journal_metrics: list[dict[str, object]] = []
        published_results: list[dict[str, object]] = []
        classify_calls: list[dict[str, object]] = []

        class _CameraStoreStub:
            def set_last_phash(self, _camera: str, _phash_hex: str) -> None:
                raise AssertionError("end event should not set pHash when no update hash is computed")

        class _SnapshotStub:
            def fetch_event_snapshot(self, _event_id: str, *, camera: str) -> bytes:
                _ = camera
                return b"jpeg-bytes"

        class _OpenAIStub:
            def classify(self, **kwargs):
                classify_calls.append(kwargs)
                return (
                    SimpleNamespace(
                        action="person_detected",
                        subject_type="human",
                        confidence=0.91,
                        description="person at door",
                    ),
                    SimpleNamespace(
                        total_tokens=1500,
                        vision_detail="low",
                        processed_size=(640, 360),
                        image_bytes=12345,
                        prompt_tokens=1000,
                        completion_tokens=500,
                        cost_usd=0.0012,
                        model="gpt-4.1-mini",
                    ),
                )

        client._camera_store = _CameraStoreStub()
        client._snapshot_manager = _SnapshotStub()
        client._openai_client = _OpenAIStub()
        client._camera_phash_threshold_by_camera = {"doorbell": 6}
        client._journal_event = lambda **_kwargs: None  # type: ignore[method-assign]
        client._journal_metric = lambda **kwargs: journal_metrics.append(kwargs)  # type: ignore[method-assign]
        client._publish_camera_result = lambda **kwargs: published_results.append(kwargs)  # type: ignore[method-assign]
        client._journal_error = lambda **_kwargs: None  # type: ignore[method-assign]
        client._publish_last_error = lambda _msg: None  # type: ignore[method-assign]
        client._publish_sync = lambda _topic, _payload, retain=None: None  # type: ignore[method-assign]
        client._status_topic = "home/synthiavision/status"
        client._is_budget_blocked = lambda: False  # type: ignore[method-assign]
        client._record_openai_usage_metrics = lambda *, usage, camera: None  # type: ignore[method-assign]
        client._config = SimpleNamespace()

        with patch("src.mqtt.mqtt_client.apply_outdoor_action_heuristic", side_effect=lambda **kwargs: kwargs["action"]):
            client._fetch_snapshot_for_event(self._event("end", event_id="evt-end"))

        self.assertEqual(len(classify_calls), 1)
        self.assertEqual(published_results[-1]["result_status"], "ok")
        self.assertEqual(published_results[-1]["event"].event_id, "evt-end")
        self.assertIsNone(journal_metrics[-1].get("phash"))
        self.assertIsNone(journal_metrics[-1].get("phash_distance"))


if __name__ == "__main__":
    unittest.main()
