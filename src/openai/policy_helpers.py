"""Helpers for prompt presets and classification allowlist enforcement."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.config import ServiceConfig
from src.db import db_get_camera_profile, db_list_camera_views
from src.db.kv_store import kv_get
from src.models import FrigateEvent

_PLACEHOLDER_PATTERN = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


@dataclass(slots=True)
class PromptSelection:
    mode: str
    preset: str
    profile_name: str | None
    profile: Any | None


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


def resolve_runtime_mode(config: ServiceConfig) -> str:
    try:
        runtime_mode = kv_get(config.paths.db_file, "runtime.current_mode")
        mode = str(runtime_mode or "").strip().lower()
        if mode:
            return mode
        fallback_mode = kv_get(config.paths.db_file, "modes.current")
        fallback = str(fallback_mode or "").strip().lower()
        if fallback:
            return fallback
    except Exception:
        pass
    return "normal"


def resolve_prompt_selection(
    camera: str,
    config: ServiceConfig,
    *,
    context_fields: dict[str, str] | None = None,
    mode: str | None = None,
) -> PromptSelection:
    resolved_mode = str(mode or resolve_runtime_mode(config) or "normal").strip().lower() or "normal"
    preset = resolve_preset(camera, config, context_fields=context_fields)
    profile_name = _resolve_profile_name(camera, resolved_mode, config)
    profile = None
    prompt_profiles = getattr(config.ai, "prompt_profiles", {}) or {}
    if profile_name:
        profile = prompt_profiles.get(profile_name)
    return PromptSelection(
        mode=resolved_mode,
        preset=preset,
        profile_name=profile_name,
        profile=profile,
    )


def render_prompts(
    preset: str,
    camera_name: str,
    allowed_actions: list[str],
    allowed_subject_types: list[str],
    config: ServiceConfig,
    context_fields: dict[str, str] | None = None,
    prompt_profile: Any | None = None,
) -> tuple[str, str]:
    templates: dict[str, dict[str, str]] = config.ai.prompt_presets
    selected = templates.get(preset) or templates.get(config.ai.default_prompt_preset) or {}
    system_template = str(selected.get("system", config.ai.system_prompt))
    user_template = str(selected.get("user", ""))
    profile_prompt_overrides = getattr(prompt_profile, "prompt_overrides", None)
    if profile_prompt_overrides is not None:
        if profile_prompt_overrides.system:
            system_template = str(profile_prompt_overrides.system)
        if profile_prompt_overrides.user:
            user_template = str(profile_prompt_overrides.user)
    environment = str((context_fields or {}).get("environment", "") or "").strip()
    purpose = str((context_fields or {}).get("purpose", "") or "").strip()
    mounting_location = str((context_fields or {}).get("mounting_location", "") or "").strip()
    view_context_summary = str((context_fields or {}).get("view_context_summary", "") or "").strip()
    focus_notes = str((context_fields or {}).get("focus_notes", "") or "").strip()
    expected_activity = str((context_fields or {}).get("expected_activity", "") or "").strip()
    delivery_focus = str((context_fields or {}).get("delivery_focus", "") or "").strip()
    (
        environment,
        view_context_summary,
        focus_notes,
        expected_activity,
        delivery_focus,
    ) = _apply_lean_rules(
        purpose=purpose,
        environment=environment,
        view_context_summary=view_context_summary,
        focus_notes=focus_notes,
        expected_activity=expected_activity,
        delivery_focus=delivery_focus,
        include_expected_activity=bool(getattr(config.ai, "include_expected_activity", False)),
    )
    privacy_rules = str(config.ai.privacy_rules or "")
    if profile_prompt_overrides is not None and profile_prompt_overrides.privacy_rules:
        privacy_rules = str(profile_prompt_overrides.privacy_rules)
    format_args = {
        "camera_name": camera_name,
        "environment": environment,
        "purpose": purpose,
        "mounting_location": mounting_location,
        "view_context_summary": view_context_summary,
        "focus_notes": focus_notes,
        "expected_activity": expected_activity,
        "delivery_focus": delivery_focus,
        "allowed_actions": _compact_list(allowed_actions),
        "allowed_subject_types": _compact_list(allowed_subject_types),
        "privacy_rules": privacy_rules,
    }
    camera_cfg = config.policy.cameras.get(camera_name)
    security_overlay = ""
    if (
        camera_cfg is not None
        and camera_cfg.security_capable
        and camera_cfg.security_mode
        and purpose != "child_room"
    ):
        security_overlay_template = str(config.ai.security_overlay_template or "")
        if (
            profile_prompt_overrides is not None
            and profile_prompt_overrides.security_overlay_template is not None
        ):
            security_overlay_template = str(profile_prompt_overrides.security_overlay_template)
        security_overlay = security_overlay_template
    format_args["security_overlay"] = security_overlay

    system_prompt = _strip_blank_lines(system_template.format(**format_args))
    user_prompt = _strip_blank_lines(user_template.format(**format_args))
    output_rules = (
        str(getattr(prompt_profile, "output_rules", "") or "").strip()
        if prompt_profile is not None
        else ""
    )
    if output_rules:
        if output_rules not in system_prompt:
            system_prompt = _strip_blank_lines(f"{system_prompt}\n{output_rules}")
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
            "mounting_location": "",
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
        "mounting_location": str(profile.get("mounting_location", "") or ""),
        "view_context_summary": str((selected_view or {}).get("context_summary", "") or ""),
        "focus_notes": str((selected_view or {}).get("focus_notes", "") or ""),
        "expected_activity": ", ".join(expected_activity),
        "delivery_focus": ", ".join(delivery_focus),
    }


def _assert_no_placeholders(text: str, *, prompt_name: str) -> None:
    if _PLACEHOLDER_PATTERN.search(text):
        raise ValueError(f"unresolved template placeholders in {prompt_name} prompt")


def _clip(text: str, max_chars: int) -> str:
    value = str(text or "").strip()
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip()


def _compact_list(items: list[str]) -> str:
    compact = [str(item).strip() for item in items if str(item).strip()]
    return json.dumps(compact, separators=(",", ":"))


def _strip_blank_lines(text: str) -> str:
    lines = text.splitlines()
    compact: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        compact.append(line.rstrip())
        previous_blank = is_blank
    return "\n".join(compact).strip()


def _apply_lean_rules(
    *,
    purpose: str,
    environment: str,
    view_context_summary: str,
    focus_notes: str,
    expected_activity: str,
    delivery_focus: str,
    include_expected_activity: bool,
) -> tuple[str, str, str, str, str]:
    lean_environment = environment
    if purpose in {"doorbell", "perimeter_security", "driveway", "backyard"}:
        lean_environment = ""
    lean_expected_activity = expected_activity if include_expected_activity else ""
    lean_delivery_focus = delivery_focus if purpose == "doorbell" else ""
    return (
        lean_environment,
        _clip(view_context_summary, 300),
        _clip(focus_notes, 300),
        lean_expected_activity,
        lean_delivery_focus,
    )


def _resolve_profile_name(camera: str, mode: str, config: ServiceConfig) -> str | None:
    normalized_camera = str(camera or "").strip()
    normalized_mode = str(mode or "").strip().lower() or "normal"
    per_camera = getattr(config.ai, "per_camera_mode_profiles", {}) or {}
    if normalized_camera in per_camera:
        camera_mode_map = per_camera.get(normalized_camera) or {}
        if normalized_mode in camera_mode_map:
            return str(camera_mode_map[normalized_mode]).strip() or None
    global_map = getattr(config.ai, "mode_profiles", {}) or {}
    if normalized_mode in global_map:
        return str(global_map[normalized_mode]).strip() or None
    if "default" in (getattr(config.ai, "prompt_profiles", {}) or {}):
        return "default"
    return None


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
    if action in {"person_leaving", "deliver_package", "pickup_package"}:
        return False
    if _resolve_camera_purpose(event.camera, config) != "doorbell":
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
    right_edge_touch_ratio = float(getattr(override_cfg, "right_edge_touch_ratio", 0.95))
    min_edge_touch_area_ratio = float(getattr(override_cfg, "min_edge_touch_area_ratio", 0.05))
    area_ratio = (w * h) / float(frame_w * frame_h)
    if area_ratio >= area_ratio_threshold:
        return True

    right_edge_x = x + w
    touches_right_edge = right_edge_x >= int(frame_w * right_edge_touch_ratio)
    mostly_on_right_side = x >= int(frame_w * 0.5)
    return touches_right_edge and mostly_on_right_side and area_ratio >= min_edge_touch_area_ratio


def _resolve_camera_purpose(camera: str, config: ServiceConfig) -> str:
    try:
        db_path = getattr(getattr(config, "paths", None), "db_file", None)
        if db_path:
            profile = db_get_camera_profile(db_path, camera) or {}
            purpose = str(profile.get("purpose", "") or "").strip()
            if purpose:
                return purpose
    except Exception:
        pass
    camera_cfg = getattr(getattr(config, "policy", None), "cameras", {}).get(camera)
    if camera_cfg is None:
        return ""
    return str(getattr(camera_cfg, "prompt_preset", "") or "").strip()
