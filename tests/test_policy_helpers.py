"""Unit tests for action/subject_type policy helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.openai.policy_helpers import (
    apply_outdoor_action_heuristic,
    enforce_classification_result,
    render_prompts,
    resolve_allowed_actions,
    resolve_preset,
    resolve_subject_types,
)
from src.models import FrigateEvent


def _build_test_config() -> SimpleNamespace:
    cameras = {
        "front": SimpleNamespace(
            allowed_actions=[
                "unknown",
                "person_passing_by",
                "person_approaching",
                "person_at_door",
                "person_leaving",
                "deliver_package",
            ],
            prompt_preset="outdoor",
        ),
        "inside": SimpleNamespace(
            allowed_actions=[],
            prompt_preset="indoor",
        ),
    }
    policy = SimpleNamespace(
        cameras=cameras,
        actions=SimpleNamespace(
            default_action="unknown",
            allowed=[
                "unknown",
                "room_occupied",
                "person_passing_by",
                "person_approaching",
                "person_at_door",
                "person_leaving",
                "deliver_package",
                "animal_detected",
            ],
        ),
        subject_types=SimpleNamespace(
            default="unknown",
            allowed=["none", "adult", "child", "pet", "animal", "vehicle", "unknown"],
        ),
    )
    ai = SimpleNamespace(
        default_prompt_preset="outdoor",
        prompt_presets={
            "outdoor": {
                "system": "sys {camera_name}",
                "user": "actions={allowed_actions} subjects={allowed_subject_types}",
            },
            "indoor": {
                "system": "indoor {camera_name}",
                "user": "u {allowed_actions}",
            },
        },
        system_prompt="fallback",
    )
    return SimpleNamespace(policy=policy, ai=ai)


class PolicyHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _build_test_config()

    def test_resolve_allowed_actions_camera_override(self) -> None:
        allowed = resolve_allowed_actions("front", self.config)
        self.assertEqual(
            allowed,
            [
                "unknown",
                "person_passing_by",
                "person_approaching",
                "person_at_door",
                "person_leaving",
                "deliver_package",
            ],
        )

    def test_resolve_allowed_actions_fallback_global(self) -> None:
        allowed = resolve_allowed_actions("inside", self.config)
        self.assertEqual(
            allowed,
            [
                "unknown",
                "room_occupied",
                "person_passing_by",
                "person_approaching",
                "person_at_door",
                "person_leaving",
                "deliver_package",
                "animal_detected",
            ],
        )

    def test_room_occupied_rejected_when_not_in_camera_override(self) -> None:
        action, _subject_type, _description, status = enforce_classification_result(
            action="room_occupied",
            subject_type="adult",
            description="person present",
            camera="front",
            config=self.config,
        )
        self.assertEqual(action, "unknown")
        self.assertEqual(status, "invalid_action")

    def test_invalid_action_forced_to_unknown(self) -> None:
        action, subject_type, description, status = enforce_classification_result(
            action="legacy_action",
            subject_type="adult",
            description="ok",
            camera="front",
            config=self.config,
        )
        self.assertEqual(action, "unknown")
        self.assertEqual(subject_type, "adult")
        self.assertEqual(status, "invalid_action")
        self.assertEqual(description, "ok")

    def test_invalid_subject_type_forced_to_unknown(self) -> None:
        action, subject_type, _description, status = enforce_classification_result(
            action="deliver_package",
            subject_type="person",
            description="ok",
            camera="front",
            config=self.config,
        )
        self.assertEqual(action, "deliver_package")
        self.assertEqual(subject_type, "unknown")
        self.assertEqual(status, "invalid_subject_type")

    def test_description_truncation(self) -> None:
        long_desc = "x" * 250
        _action, _subject_type, description, _status = enforce_classification_result(
            action="deliver_package",
            subject_type="adult",
            description=long_desc,
            camera="front",
            config=self.config,
        )
        self.assertEqual(len(description), 200)

    def test_render_prompts(self) -> None:
        preset = resolve_preset("front", self.config)
        allowed_actions = resolve_allowed_actions("front", self.config)
        allowed_subject_types = resolve_subject_types(self.config)
        system, user = render_prompts(
            preset,
            camera_name="Front Door",
            allowed_actions=allowed_actions,
            allowed_subject_types=allowed_subject_types,
            config=self.config,
        )
        self.assertIn("Front Door", system)
        self.assertIn("deliver_package", user)
        self.assertIn("adult", user)

    def test_subject_type_values_pass_through_when_allowed(self) -> None:
        for subject in ["vehicle", "animal", "pet", "unknown", "none"]:
            _action, subject_type, _description, status = enforce_classification_result(
                action="deliver_package",
                subject_type=subject,
                description="scene",
                camera="front",
                config=self.config,
            )
            self.assertEqual(subject_type, subject)
            self.assertEqual(status, "ok")

    def test_new_movement_action_allowed_when_configured(self) -> None:
        action, _subject_type, _description, status = enforce_classification_result(
            action="person_passing_by",
            subject_type="adult",
            description="person passing entrance",
            camera="front",
            config=self.config,
        )
        self.assertEqual(action, "person_passing_by")
        self.assertEqual(status, "ok")

    def test_heuristic_promotes_unknown_to_person_at_door_for_door_zone(self) -> None:
        event = FrigateEvent(
            event_id="evt-1",
            camera="front",
            label="person",
            event_type="update",
            zones=("front_door",),
        )
        action = apply_outdoor_action_heuristic(
            event=event,
            action="unknown",
            config=self.config,
        )
        self.assertEqual(action, "person_at_door")

    def test_heuristic_noop_without_door_zone(self) -> None:
        event = FrigateEvent(
            event_id="evt-2",
            camera="front",
            label="person",
            event_type="update",
            zones=("driveway",),
        )
        action = apply_outdoor_action_heuristic(
            event=event,
            action="unknown",
            config=self.config,
        )
        self.assertEqual(action, "unknown")


if __name__ == "__main__":
    unittest.main()
