"""Integration-style tests with mocks for MQTT/httpx/OpenAI flows."""

from __future__ import annotations

import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.config import load_settings
from src.openai.client import OpenAIClient

try:
    from src.mqtt.mqtt_client import MQTTClient
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    MQTTClient = None  # type: ignore[assignment]

try:
    from src.snapshot_manager import SnapshotManager
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    SnapshotManager = None  # type: ignore[assignment]

try:
    import yaml  # noqa: F401
    HAS_YAML = True
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    HAS_YAML = False


class IntegrationMocksTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "test-key")

    def test_snapshot_manager_with_mock_httpx(self) -> None:
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        if SnapshotManager is None:
            self.skipTest("httpx not installed")
        cfg = load_settings("config/config.yaml")
        manager = SnapshotManager(cfg)
        mock_response = SimpleNamespace(status_code=200, content=b"\xff\xd8\xff\xd9")
        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_ctx = Mock()
        mock_ctx.__enter__ = Mock(return_value=mock_client)
        mock_ctx.__exit__ = Mock(return_value=False)
        with patch("src.snapshot_manager.httpx.Client", return_value=mock_ctx):
            data = manager.fetch_event_snapshot("event-1", camera="livingroom")
        self.assertEqual(data, b"\xff\xd8\xff\xd9")

    def test_openai_client_payload_uses_input_image(self) -> None:
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        client = OpenAIClient.__new__(OpenAIClient)
        cfg = load_settings("config/config.yaml")
        client._config = cfg
        client._openai_cfg = cfg.openai
        captured: dict[str, object] = {}

        def _create(**kwargs):
            captured.update(kwargs)
            response = SimpleNamespace(
                output_text=json.dumps(
                    {
                        "action": "room_occupied",
                        "subject_type": "unknown",
                        "confidence": 0.8,
                        "description": "people visible",
                    }
                ),
                output=[],
                usage=SimpleNamespace(input_tokens=120, output_tokens=20, total_tokens=140),
            )
            return response

        client._client = SimpleNamespace(responses=SimpleNamespace(create=_create))
        try:
            from PIL import Image
        except ModuleNotFoundError:
            self.skipTest("Pillow not available")
        image = Image.new("RGB", (64, 64), color=(100, 100, 100))
        b = io.BytesIO()
        image.save(b, format="JPEG")
        client.classify(snapshot_bytes=b.getvalue(), camera_name="livingroom")
        self.assertIn("input", captured)
        content = captured["input"][1]["content"]  # type: ignore[index]
        self.assertEqual(content[1]["type"], "input_image")

    def test_mqtt_core_control_command_with_mock_publish(self) -> None:
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        if MQTTClient is None:
            self.skipTest("paho-mqtt not installed")
        cfg = load_settings("config/config.yaml")
        mqtt_client = MQTTClient(cfg)
        mqtt_client._publish_sync = Mock()  # type: ignore[method-assign]
        topic = f"{cfg.service.mqtt_prefix}/control/monthly_budget/set"
        handled = mqtt_client._handle_core_control_message(topic, b"15.5")
        self.assertTrue(handled)
        self.assertEqual(mqtt_client._monthly_budget_limit, 15.5)


if __name__ == "__main__":
    unittest.main()
