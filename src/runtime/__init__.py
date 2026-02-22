"""Runtime-level constants and helpers for pipeline behavior."""

from src.runtime.constants import (
    DEGRADE_HIGH_WATERMARK,
    DEGRADE_LOW_WATERMARK,
    DEGRADE_SUSTAIN_SECONDS,
    EVENT_QUEUE_MAX_SIZE,
)

__all__ = [
    "EVENT_QUEUE_MAX_SIZE",
    "DEGRADE_HIGH_WATERMARK",
    "DEGRADE_LOW_WATERMARK",
    "DEGRADE_SUSTAIN_SECONDS",
]
