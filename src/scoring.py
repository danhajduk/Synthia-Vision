"""Event risk scoring helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from src.config.settings import ScoringConfig, ScoringWeightsConfig
from src.models import FrigateEvent


def compute_event_risk_score(
    *,
    event: FrigateEvent,
    ai_confidence: float | None,
    scoring: ScoringConfig,
) -> float:
    camera_name = str(event.camera or "").strip().lower()
    override = scoring.per_camera_overrides.get(camera_name)
    weights = _effective_weights(scoring.weights, override)

    time_component = _time_of_day_score(event)
    camera_zone_component = _camera_zone_score(event, scoring)
    ai_component = _clamp01(ai_confidence if ai_confidence is not None else 0.0)
    duration_component = _duration_score(event)

    weighted_total = (
        (weights.time_of_day * time_component)
        + (weights.camera_zone * camera_zone_component)
        + (weights.ai_confidence * ai_component)
        + (weights.duration * duration_component)
    )
    weight_sum = (
        weights.time_of_day
        + weights.camera_zone
        + weights.ai_confidence
        + weights.duration
    )
    if weight_sum <= 0:
        return 0.0
    return round(_clamp01(weighted_total / weight_sum), 4)


def _effective_weights(
    base: ScoringWeightsConfig,
    override,
) -> ScoringWeightsConfig:
    if override is None:
        return base
    return ScoringWeightsConfig(
        time_of_day=base.time_of_day if override.time_of_day is None else float(override.time_of_day),
        camera_zone=base.camera_zone if override.camera_zone is None else float(override.camera_zone),
        ai_confidence=base.ai_confidence
        if override.ai_confidence is None
        else float(override.ai_confidence),
        duration=base.duration if override.duration is None else float(override.duration),
    )


def _time_of_day_score(event: FrigateEvent) -> float:
    if event.event_ts is None:
        return 0.5
    dt = datetime.fromtimestamp(float(event.event_ts), tz=timezone.utc)
    hour = int(dt.hour)
    if hour < 6 or hour >= 22:
        return 1.0
    if hour < 8 or hour >= 20:
        return 0.75
    return 0.45


def _camera_zone_score(event: FrigateEvent, scoring: ScoringConfig) -> float:
    camera_name = str(event.camera or "").strip().lower()
    camera_score = float(
        scoring.camera_importance.overrides.get(camera_name, scoring.camera_importance.default)
    )
    zone_score = float(scoring.zone_weights.default)
    zones = event.zones if isinstance(event.zones, tuple) else ()
    for zone_name in zones:
        normalized = str(zone_name or "").strip().lower()
        if not normalized:
            continue
        zone_score = max(zone_score, float(scoring.zone_weights.overrides.get(normalized, zone_score)))
    return _clamp01(max(camera_score, zone_score))


def _duration_score(event: FrigateEvent) -> float:
    if event.start_time is None or event.end_time is None:
        return 0.0
    duration_s = max(0.0, float(event.end_time) - float(event.start_time))
    # 30s+ movement/event windows are treated as maximal duration risk.
    return _clamp01(duration_s / 30.0)


def _clamp01(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return float(value)
