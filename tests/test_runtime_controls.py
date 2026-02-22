"""Unit tests for runtime event-type controls."""

from __future__ import annotations

import unittest

from src.runtime_controls import EventControlSettings, apply_event_controls
from src.runtime_controls import camera_event_controls_from_state


class RuntimeControlsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.counts: dict[str, int] = {}
        self.last_seen: dict[str, float] = {}
        self.base_ts = 1_700_000_000.0

    def test_default_end_on_update_off(self) -> None:
        settings = EventControlSettings(
            process_end_events=True,
            process_update_events=False,
            updates_per_event=1,
        )
        update_result = apply_event_controls(
            event_id="e1",
            event_type="update",
            settings=settings,
            updates_processed_count=self.counts,
            last_seen_ts=self.last_seen,
            event_ts=self.base_ts,
        )
        end_result = apply_event_controls(
            event_id="e1",
            event_type="end",
            settings=settings,
            updates_processed_count=self.counts,
            last_seen_ts=self.last_seen,
            event_ts=self.base_ts + 1,
        )
        self.assertFalse(update_result.allow)
        self.assertTrue(end_result.allow)

    def test_update_on_n1_only_first_update(self) -> None:
        settings = EventControlSettings(
            process_end_events=False,
            process_update_events=True,
            updates_per_event=1,
        )
        first = apply_event_controls(
            event_id="e1",
            event_type="update",
            settings=settings,
            updates_processed_count=self.counts,
            last_seen_ts=self.last_seen,
            event_ts=self.base_ts,
        )
        second = apply_event_controls(
            event_id="e1",
            event_type="update",
            settings=settings,
            updates_processed_count=self.counts,
            last_seen_ts=self.last_seen,
            event_ts=self.base_ts + 1,
        )
        self.assertTrue(first.allow)
        self.assertFalse(second.allow)

    def test_update_on_n2_accepts_two_updates(self) -> None:
        settings = EventControlSettings(
            process_end_events=False,
            process_update_events=True,
            updates_per_event=2,
        )
        first = apply_event_controls(
            event_id="e2",
            event_type="update",
            settings=settings,
            updates_processed_count=self.counts,
            last_seen_ts=self.last_seen,
            event_ts=self.base_ts,
        )
        second = apply_event_controls(
            event_id="e2",
            event_type="update",
            settings=settings,
            updates_processed_count=self.counts,
            last_seen_ts=self.last_seen,
            event_ts=self.base_ts + 1,
        )
        third = apply_event_controls(
            event_id="e2",
            event_type="update",
            settings=settings,
            updates_processed_count=self.counts,
            last_seen_ts=self.last_seen,
            event_ts=self.base_ts + 2,
        )
        self.assertTrue(first.allow)
        self.assertTrue(second.allow)
        self.assertFalse(third.allow)

    def test_both_on_allows_updates_and_end(self) -> None:
        settings = EventControlSettings(
            process_end_events=True,
            process_update_events=True,
            updates_per_event=1,
        )
        update = apply_event_controls(
            event_id="e3",
            event_type="update",
            settings=settings,
            updates_processed_count=self.counts,
            last_seen_ts=self.last_seen,
            event_ts=self.base_ts,
        )
        end = apply_event_controls(
            event_id="e3",
            event_type="end",
            settings=settings,
            updates_processed_count=self.counts,
            last_seen_ts=self.last_seen,
            event_ts=self.base_ts + 1,
        )
        self.assertTrue(update.allow)
        self.assertTrue(end.allow)

    def test_both_off_rejects_all(self) -> None:
        settings = EventControlSettings(
            process_end_events=False,
            process_update_events=False,
            updates_per_event=1,
        )
        update = apply_event_controls(
            event_id="e4",
            event_type="update",
            settings=settings,
            updates_processed_count=self.counts,
            last_seen_ts=self.last_seen,
            event_ts=self.base_ts,
        )
        end = apply_event_controls(
            event_id="e4",
            event_type="end",
            settings=settings,
            updates_processed_count=self.counts,
            last_seen_ts=self.last_seen,
            event_ts=self.base_ts + 1,
        )
        self.assertFalse(update.allow)
        self.assertFalse(end.allow)

    def test_camera_controls_loaded_from_state(self) -> None:
        state = {
            "controls": {
                "camera_event_processing": {
                    "doorbell": {
                        "process_end_events": False,
                        "process_update_events": True,
                    }
                }
            }
        }
        process_end, process_update = camera_event_controls_from_state(state, "doorbell")
        self.assertFalse(process_end)
        self.assertTrue(process_update)


if __name__ == "__main__":
    unittest.main()
