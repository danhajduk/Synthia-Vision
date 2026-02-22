"""Unit tests for OpenAI client parsing, retry, and request formatting."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.errors import ExternalServiceError, ValidationError
from src.openai import client as openai_client_module
from src.openai.client import OpenAIClient


class _FakeUsage:
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = input_tokens + output_tokens


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "output_text"
        self.text = text


class _FakeOutputItem:
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]


class _FakeResponse:
    def __init__(
        self,
        content: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self.output_text = content
        self.output = [_FakeOutputItem(content)]
        self.usage = _FakeUsage(input_tokens=input_tokens, output_tokens=output_tokens)


def _build_config() -> SimpleNamespace:
    policy = SimpleNamespace(
        cameras={
            "front": SimpleNamespace(
                allowed_actions=["unknown", "deliver_package"],
                prompt_preset="outdoor",
                vision_detail=None,
                max_side_px=None,
            ),
            "inside": SimpleNamespace(
                allowed_actions=[],
                prompt_preset="indoor",
                vision_detail=None,
                max_side_px=None,
            ),
        },
        actions=SimpleNamespace(
            default_action="unknown",
            allowed=["unknown", "room_occupied", "deliver_package"],
        ),
        subject_types=SimpleNamespace(
            default="unknown",
            allowed=["none", "adult", "child", "pet", "animal", "vehicle", "unknown"],
        ),
    )
    ai = SimpleNamespace(
        schema_name="synthia_vision_event",
        schema={},
        system_prompt="fallback",
        default_prompt_preset="outdoor",
        prompt_presets={
            "outdoor": {
                "system": "sys {camera_name}",
                "user": "allowed_actions={allowed_actions} allowed_subject_types={allowed_subject_types}",
            },
            "indoor": {
                "system": "indoor {camera_name}",
                "user": "allowed_actions={allowed_actions} allowed_subject_types={allowed_subject_types}",
            },
        },
        vision_detail="low",
        image_preprocess=SimpleNamespace(
            enabled=True,
            max_side_px=512,
            jpeg_quality=75,
            strip_metadata=True,
            crop_to_bbox=True,
            bbox_padding=0.2,
        ),
    )
    openai_cfg = SimpleNamespace(
        model="gpt-4o-mini",
        max_output_tokens=200,
        retry_attempts=3,
        retry_backoff_seconds=[0.0, 0.0, 0.0],
    )
    return SimpleNamespace(policy=policy, ai=ai, openai=openai_cfg)


def _make_retry_exception() -> Exception:
    exc_type = openai_client_module.APITimeoutError
    exc = exc_type.__new__(exc_type)
    Exception.__init__(exc, "timeout")
    return exc


def _jpeg_bytes(width: int = 64, height: int = 64) -> bytes:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise unittest.SkipTest("Pillow is required for this test") from exc
    import io

    image = Image.new("RGB", (width, height), color=(120, 100, 80))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class OpenAIClientTests(unittest.TestCase):
    def _build_client(self, create_callable) -> OpenAIClient:
        client = OpenAIClient.__new__(OpenAIClient)
        config = _build_config()
        client._config = config
        client._openai_cfg = config.openai
        client._client = SimpleNamespace(
            responses=SimpleNamespace(
                create=create_callable,
            )
        )
        return client

    def test_classify_valid_json(self) -> None:
        def _create(**_kwargs):
            return _FakeResponse(
                '{"action":"deliver_package","subject_type":"adult","confidence":0.82,"description":"package near front door"}',
                input_tokens=120,
                output_tokens=30,
            )

        client = self._build_client(_create)
        classification, usage = client.classify(
            snapshot_bytes=_jpeg_bytes(),
            camera_name="front",
        )
        self.assertEqual(classification.action, "deliver_package")
        self.assertEqual(classification.subject_type, "adult")
        self.assertEqual(int(round(classification.confidence * 100)), 82)
        self.assertGreater(usage.total_tokens, 0)
        self.assertGreaterEqual(usage.cost_usd, 0.0)

    def test_classify_allows_room_occupied_for_indoor_camera(self) -> None:
        def _create(**_kwargs):
            return _FakeResponse(
                '{"action":"room_occupied","subject_type":"unknown","confidence":0.91,"description":"people visible in room"}',
                input_tokens=100,
                output_tokens=20,
            )

        client = self._build_client(_create)
        classification, _usage = client.classify(
            snapshot_bytes=_jpeg_bytes(),
            camera_name="inside",
        )
        self.assertEqual(classification.action, "room_occupied")

    def test_classify_invalid_json(self) -> None:
        def _create(**_kwargs):
            return _FakeResponse("not-json")

        client = self._build_client(_create)
        with self.assertRaises(ValidationError):
            client.classify(snapshot_bytes=_jpeg_bytes(), camera_name="front")

    def test_classify_missing_field(self) -> None:
        def _create(**_kwargs):
            return _FakeResponse(
                '{"action":"deliver_package","confidence":0.82,"description":"package near front door"}'
            )

        client = self._build_client(_create)
        with self.assertRaises(ValidationError):
            client.classify(snapshot_bytes=_jpeg_bytes(), camera_name="front")

    def test_retry_transient_error_then_success(self) -> None:
        calls = {"count": 0}

        def _create(**_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise _make_retry_exception()
            return _FakeResponse(
                '{"action":"deliver_package","subject_type":"adult","confidence":0.82,"description":"package near front door"}'
            )

        client = self._build_client(_create)
        client._openai_cfg.retry_attempts = 2
        client._openai_cfg.retry_backoff_seconds = [0.0]
        classification, _usage = client.classify(snapshot_bytes=_jpeg_bytes(), camera_name="front")
        self.assertEqual(classification.action, "deliver_package")
        self.assertEqual(calls["count"], 2)

    def test_retry_exhausted_raises_external_service_error(self) -> None:
        def _create(**_kwargs):
            raise _make_retry_exception()

        client = self._build_client(_create)
        client._openai_cfg.retry_attempts = 2
        client._openai_cfg.retry_backoff_seconds = [0.0]
        with self.assertRaises(ExternalServiceError):
            client.classify(snapshot_bytes=_jpeg_bytes(), camera_name="front")

    def test_request_uses_input_image_and_low_detail(self) -> None:
        captured: dict[str, object] = {}

        def _create(**kwargs):
            captured.update(kwargs)
            return _FakeResponse(
                '{"action":"deliver_package","subject_type":"adult","confidence":0.82,"description":"package near front door"}'
            )

        client = self._build_client(_create)
        client.classify(snapshot_bytes=_jpeg_bytes(1920, 1080), camera_name="front")
        self.assertIn("input", captured)
        input_payload = captured["input"]
        self.assertIsInstance(input_payload, list)
        user_block = input_payload[1]
        content = user_block["content"]
        self.assertNotIn("data:image", content[0]["text"])
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(content[1]["detail"], "low")


if __name__ == "__main__":
    unittest.main()
