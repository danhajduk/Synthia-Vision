"""Perceptual hash helpers for smart-update gating."""

from __future__ import annotations

from io import BytesIO


def compute_dhash_hex(image_bytes: bytes) -> str:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Pillow is required for perceptual hash operations") from exc

    with Image.open(BytesIO(image_bytes)) as image:
        gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(gray.getdata())
    bits = 0
    for row in range(8):
        offset = row * 9
        for col in range(8):
            left = pixels[offset + col]
            right = pixels[offset + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def hamming_distance_hex(a_hex: str, b_hex: str) -> int:
    a = int(a_hex, 16)
    b = int(b_hex, 16)
    return (a ^ b).bit_count()
