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
        )


@dataclass(slots=True)
class OpenAIClassification:
    """Validated structured output from OpenAI."""

    action: str
    subject_type: str
    confidence: float
    description: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OpenAIClassification":
        action = payload.get("action")
        subject_type = payload.get("subject_type")
        confidence = payload.get("confidence")
        description = payload.get("description")

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
        )


def _as_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raise ValidationError(f"Expected numeric timestamp, got {type(value).__name__}")
