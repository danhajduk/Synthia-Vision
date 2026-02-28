"""Tests for mode-based prompt profile loading and rendering."""

from __future__ import annotations

import os
import unittest

from src.config import load_settings
from src.config.settings import PolicyCameraConfig
from src.openai.policy_helpers import render_prompts, resolve_allowed_actions, resolve_prompt_selection, resolve_subject_types

try:
    import yaml  # noqa: F401

    HAS_YAML = True
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    HAS_YAML = False


class PromptProfilesTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "test-key")

    def test_profiles_load_and_render_across_modes(self) -> None:
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        config = load_settings("config/config.yaml")
        self.assertIn("default", config.ai.prompt_profiles)
        self.assertIn("delivery_watch", config.ai.prompt_profiles)
        self.assertIn("guest_expected", config.ai.prompt_profiles)
        self.assertIn("high_alert", config.ai.prompt_profiles)

        config.policy.cameras["doorbell"].security_capable = True
        config.policy.cameras["doorbell"].security_mode = True
        config.policy.cameras["child_room_cam"] = PolicyCameraConfig(
            security_capable=True,
            security_mode=True,
        )

        doorbell_context = {
            "purpose": "doorbell",
            "environment": "outdoor",
            "mounting_location": "front door",
            "view_context_summary": "shared hallway facing entry",
            "focus_notes": "watch for package drop-offs",
            "expected_activity": "delivery drivers, neighbors passing",
            "delivery_focus": "porch threshold, package handling",
        }
        selection_delivery = resolve_prompt_selection(
            "doorbell",
            config,
            context_fields=doorbell_context,
            mode="delivery_watch",
        )
        self.assertEqual(selection_delivery.profile_name, "delivery_watch")
        self.assertEqual(selection_delivery.preset, "doorbell")
        system_delivery, user_delivery = render_prompts(
            preset=selection_delivery.preset,
            camera_name="doorbell",
            allowed_actions=resolve_allowed_actions("doorbell", config),
            allowed_subject_types=resolve_subject_types(config),
            config=config,
            context_fields=doorbell_context,
            prompt_profile=selection_delivery.profile,
        )
        self.assertIn("Return ONLY valid JSON matching schema; no extra text.", system_delivery)
        self.assertIn("SECURITY MODE OVERLAY", user_delivery)

        child_context = {
            "purpose": "child_room",
            "environment": "indoor",
            "mounting_location": "nursery",
            "view_context_summary": "crib and sleep area",
            "focus_notes": "bed state only",
            "expected_activity": "sleeping child",
            "delivery_focus": "",
        }
        selection_high_alert = resolve_prompt_selection(
            "child_room_cam",
            config,
            context_fields=child_context,
            mode="high_alert",
        )
        self.assertEqual(selection_high_alert.profile_name, "high_alert")
        self.assertEqual(selection_high_alert.preset, "child_room")
        system_child, user_child = render_prompts(
            preset=selection_high_alert.preset,
            camera_name="child_room_cam",
            allowed_actions=resolve_allowed_actions("child_room_cam", config),
            allowed_subject_types=resolve_subject_types(config),
            config=config,
            context_fields=child_context,
            prompt_profile=selection_high_alert.profile,
        )
        self.assertIn("Return ONLY valid JSON matching schema; no extra text.", system_child)
        self.assertNotIn("SECURITY MODE OVERLAY", user_child)


if __name__ == "__main__":
    unittest.main()
