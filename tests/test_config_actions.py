"""Tests for movement action defaults in config parsing."""

from __future__ import annotations

import os
import unittest

try:
    import yaml  # noqa: F401

    HAS_YAML = True
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    HAS_YAML = False

from src.config import load_settings


class ConfigMovementActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "test-key")

    def test_global_actions_include_outdoor_movement_values(self) -> None:
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        cfg = load_settings("config/config.yaml")
        for action in (
            "person_passing_by",
            "person_approaching",
            "person_at_door",
            "person_leaving",
        ):
            self.assertIn(action, cfg.policy.actions.allowed)

    def test_doorbell_camera_actions_include_outdoor_movement_values(self) -> None:
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        cfg = load_settings("config/config.yaml")
        doorbell = cfg.policy.cameras["doorbell"]
        for action in (
            "person_passing_by",
            "person_approaching",
            "person_at_door",
            "person_leaving",
        ):
            self.assertIn(action, doorbell.allowed_actions)


if __name__ == "__main__":
    unittest.main()
