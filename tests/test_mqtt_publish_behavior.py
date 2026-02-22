"""Tests for MQTT publish behavior on non-processed events."""

from __future__ import annotations

import unittest

from src.models import FrigateEvent

try:
    from src.mqtt.mqtt_client import MQTTClient
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    MQTTClient = None  # type: ignore[assignment]


class MQTTPublishBehaviorTests(unittest.TestCase):
    def test_publish_camera_unknown_uses_waiting_defaults(self) -> None:
        if MQTTClient is None:
            self.skipTest("paho-mqtt not installed")
        published: list[tuple[str, str]] = []
        client = MQTTClient.__new__(MQTTClient)
        client._resolve_camera_topics = lambda _camera: {  # type: ignore[method-assign]
            "last_event_id": "cam/last_event_id",
            "last_event_ts": "cam/last_event_ts",
            "result_status": "cam/result_status",
            "action": "cam/action",
            "subject_type": "cam/subject_type",
            "confidence": "cam/confidence",
            "description": "cam/description",
            "monthly_cost": "cam/monthly_cost",
        }
        client._publish_sync = lambda topic, payload, retain=None: published.append(  # type: ignore[method-assign]
            (topic, str(payload))
        )

        client._publish_camera_unknown("doorbell")

        self.assertIn(("cam/result_status", "waiting"), published)
        self.assertIn(("cam/action", "waiting"), published)
        self.assertIn(("cam/description", "waiting for event"), published)

    def test_publish_camera_status_only_does_not_publish_action_or_description(self) -> None:
        if MQTTClient is None:
            self.skipTest("paho-mqtt not installed")
        published: list[tuple[str, str]] = []
        client = MQTTClient.__new__(MQTTClient)
        client._resolve_camera_topics = lambda _camera: {  # type: ignore[method-assign]
            "last_event_id": "cam/last_event_id",
            "last_event_ts": "cam/last_event_ts",
            "result_status": "cam/result_status",
            "action": "cam/action",
            "description": "cam/description",
        }
        client._publish_sync = lambda topic, payload, retain=None: published.append(  # type: ignore[method-assign]
            (topic, str(payload))
        )
        client._to_iso_timestamp = lambda _ts: "2026-02-22T12:00:00+00:00"  # type: ignore[method-assign]

        event = FrigateEvent(
            event_id="evt-1",
            camera="doorbell",
            label="person",
            event_type="update",
            event_ts=1700000000.0,
        )
        client._publish_camera_status_only(event=event, result_status="suppressed")

        published_topics = [topic for topic, _payload in published]
        self.assertEqual(
            published_topics,
            ["cam/last_event_id", "cam/last_event_ts", "cam/result_status"],
        )

    def test_unknown_camera_stays_disabled_when_not_in_db(self) -> None:
        if MQTTClient is None:
            self.skipTest("paho-mqtt not installed")

        class _CameraStoreStub:
            def get_camera_enabled(self, _camera: str):
                return None

        client = MQTTClient.__new__(MQTTClient)
        client._camera_store = _CameraStoreStub()
        self.assertFalse(client._is_camera_enabled_runtime("garage"))


if __name__ == "__main__":
    unittest.main()
