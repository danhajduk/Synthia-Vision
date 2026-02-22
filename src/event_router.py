"""Event routing based on policy decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from src.models import FrigateEvent
from src.policy_engine import Decision

LOGGER = logging.getLogger("synthia_vision")


@dataclass(slots=True)
class RouterCounters:
    accepted: int = 0
    rejected: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class RouteResult:
    route: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class EventRouter:
    """Routes policy decisions and tracks debug counters."""

    def __init__(self) -> None:
        self._counters = RouterCounters()

    def route(self, event: FrigateEvent, decision: Decision) -> RouteResult:
        if decision.should_process:
            self._counters.accepted += 1
            result = RouteResult(
                route="processing",
                reason=decision.reason,
                details=decision.details,
            )
            LOGGER.info(
                "Event routed: route=%s event_id=%s camera=%s reason=%s",
                result.route,
                event.event_id,
                event.camera,
                result.reason,
            )
            return result

        self._counters.rejected += 1
        self._counters.rejected_by_reason[decision.reason] = (
            self._counters.rejected_by_reason.get(decision.reason, 0) + 1
        )
        result = RouteResult(
            route="rejected",
            reason=decision.reason,
            details=decision.details,
        )
        LOGGER.info(
            "Event routed: route=%s event_id=%s camera=%s reason=%s rejected_count=%s",
            result.route,
            event.event_id,
            event.camera,
            result.reason,
            self._counters.rejected,
        )
        return result

    def counters_snapshot(self) -> RouterCounters:
        return RouterCounters(
            accepted=self._counters.accepted,
            rejected=self._counters.rejected,
            rejected_by_reason=dict(self._counters.rejected_by_reason),
        )
