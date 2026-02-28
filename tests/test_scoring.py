"""Tests for event risk scoring helpers."""

from __future__ import annotations

import unittest

from src.config.settings import (
    ScoringConfig,
    ScoringScaleConfig,
    ScoringWeightOverrideConfig,
    ScoringWeightsConfig,
)
from src.models import FrigateEvent
from src.scoring import compute_event_risk_score


class RiskScoringTests(unittest.TestCase):
    def test_score_uses_camera_override_and_duration(self) -> None:
        config = ScoringConfig(
            weights=ScoringWeightsConfig(
                time_of_day=0.2,
                camera_zone=0.3,
                ai_confidence=0.4,
                duration=0.1,
            ),
            per_camera_overrides={
                "doorbell": ScoringWeightOverrideConfig(ai_confidence=0.6, camera_zone=0.2),
            },
            camera_importance=ScoringScaleConfig(default=0.5, overrides={"doorbell": 0.9}),
            zone_weights=ScoringScaleConfig(default=0.4, overrides={"porch": 0.8}),
        )
        event = FrigateEvent(
            event_id="evt-score-1",
            camera="doorbell",
            label="person",
            event_type="end",
            event_ts=1700000000.0,
            start_time=1700000000.0,
            end_time=1700000020.0,
            zones=("porch",),
        )
        score = compute_event_risk_score(event=event, ai_confidence=0.8, scoring=config)
        self.assertGreater(score, 0.7)
        self.assertLessEqual(score, 1.0)

    def test_score_defaults_to_zero_confidence_when_missing(self) -> None:
        config = ScoringConfig()
        event = FrigateEvent(
            event_id="evt-score-2",
            camera="livingroom",
            label="person",
            event_type="update",
            event_ts=1700000000.0,
        )
        score = compute_event_risk_score(event=event, ai_confidence=None, scoring=config)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


if __name__ == "__main__":
    unittest.main()
