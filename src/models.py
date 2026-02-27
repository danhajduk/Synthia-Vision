"""Core data models used across the service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ValidationError


@dataclass(slots=True)
class FrigateEvent:
    """Normalized Frigate event emitted from MQTT payloads."""

    event_id: str
    camera: str
    label: str
    event_type: str
    score: float | None = None
    start_time: float | None = None
    end_time: float | None = None
    event_ts: float | None = None
    bbox: tuple[int, int, int, int] | None = None
    zones: tuple[str, ...] = ()
    motion_direction: str | None = None

    @classmethod
    def from_mqtt_payload(cls, payload: dict[str, Any]) -> "FrigateEvent":
        event_data = payload.get("after") or payload.get("event") or {}
        event_id = event_data.get("id")
        camera = event_data.get("camera")
        label = event_data.get("label")
        event_type = payload.get("type")

        if not isinstance(event_id, str) or not event_id:
            raise ValidationError("Frigate payload missing event id")
        if not isinstance(camera, str) or not camera:
            raise ValidationError("Frigate payload missing camera")
        if not isinstance(label, str) or not label:
            raise ValidationError("Frigate payload missing label")
        if not isinstance(event_type, str) or not event_type:
            raise ValidationError("Frigate payload missing type")

        return cls(
            event_id=event_id,
            camera=camera,
            label=label,
            event_type=event_type,
            score=_as_float_or_none(event_data.get("score")),
            start_time=_as_float_or_none(event_data.get("start_time")),
            end_time=_as_float_or_none(event_data.get("end_time")),
            event_ts=_as_float_or_none(payload.get("time")),
            bbox=_as_bbox_or_none(event_data.get("box")),
            zones=_as_string_tuple_or_empty(
                event_data.get("current_zones") or event_data.get("entered_zones")
            ),
            motion_direction=_as_optional_string(
                event_data.get("motion_direction") or event_data.get("direction")
            ),
        )


@dataclass(slots=True)
class OpenAIClassification:
    """Validated structured output from OpenAI."""

    action: str
    subject_type: str
    confidence: float
    description: str
    explanation: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OpenAIClassification":
        action = payload.get("action")
        subject_type = payload.get("subject_type")
        confidence = payload.get("confidence")
        description = payload.get("description")
        explanation = payload.get("explanation")

        if not isinstance(action, str) or not action:
            raise ValidationError("OpenAI payload missing action")
        if not isinstance(subject_type, str) or not subject_type:
            raise ValidationError("OpenAI payload missing subject_type")
        if not isinstance(description, str) or not description:
            raise ValidationError("OpenAI payload missing description")
        if not isinstance(confidence, (int, float)):
            raise ValidationError("OpenAI payload confidence must be numeric")

        confidence_value = float(confidence)
        if confidence_value < 0.0 or confidence_value > 1.0:
            raise ValidationError("OpenAI payload confidence must be between 0 and 1")

        return cls(
            action=action,
            subject_type=subject_type,
            confidence=confidence_value,
            description=description,
            explanation=explanation if isinstance(explanation, str) and explanation.strip() else None,
        )


def _as_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raise ValidationError(f"Expected numeric timestamp, got {type(value).__name__}")


def _as_bbox_or_none(value: Any) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    if isinstance(value, list) and len(value) == 4 and all(
        isinstance(item, (int, float)) for item in value
    ):
        x, y, w, h = (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
        if w > 0 and h > 0:
            return x, y, w, h
        return None
    if isinstance(value, dict):
        x = value.get("x")
        y = value.get("y")
        w = value.get("width")
        h = value.get("height")
        if all(isinstance(item, (int, float)) for item in (x, y, w, h)):
            x_i, y_i, w_i, h_i = int(x), int(y), int(w), int(h)
            if w_i > 0 and h_i > 0:
                return x_i, y_i, w_i, h_i
    return None


def _as_string_tuple_or_empty(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    normalized = [item for item in value if isinstance(item, str) and item.strip()]
    return tuple(normalized)


def _as_optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
