"""Tests for centralized runtime queue/degraded constants."""

from __future__ import annotations

import unittest

from src.runtime.constants import (
    DEGRADE_HIGH_WATERMARK,
    DEGRADE_LOW_WATERMARK,
    DEGRADE_SUSTAIN_SECONDS,
    EVENT_QUEUE_MAX_SIZE,
)


class RuntimeConstantsTests(unittest.TestCase):
    def test_queue_and_degrade_constants(self) -> None:
        self.assertEqual(EVENT_QUEUE_MAX_SIZE, 50)
        self.assertEqual(DEGRADE_HIGH_WATERMARK, 40)
        self.assertEqual(DEGRADE_LOW_WATERMARK, 10)
        self.assertEqual(DEGRADE_SUSTAIN_SECONDS, 30)

    def test_constant_relationships_are_sane(self) -> None:
        self.assertGreater(EVENT_QUEUE_MAX_SIZE, DEGRADE_HIGH_WATERMARK)
        self.assertGreater(DEGRADE_HIGH_WATERMARK, DEGRADE_LOW_WATERMARK)
        self.assertGreater(DEGRADE_SUSTAIN_SECONDS, 0)


if __name__ == "__main__":
    unittest.main()
