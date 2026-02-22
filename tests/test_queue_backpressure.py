"""Tests for queue backpressure behavior."""

from __future__ import annotations

from collections import deque
import threading
import unittest

from src.models import FrigateEvent

try:
    from src.mqtt.mqtt_client import MQTTClient
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    MQTTClient = None  # type: ignore[assignment]


class QueueBackpressureTests(unittest.TestCase):
    def _build_client(self) -> MQTTClient:
        client = MQTTClient.__new__(MQTTClient)
        client._event_queue = deque(maxlen=50)
        client._event_queue_lock = threading.Lock()
        client._dropped_events_total = 0
        client._dropped_update_total = 0
        client._dropped_queue_full_total = 0
        client._loop = None
        client._queue_event = None  # not needed when _loop is None
        client._is_degraded = False
        client._is_budget_blocked = lambda: False  # type: ignore[method-assign]
        return client

    def _event(self, idx: int, event_type: str) -> FrigateEvent:
        return FrigateEvent(
            event_id=f"evt-{idx}",
            camera="doorbell",
            label="person",
            event_type=event_type,
        )

    def test_drop_incoming_update_when_full(self) -> None:
        if MQTTClient is None:
            self.skipTest("paho-mqtt not installed")
        client = self._build_client()
        for i in range(50):
            client._event_queue.append(self._event(i, "end"))

        client._enqueue_event_from_callback(self._event(99, "update"))

        self.assertEqual(len(client._event_queue), 50)
        self.assertEqual(client._dropped_events_total, 1)
        self.assertEqual(client._dropped_update_total, 1)
        self.assertEqual(client._dropped_queue_full_total, 0)
        self.assertNotIn("evt-99", {e.event_id for e in client._event_queue})

    def test_drop_oldest_then_enqueue_non_update_when_full(self) -> None:
        if MQTTClient is None:
            self.skipTest("paho-mqtt not installed")
        client = self._build_client()
        for i in range(50):
            client._event_queue.append(self._event(i, "end"))

        client._enqueue_event_from_callback(self._event(100, "end"))

        self.assertEqual(len(client._event_queue), 50)
        ids = [e.event_id for e in client._event_queue]
        self.assertNotIn("evt-0", ids)
        self.assertIn("evt-100", ids)
        self.assertEqual(client._dropped_events_total, 1)
        self.assertEqual(client._dropped_update_total, 0)
        self.assertEqual(client._dropped_queue_full_total, 1)

    def test_effective_runtime_status_priority(self) -> None:
        if MQTTClient is None:
            self.skipTest("paho-mqtt not installed")
        client = self._build_client()
        client._is_degraded = True
        client._is_budget_blocked = lambda: True  # type: ignore[method-assign]
        self.assertEqual(client._effective_runtime_status(), "budget_blocked")
        client._is_budget_blocked = lambda: False  # type: ignore[method-assign]
        self.assertEqual(client._effective_runtime_status(), "degraded")
        client._is_degraded = False
        self.assertEqual(client._effective_runtime_status(), "enabled")


if __name__ == "__main__":
    unittest.main()
