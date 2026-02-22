"""Pure policy decision interface."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Mapping

from src.config import ServiceConfig
from src.models import FrigateEvent

LOGGER = logging.getLogger("synthia_vision.policy")


@dataclass(slots=True)
class Decision:
    """Pure policy result for a candidate event."""

    should_process: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


def should_process(
    event: FrigateEvent,
    state: Mapping[str, Any],
    config: ServiceConfig,
) -> Decision:
    """Return a deterministic decision with no side effects."""
    allowed_types = [event_type.lower() for event_type in config.policy.defaults.process_on]
    if not _is_event_type_allowed(event, config):
        return _reject(
            event,
            "event_type_not_allowed",
            {
                "event_type": event.event_type,
                "allowed_event_types": allowed_types,
            },
        )

    if _is_duplicate_event(event, state):
        return _reject(event, "duplicate_event_id", {"event_id": event.event_id})

    if not _is_camera_enabled(event, config):
        return _reject(event, "camera_disabled", {"camera": event.camera})

    if _blocked_by_doorbell_only_mode(event, config):
        return _reject(
            event,
            "camera_blocked_by_mode",
            {
                "camera": event.camera,
                "allowed_cameras": config.modes.doorbell_only_mode.allowed_cameras,
            },
        )

    if not _is_label_allowed(event, config):
        return _reject(
            event,
            "label_not_allowed",
            {
                "label": event.label,
                "allowed_labels": _allowed_labels(event, config),
            },
        )

    if not _passes_confidence_threshold(event, config):
        return _reject(
            event,
            "below_confidence_threshold",
            {
                "threshold": _confidence_threshold(event, config),
                "score": event.score if event.score is not None else 1.0,
            },
        )

    cooldown_remaining = _cooldown_remaining_seconds(event, state, config)
    if cooldown_remaining is not None and cooldown_remaining > 0:
        cooldown_context = _cooldown_context(event, state, config)
        return _reject(
            event,
            "cooldown_active",
            {
                "camera": event.camera,
                "cooldown_remaining_s": round(cooldown_remaining, 3),
                "min_process_interval_s": cooldown_context["min_process_interval_s"],
                "camera_cooldown_s": cooldown_context["camera_cooldown_s"],
                "effective_interval_s": cooldown_context["effective_interval_s"],
                "elapsed_s": cooldown_context["elapsed_s"],
            },
        )

    return _accept(event, {"event_type": event.event_type, "label": event.label})


def _is_event_type_allowed(event: FrigateEvent, config: ServiceConfig) -> bool:
    allowed_types = {event_type.lower() for event_type in config.policy.defaults.process_on}
    return event.event_type.lower() in allowed_types


def _is_duplicate_event(event: FrigateEvent, state: Mapping[str, Any]) -> bool:
    events_data = _mapping(state.get("events"))
    recent_ids_raw = events_data.get("recent_event_ids", [])
    if not isinstance(recent_ids_raw, list):
        return False
    return event.event_id in recent_ids_raw


def _is_camera_enabled(event: FrigateEvent, config: ServiceConfig) -> bool:
    camera_policy = config.policy.cameras.get(event.camera)
    if camera_policy is not None:
        return camera_policy.enabled
    return config.policy.defaults.enabled


def _blocked_by_doorbell_only_mode(event: FrigateEvent, config: ServiceConfig) -> bool:
    mode = config.modes.doorbell_only_mode
    if not mode.enabled:
        return False
    return event.camera not in set(mode.allowed_cameras)


def _is_label_allowed(event: FrigateEvent, config: ServiceConfig) -> bool:
    return event.label in _allowed_labels(event, config)


def _allowed_labels(event: FrigateEvent, config: ServiceConfig) -> list[str]:
    camera_policy = config.policy.cameras.get(event.camera)
    return camera_policy.labels if camera_policy else config.policy.defaults.labels


def _passes_confidence_threshold(event: FrigateEvent, config: ServiceConfig) -> bool:
    threshold = _confidence_threshold(event, config)
    # Frigate score may be absent; defaulting to 1.0 avoids false rejects until score plumbing is complete.
    observed_score = event.score if event.score is not None else 1.0
    return observed_score >= threshold


def _confidence_threshold(event: FrigateEvent, config: ServiceConfig) -> float:
    camera_policy = config.policy.cameras.get(event.camera)
    threshold = (
        camera_policy.confidence_threshold
        if camera_policy
        else config.policy.defaults.confidence_threshold
    )
    if (
        config.modes.high_precision_mode.enabled
        and config.modes.high_precision_mode.confidence_threshold_override is not None
    ):
        threshold = max(threshold, config.modes.high_precision_mode.confidence_threshold_override)
    return threshold


def _is_in_cooldown(
    event: FrigateEvent,
    state: Mapping[str, Any],
    config: ServiceConfig,
) -> bool:
    remaining = _cooldown_remaining_seconds(event, state, config)
    return remaining is not None and remaining > 0


def _cooldown_remaining_seconds(
    event: FrigateEvent,
    state: Mapping[str, Any],
    config: ServiceConfig,
) -> float | None:
    if event.event_ts is None:
        return None

    events_data = _mapping(state.get("events"))
    last_by_camera = _mapping(events_data.get("last_by_camera"))
    camera_state = _mapping(last_by_camera.get(event.camera))
    last_ts = _extract_last_ts(camera_state)
    if last_ts is None:
        return None

    camera_policy = config.policy.cameras.get(event.camera)
    per_camera_cooldown = (
        camera_policy.cooldown_seconds
        if camera_policy
        else config.dedupe.per_camera_cooldown_default_seconds
    )
    effective_cooldown = max(
        float(per_camera_cooldown),
        config.policy.defaults.min_process_interval_seconds,
    )
    elapsed = event.event_ts - last_ts
    return max(0.0, effective_cooldown - elapsed)


def _cooldown_context(
    event: FrigateEvent,
    state: Mapping[str, Any],
    config: ServiceConfig,
) -> dict[str, float]:
    event_ts = event.event_ts if event.event_ts is not None else 0.0
    events_data = _mapping(state.get("events"))
    last_by_camera = _mapping(events_data.get("last_by_camera"))
    camera_state = _mapping(last_by_camera.get(event.camera))
    last_ts = _extract_last_ts(camera_state) or event_ts

    camera_policy = config.policy.cameras.get(event.camera)
    camera_cooldown = float(
        camera_policy.cooldown_seconds
        if camera_policy
        else config.dedupe.per_camera_cooldown_default_seconds
    )
    min_interval = float(config.policy.defaults.min_process_interval_seconds)
    effective_interval = max(camera_cooldown, min_interval)
    elapsed = max(0.0, event_ts - last_ts)
    return {
        "min_process_interval_s": min_interval,
        "camera_cooldown_s": camera_cooldown,
        "effective_interval_s": effective_interval,
        "elapsed_s": round(elapsed, 3),
    }


def _extract_last_ts(camera_state: Mapping[str, Any]) -> float | None:
    for key in ("last_event_ts", "last_processed_ts", "ts"):
        value = camera_state.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _reject(event: FrigateEvent, reason: str, details: dict[str, Any]) -> Decision:
    decision = Decision(False, reason, details)
    LOGGER.info(
        "Policy reject event_id=%s camera=%s reason=%s details=%s",
        event.event_id,
        event.camera,
        reason,
        details,
    )
    return decision


def _accept(event: FrigateEvent, details: dict[str, Any] | None = None) -> Decision:
    decision = Decision(True, "accepted", details or {})
    LOGGER.info(
        "Policy accept event_id=%s camera=%s reason=%s details=%s",
        event.event_id,
        event.camera,
        decision.reason,
        decision.details,
    )
    return decision
