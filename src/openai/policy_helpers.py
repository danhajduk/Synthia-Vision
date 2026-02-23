"""Helpers for prompt presets and classification allowlist enforcement."""

from __future__ import annotations

from typing import Any

from src.config import ServiceConfig
from src.db import db_get_camera_profile, db_list_camera_views
from src.models import FrigateEvent


def resolve_allowed_actions(camera: str, config: ServiceConfig) -> list[str]:
    camera_cfg = config.policy.cameras.get(camera)
    if camera_cfg is not None and camera_cfg.allowed_actions:
        return list(camera_cfg.allowed_actions)
    return list(config.policy.actions.allowed)


def resolve_subject_types(config: ServiceConfig) -> list[str]:
    return list(config.policy.subject_types.allowed)


def resolve_preset(
    camera: str,
    config: ServiceConfig,
    *,
    context_fields: dict[str, str] | None = None,
) -> str:
    templates: dict[str, dict[str, str]] = config.ai.prompt_presets
    purpose = ""
    if context_fields:
        purpose = str(context_fields.get("purpose", "") or "").strip()
    if not purpose:
        try:
            profile = db_get_camera_profile(config.paths.db_file, camera) or {}
            purpose = str(profile.get("purpose", "") or "").strip()
        except Exception:
            purpose = ""
    if purpose and purpose in templates:
        return purpose
    if "general" in templates:
        return "general"
    camera_cfg = config.policy.cameras.get(camera)
    if camera_cfg is not None and camera_cfg.prompt_preset:
        preset = str(camera_cfg.prompt_preset)
        if preset in templates:
            return preset
    return config.ai.default_prompt_preset


def render_prompts(
    preset: str,
    camera_name: str,
    allowed_actions: list[str],
    allowed_subject_types: list[str],
    config: ServiceConfig,
    context_fields: dict[str, str] | None = None,
) -> tuple[str, str]:
    templates: dict[str, dict[str, str]] = config.ai.prompt_presets
    selected = templates.get(preset) or templates.get(config.ai.default_prompt_preset) or {}
    system_template = str(selected.get("system", config.ai.system_prompt))
    user_template = str(selected.get("user", ""))
    environment = ""
    purpose = ""
    if context_fields:
        environment = str(context_fields.get("environment", "") or "").strip()
        purpose = str(context_fields.get("purpose", "") or "").strip()
    if "{environment}" not in user_template:
        user_template = (
            f"{user_template.rstrip()}\n"
            "Environment: {environment}\n"
        )
    if "{purpose}" not in user_template:
        user_template = (
            f"{user_template.rstrip()}\n"
            "Purpose: {purpose}\n"
        )

    format_args = {
        "camera_name": camera_name,
        "allowed_actions": ", ".join(allowed_actions),
        "allowed_subject_types": ", ".join(allowed_subject_types),
    }
    if context_fields:
        format_args.update(context_fields)
    system_prompt = system_template.format(**format_args)
    user_prompt = user_template.format(**format_args)
    # Always inject setup context so classification sees configured camera intent.
    user_prompt = (
        f"{user_prompt.rstrip()}\n"
        "View context summary: {context_summary}\n"
        "View focus notes: {focus_notes}\n"
        "Typical activities: {typical_activities}\n"
    ).format(**format_args)
    # Global privacy + output constraints for every classification request.
    user_prompt = (
        f"{user_prompt.rstrip()}\n"
        "Privacy requirements: no identifying details (no faces, clothing/colors, brands, readable text, plates).\n"
        "Return ONLY valid JSON for synthia_vision_event: action, subject_type, confidence, description.\n"
        "Description: one short generic sentence, max 200 chars.\n"
    )
    camera_cfg = config.policy.cameras.get(camera_name)
    if (
        camera_cfg is not None
        and camera_cfg.security_capable
        and camera_cfg.security_mode
        and purpose != "child_room"
    ):
        overlay_lines = [
            "Security overlay mode: conservative safety-focused interpretation only.",
            "Do not infer intent without clear visual evidence.",
            "Use suspicious_activity ONLY when clear tampering or forced-entry posture is visible.",
            "Use loitering ONLY when clear lingering near a relevant area is visible.",
        ]
        if purpose in {"doorbell", "garage"}:
            overlay_lines.append(
                "Prioritize entry/threshold-related actions for this camera when clearly supported."
            )
        if purpose == "driveway":
            overlay_lines.append(
                "Prioritize vehicle_arrival/vehicle_departure when vehicle motion context is clear."
            )
        user_prompt = f"{user_prompt.rstrip()}\n" + "\n".join(overlay_lines) + "\n"
    return system_prompt, user_prompt


def build_camera_context_fields(camera: str, config: ServiceConfig) -> dict[str, str]:
    try:
        profile = db_get_camera_profile(config.paths.db_file, camera) or {}
        views = db_list_camera_views(config.paths.db_file, camera)
    except Exception:
        return {
            "environment": "",
            "purpose": "",
            "view_type": "",
            "context_summary": "",
            "focus_notes": "",
            "typical_activities": "",
        }

    default_view_id = str(profile.get("default_view_id") or "").strip()
    selected_view: dict[str, Any] | None = None
    if default_view_id:
        selected_view = next(
            (item for item in views if str(item.get("view_id", "")) == default_view_id),
            None,
        )
    if selected_view is None and views:
        selected_view = views[0]

    expected_activity = []
    if selected_view is not None:
        raw = selected_view.get("expected_activity", [])
        if isinstance(raw, list):
            expected_activity = [str(item).strip() for item in raw if str(item).strip()]
    return {
        "environment": str(profile.get("environment", "") or ""),
        "purpose": str(profile.get("purpose", "") or ""),
        "view_type": str(profile.get("view_type", "") or ""),
        "context_summary": str((selected_view or {}).get("context_summary", "") or ""),
        "focus_notes": str((selected_view or {}).get("focus_notes", "") or ""),
        "typical_activities": ", ".join(expected_activity),
    }


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
