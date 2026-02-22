"""Helpers for prompt presets and classification allowlist enforcement."""

from __future__ import annotations

from typing import Any

from src.config import ServiceConfig
from src.models import FrigateEvent


def resolve_allowed_actions(camera: str, config: ServiceConfig) -> list[str]:
    camera_cfg = config.policy.cameras.get(camera)
    if camera_cfg is not None and camera_cfg.allowed_actions:
        return list(camera_cfg.allowed_actions)
    return list(config.policy.actions.allowed)


def resolve_subject_types(config: ServiceConfig) -> list[str]:
    return list(config.policy.subject_types.allowed)


def resolve_preset(camera: str, config: ServiceConfig) -> str:
    camera_cfg = config.policy.cameras.get(camera)
    if camera_cfg is not None and camera_cfg.prompt_preset:
        return camera_cfg.prompt_preset
    return config.ai.default_prompt_preset


def render_prompts(
    preset: str,
    camera_name: str,
    allowed_actions: list[str],
    allowed_subject_types: list[str],
    config: ServiceConfig,
) -> tuple[str, str]:
    templates: dict[str, dict[str, str]] = config.ai.prompt_presets
    selected = templates.get(preset) or templates.get(config.ai.default_prompt_preset) or {}
    system_template = str(selected.get("system", config.ai.system_prompt))
    user_template = str(selected.get("user", ""))

    format_args = {
        "camera_name": camera_name,
        "allowed_actions": ", ".join(allowed_actions),
        "allowed_subject_types": ", ".join(allowed_subject_types),
    }
    return (
        system_template.format(**format_args),
        user_template.format(**format_args),
    )


def enforce_classification_result(
    *,
    action: str,
    subject_type: str,
    description: str,
    camera: str,
    config: ServiceConfig,
) -> tuple[str, str, str, str]:
    allowed_actions = set(resolve_allowed_actions(camera, config))
    allowed_subject_types = set(resolve_subject_types(config))

    enforced_action = action if action in allowed_actions else config.policy.actions.default_action
    enforced_subject_type = (
        subject_type
        if subject_type in allowed_subject_types
        else config.policy.subject_types.default
    )
    enforced_description = _truncate_description(description)

    result_status = "ok"
    if enforced_action != action:
        result_status = "invalid_action"
    elif enforced_subject_type != subject_type:
        result_status = "invalid_subject_type"
    return enforced_action, enforced_subject_type, enforced_description, result_status


def apply_outdoor_action_heuristic(
    *,
    event: FrigateEvent,
    action: str,
    config: ServiceConfig,
) -> str:
    if action != config.policy.actions.default_action:
        return action
    allowed_actions = set(resolve_allowed_actions(event.camera, config))
    if "person_at_door" not in allowed_actions:
        return action
    if event.label != "person":
        return action
    zone_tokens = _normalized_zone_tokens(event.zones)
    if not zone_tokens:
        return action
    if _looks_like_door_zone(zone_tokens):
        return "person_at_door"
    return action


def _truncate_description(value: str, max_len: int = 200) -> str:
    text = str(value).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip()


def _normalized_zone_tokens(zones: tuple[str, ...]) -> set[str]:
    tokens: set[str] = set()
    for zone in zones:
        for token in zone.lower().replace("-", " ").replace("_", " ").split():
            if token:
                tokens.add(token)
    return tokens


def _looks_like_door_zone(tokens: set[str]) -> bool:
    door_tokens = {"door", "entry", "entrance", "threshold", "porch", "stoop"}
    return any(token in door_tokens for token in tokens)
