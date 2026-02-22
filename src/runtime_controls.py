"""Runtime controls for event-type processing gates."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any


@dataclass(slots=True)
class EventControlSettings:
    process_end_events: bool = True
    process_update_events: bool = False
    updates_per_event: int = 1
    update_ttl_seconds: int = 600


@dataclass(slots=True)
class EventControlGateResult:
    allow: bool
    reason: str


def normalize_event_type(raw_event_type: str) -> str:
    return raw_event_type.strip().lower()


def cleanup_update_tracking(
    updates_processed_count: dict[str, int],
    last_seen_ts: dict[str, float],
    *,
    now_ts: float | None = None,
    ttl_seconds: int = 600,
) -> None:
    now = now_ts if now_ts is not None else time.time()
    expire_before = now - max(1, ttl_seconds)
    stale_ids = [event_id for event_id, ts in last_seen_ts.items() if ts < expire_before]
    for event_id in stale_ids:
        last_seen_ts.pop(event_id, None)
        updates_processed_count.pop(event_id, None)


def apply_event_controls(
    *,
    event_id: str,
    event_type: str,
    settings: EventControlSettings,
    updates_processed_count: dict[str, int],
    last_seen_ts: dict[str, float],
    event_ts: float | None,
) -> EventControlGateResult:
    now = event_ts if event_ts is not None else time.time()
    cleanup_update_tracking(
        updates_processed_count,
        last_seen_ts,
        now_ts=now,
        ttl_seconds=settings.update_ttl_seconds,
    )

    normalized_type = normalize_event_type(event_type)
    last_seen_ts[event_id] = now

    if normalized_type == "end":
        # End closes an event window and releases update counters.
        updates_processed_count.pop(event_id, None)
        last_seen_ts.pop(event_id, None)
        if settings.process_end_events:
            return EventControlGateResult(True, "event_type_end_enabled")
        return EventControlGateResult(False, "event_type_end_disabled")

    if normalized_type == "update":
        if not settings.process_update_events:
            return EventControlGateResult(False, "event_type_update_disabled")
        count = updates_processed_count.get(event_id, 0)
        if count >= settings.updates_per_event:
            return EventControlGateResult(False, "event_type_update_limit_reached")
        updates_processed_count[event_id] = count + 1
        return EventControlGateResult(True, "event_type_update_enabled")

    # Unsupported/unknown event types are suppressed at this control layer.
    return EventControlGateResult(False, "event_type_not_supported")


def bool_to_on_off(value: bool) -> str:
    return "ON" if value else "OFF"


def parse_on_off(payload: str) -> bool | None:
    normalized = payload.strip().upper()
    if normalized == "ON":
        return True
    if normalized == "OFF":
        return False
    return None


def parse_updates_per_event(payload: str) -> int | None:
    normalized = payload.strip()
    if normalized not in {"1", "2"}:
        return None
    return int(normalized)


def controls_from_state(state: dict[str, Any]) -> EventControlSettings:
    controls = state.get("controls")
    if not isinstance(controls, dict):
        return EventControlSettings()

    process_end_events = controls.get("process_end_events")
    process_update_events = controls.get("process_update_events")
    updates_per_event = controls.get("updates_per_event")

    if not isinstance(process_end_events, bool):
        process_end_events = True
    if not isinstance(process_update_events, bool):
        process_update_events = False
    if not isinstance(updates_per_event, int) or updates_per_event not in {1, 2}:
        updates_per_event = 1

    return EventControlSettings(
        process_end_events=process_end_events,
        process_update_events=process_update_events,
        updates_per_event=updates_per_event,
    )


def camera_event_controls_from_state(
    state: dict[str, Any],
    camera: str,
    *,
    default_process_end_events: bool = True,
    default_process_update_events: bool = False,
) -> tuple[bool, bool]:
    controls = state.get("controls")
    if not isinstance(controls, dict):
        return (default_process_end_events, default_process_update_events)

    camera_controls = controls.get("camera_event_processing")
    if not isinstance(camera_controls, dict):
        return (default_process_end_events, default_process_update_events)

    raw = camera_controls.get(camera)
    if not isinstance(raw, dict):
        return (default_process_end_events, default_process_update_events)

    process_end = raw.get("process_end_events")
    process_update = raw.get("process_update_events")
    if not isinstance(process_end, bool):
        process_end = default_process_end_events
    if not isinstance(process_update, bool):
        process_update = default_process_update_events
    return (process_end, process_update)
