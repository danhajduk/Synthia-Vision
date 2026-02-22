"""Tests for perceptual hash helpers."""

from __future__ import annotations

import io
import unittest

from src.pipeline import compute_dhash_hex, hamming_distance_hex


def _jpeg_bytes(color: tuple[int, int, int]) -> bytes:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise unittest.SkipTest("Pillow is required for this test") from exc
    image = Image.new("RGB", (128, 96), color=color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _pattern_bytes(invert: bool = False) -> bytes:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise unittest.SkipTest("Pillow is required for this test") from exc
    image = Image.new("RGB", (128, 96), color=(0, 0, 0))
    px = image.load()
    for y in range(image.height):
        for x in range(image.width):
            on = ((x // 8) + (y // 8)) % 2 == 0
            if invert:
                on = not on
            px[x, y] = (245, 245, 245) if on else (15, 15, 15)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class PHashTests(unittest.TestCase):
    def test_dhash_is_stable_for_same_image(self) -> None:
        payload = _jpeg_bytes((120, 110, 100))
        a = compute_dhash_hex(payload)
        b = compute_dhash_hex(payload)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 16)
        self.assertEqual(hamming_distance_hex(a, b), 0)

    def test_hamming_distance_increases_for_changed_image(self) -> None:
        a = compute_dhash_hex(_pattern_bytes(invert=False))
        b = compute_dhash_hex(_pattern_bytes(invert=True))
        self.assertGreater(hamming_distance_hex(a, b), 0)


if __name__ == "__main__":
    unittest.main()
