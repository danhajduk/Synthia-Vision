"""Unit tests for budget guard and metric rollover helpers."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

try:
    from src.mqtt.mqtt_client import MQTTClient
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    MQTTClient = None  # type: ignore[assignment]


@unittest.skipIf(MQTTClient is None, "paho-mqtt not installed")
class BudgetRolloverTests(unittest.TestCase):
    def _build_client(self) -> MQTTClient:
        client = MQTTClient.__new__(MQTTClient)
        client._config = SimpleNamespace(
            budget=SimpleNamespace(enabled=True),
        )
        client._monthly_budget_limit = 10.0
        client._runtime_metrics = {}
        return client

    def test_is_budget_blocked_true_when_month_limit_reached(self) -> None:
        client = self._build_client()
        client._runtime_metrics = {"cost_month2day_total": 10.0}
        self.assertTrue(client._is_budget_blocked())

    def test_is_budget_blocked_false_when_disabled(self) -> None:
        client = self._build_client()
        client._config.budget.enabled = False
        client._runtime_metrics = {"cost_month2day_total": 50.0}
        self.assertFalse(client._is_budget_blocked())

    def test_apply_metric_rollovers_resets_day_and_month(self) -> None:
        client = self._build_client()
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        last_month = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        metrics = {
            "count_today": 5,
            "count_today_date": yesterday,
            "cost_daily_total": 3.5,
            "count_month_key": last_month,
            "cost_month2day_total": 12.0,
            "cost_monthly_by_camera": {"front": 7.0},
        }
        client._apply_metric_rollovers(metrics)
        self.assertEqual(metrics["count_today"], 0)
        self.assertEqual(metrics["cost_daily_total"], 0.0)
        self.assertEqual(metrics["cost_month2day_total"], 0.0)
        self.assertEqual(metrics["cost_monthly_by_camera"], {})


if __name__ == "__main__":
    unittest.main()
