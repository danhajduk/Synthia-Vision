"""Helpers for prompt presets and classification allowlist enforcement."""

from __future__ import annotations

import re
from typing import Any

from src.config import ServiceConfig
from src.db import db_get_camera_profile, db_list_camera_views
from src.models import FrigateEvent

_PLACEHOLDER_PATTERN = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


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
    environment = str((context_fields or {}).get("environment", "") or "").strip()
    purpose = str((context_fields or {}).get("purpose", "") or "").strip()
    view_context_summary = str((context_fields or {}).get("view_context_summary", "") or "").strip()
    focus_notes = str((context_fields or {}).get("focus_notes", "") or "").strip()
    expected_activity = str((context_fields or {}).get("expected_activity", "") or "").strip()
    delivery_focus = str((context_fields or {}).get("delivery_focus", "") or "").strip()
    format_args = {
        "camera_name": camera_name,
        "environment": environment,
        "purpose": purpose,
        "view_context_summary": view_context_summary,
        "focus_notes": focus_notes,
        "expected_activity": expected_activity,
        "delivery_focus": delivery_focus,
        "allowed_actions": ", ".join(allowed_actions),
        "allowed_subject_types": ", ".join(allowed_subject_types),
        "privacy_rules": str(config.ai.privacy_rules or ""),
    }
    camera_cfg = config.policy.cameras.get(camera_name)
    security_overlay = ""
    if (
        camera_cfg is not None
        and camera_cfg.security_capable
        and camera_cfg.security_mode
        and purpose != "child_room"
    ):
        security_overlay = str(config.ai.security_overlay_template or "")
    format_args["security_overlay"] = security_overlay

    system_prompt = system_template.format(**format_args)
    user_prompt = user_template.format(**format_args)
    _assert_no_placeholders(system_prompt, prompt_name="system")
    _assert_no_placeholders(user_prompt, prompt_name="user")
    return system_prompt, user_prompt


def build_camera_context_fields(camera: str, config: ServiceConfig) -> dict[str, str]:
    try:
        profile = db_get_camera_profile(config.paths.db_file, camera) or {}
        views = db_list_camera_views(config.paths.db_file, camera)
    except Exception:
        return {
            "environment": "",
            "purpose": "general",
            "view_type": "",
            "view_context_summary": "",
            "focus_notes": "",
            "expected_activity": "",
            "delivery_focus": "",
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
    raw_delivery_focus = profile.get("delivery_focus", [])
    delivery_focus: list[str] = []
    if isinstance(raw_delivery_focus, list):
        delivery_focus = [str(item).strip() for item in raw_delivery_focus if str(item).strip()]
    return {
        "environment": str(profile.get("environment", "") or ""),
        "purpose": str(profile.get("purpose", "general") or "general"),
        "view_type": str(profile.get("view_type", "") or ""),
        "view_context_summary": str((selected_view or {}).get("context_summary", "") or ""),
        "focus_notes": str((selected_view or {}).get("focus_notes", "") or ""),
        "expected_activity": ", ".join(expected_activity),
        "delivery_focus": ", ".join(delivery_focus),
    }


def _assert_no_placeholders(text: str, *, prompt_name: str) -> None:
    if _PLACEHOLDER_PATTERN.search(text):
        raise ValueError(f"unresolved template placeholders in {prompt_name} prompt")


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
    frame_size: tuple[int, int] | None = None,
) -> str:
    if _should_force_person_at_door(
        event=event,
        action=action,
        config=config,
        frame_size=frame_size,
    ):
        return "person_at_door"
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


def _should_force_person_at_door(
    *,
    event: FrigateEvent,
    action: str,
    config: ServiceConfig,
    frame_size: tuple[int, int] | None,
) -> bool:
    override_cfg = getattr(getattr(config, "ai", None), "proximity_override", None)
    if not getattr(override_cfg, "enabled", False):
        return False
    if action == "person_leaving":
        return False
    if event.label != "person" or event.bbox is None or frame_size is None:
        return False
    allowed_actions = set(resolve_allowed_actions(event.camera, config))
    if "person_at_door" not in allowed_actions:
        return False

    frame_w, frame_h = int(frame_size[0]), int(frame_size[1])
    if frame_w <= 0 or frame_h <= 0:
        return False
    x, _y, w, h = event.bbox
    if w <= 0 or h <= 0:
        return False

    area_ratio_threshold = float(getattr(override_cfg, "area_ratio_threshold", 0.25))
    right_edge_touch_ratio = float(getattr(override_cfg, "right_edge_touch_ratio", 0.98))
    area_ratio = (w * h) / float(frame_w * frame_h)
    if area_ratio >= area_ratio_threshold:
        return True

    right_edge_x = x + w
    touches_right_edge = right_edge_x >= int(frame_w * right_edge_touch_ratio)
    mostly_on_right_side = x >= int(frame_w * 0.5)
    return touches_right_edge and mostly_on_right_side
