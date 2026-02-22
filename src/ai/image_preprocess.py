"""Image preprocessing for token-efficient vision calls."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import ServiceConfig


@dataclass(slots=True)
class PreprocessResult:
    image_bytes: bytes
    original_size: tuple[int, int]
    processed_size: tuple[int, int]
    cropped_to_bbox: bool
    image_format: str
    quality: int


def preprocess_image_bytes(
    image_bytes: bytes,
    *,
    config: ServiceConfig,
    camera_name: str,
    bbox: tuple[int, int, int, int] | None = None,
    force_low_budget: bool = False,
) -> PreprocessResult:
    try:
        from PIL import Image, ImageOps
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Pillow is required for image preprocessing") from exc

    preprocess_cfg = config.ai.image_preprocess
    camera_cfg = config.policy.cameras.get(camera_name)
    enabled = bool(preprocess_cfg.enabled)
    target_max_side = int(camera_cfg.max_side_px or preprocess_cfg.max_side_px)
    quality = int(preprocess_cfg.jpeg_quality)
    keep_metadata = not bool(preprocess_cfg.strip_metadata)
    if force_low_budget:
        target_max_side = min(target_max_side, 512)

    with Image.open(BytesIO(image_bytes)) as img:
        source_exif = img.info.get("exif")
        img = ImageOps.exif_transpose(img)
        original_size = (int(img.width), int(img.height))
        processed = img.convert("RGB")
        used_crop = False

        # Cropping is intentionally disabled to preserve full-frame context.
        _ = bbox

        if enabled:
            processed.thumbnail((target_max_side, target_max_side), Image.Resampling.LANCZOS)

        output = BytesIO()
        processed.save(
            output,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=False,
            exif=source_exif if keep_metadata and source_exif else b"",
        )
        final_bytes = output.getvalue()

    return PreprocessResult(
        image_bytes=final_bytes,
        original_size=original_size,
        processed_size=(processed.width, processed.height),
        cropped_to_bbox=used_crop,
        image_format="JPEG",
        quality=quality,
    )
