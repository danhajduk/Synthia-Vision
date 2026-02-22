"""Unit tests for image preprocessing pipeline."""

from __future__ import annotations

import io
import unittest
from types import SimpleNamespace

from src.ai.image_preprocess import preprocess_image_bytes


def _build_config() -> SimpleNamespace:
    return SimpleNamespace(
        ai=SimpleNamespace(
            image_preprocess=SimpleNamespace(
                enabled=True,
                max_side_px=512,
                jpeg_quality=75,
                strip_metadata=True,
                crop_to_bbox=True,
                bbox_padding=0.2,
            ),
        ),
        policy=SimpleNamespace(
            cameras={
                "front": SimpleNamespace(
                    max_side_px=None,
                )
            }
        ),
    )


def _jpeg_bytes(width: int, height: int) -> bytes:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise unittest.SkipTest("Pillow is required for this test") from exc
    image = Image.new("RGB", (width, height), color=(120, 100, 80))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


class ImagePreprocessTests(unittest.TestCase):
    def test_resize_to_max_side_and_jpeg(self) -> None:
        cfg = _build_config()
        original = _jpeg_bytes(1920, 1080)
        result = preprocess_image_bytes(original, config=cfg, camera_name="front")
        self.assertEqual(result.image_format, "JPEG")
        self.assertEqual(result.original_size, (1920, 1080))
        self.assertLessEqual(max(result.processed_size), 512)
        self.assertEqual(result.quality, 75)

    def test_crop_to_bbox_then_resize(self) -> None:
        cfg = _build_config()
        original = _jpeg_bytes(1920, 1080)
        result = preprocess_image_bytes(
            original,
            config=cfg,
            camera_name="front",
            bbox=(400, 200, 300, 300),
        )
        self.assertTrue(result.cropped_to_bbox)
        self.assertLessEqual(max(result.processed_size), 512)


if __name__ == "__main__":
    unittest.main()
