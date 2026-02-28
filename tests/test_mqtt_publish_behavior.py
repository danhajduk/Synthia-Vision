"""Tests for MQTT publish behavior on non-processed events."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

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
            "suppressed_count": "cam/suppressed_count",
            "monthly_cost": "cam/monthly_cost",
        }
        client._publish_sync = lambda topic, payload, retain=None: published.append(  # type: ignore[method-assign]
            (topic, str(payload))
        )

        client._publish_camera_unknown("doorbell")

        self.assertIn(("cam/result_status", "waiting"), published)
        self.assertIn(("cam/action", "waiting"), published)
        self.assertIn(("cam/description", "waiting for event"), published)
        self.assertIn(("cam/suppressed_count", "0"), published)

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

    def test_apply_camera_policy_overrides_uses_store_settings(self) -> None:
        if MQTTClient is None:
            self.skipTest("paho-mqtt not installed")

        class _CameraStoreStub:
            def get_policy_settings(
                self,
                _camera: str,
                *,
                default_display_name: str,
                default_confidence_threshold: float,
                default_cooldown_s: int,
                default_vision_detail: str,
            ):
                _ = (
                    default_display_name,
                    default_confidence_threshold,
                    default_cooldown_s,
                    default_vision_detail,
                )
                return SimpleNamespace(
                    display_name="Front Door",
                    prompt_preset="outdoor",
                    confidence_threshold=0.92,
                    cooldown_s=45,
                    vision_detail="high",
                    phash_threshold=8,
                    security_capable=False,
                    security_mode=False,
                )

        client = MQTTClient.__new__(MQTTClient)
        client._camera_store = _CameraStoreStub()
        client._camera_phash_threshold_by_camera = {}
        client._config = SimpleNamespace(
            policy=SimpleNamespace(
                defaults=SimpleNamespace(labels=["person"], confidence_threshold=0.65),
                cameras={},
            ),
            dedupe=SimpleNamespace(per_camera_cooldown_default_seconds=30),
            ai=SimpleNamespace(vision_detail="low"),
        )

        client._apply_camera_policy_overrides("doorbell", enabled=False)

        camera_policy = client._config.policy.cameras["doorbell"]
        self.assertEqual(camera_policy.name, "Front Door")
        self.assertFalse(camera_policy.enabled)
        self.assertEqual(camera_policy.prompt_preset, "outdoor")
        self.assertEqual(camera_policy.confidence_threshold, 0.92)
        self.assertEqual(camera_policy.cooldown_seconds, 45)
        self.assertEqual(camera_policy.vision_detail, "high")
        self.assertEqual(client._camera_phash_threshold_by_camera["doorbell"], 8)


if __name__ == "__main__":
    unittest.main()
