"""Home Assistant MQTT discovery payload generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.config import ServiceConfig


@dataclass(slots=True)
class DiscoveryMessage:
    topic: str
    payload: str


class HADiscoveryPublisher:
    """Builds Home Assistant MQTT discovery messages."""

    def __init__(self, config: ServiceConfig) -> None:
        self._config = config
        self._prefix = config.mqtt_discovery.prefix
        self._node_id = config.mqtt_discovery.node_id
        self._runtime_prefix = config.service.mqtt_prefix
        self._device = config.mqtt_discovery.device

    def build_messages(self, cameras: list[str]) -> list[DiscoveryMessage]:
        messages: list[DiscoveryMessage] = []
        messages.extend(self._core_messages())
        for camera in cameras:
            messages.extend(self._camera_messages(camera))
        return messages

    def _core_messages(self) -> list[DiscoveryMessage]:
        core_device = {
            "name": self._config.service.name,
            "identifiers": ["synthia_vision", self._node_id],
            "manufacturer": self._device.manufacturer,
            "model": self._device.model,
            "sw_version": self._device.sw_version,
        }
        messages: list[DiscoveryMessage] = []

        status_payload = {
            "name": "Synthia Vision Status",
            "object_id": "synthia_vision_status",
            "unique_id": f"sv_{self._node_id}_core_status",
            "state_topic": self._core_topic("status", "status"),
            "icon": "mdi:brain",
            "device": core_device,
        }
        messages.append(
            DiscoveryMessage(
                topic=f"{self._prefix}/sensor/{self._node_id}/status/config",
                payload=json.dumps(status_payload, separators=(",", ":")),
            )
        )

        heartbeat_payload = {
            "name": "Synthia Vision Heartbeat",
            "object_id": "synthia_vision_heartbeat",
            "unique_id": f"sv_{self._node_id}_core_heartbeat",
            "state_topic": self._core_topic("heartbeat_ts", "heartbeat_ts"),
            "device_class": "timestamp",
            "icon": "mdi:heart-pulse",
            "device": core_device,
        }
        messages.append(
            DiscoveryMessage(
                topic=f"{self._prefix}/sensor/{self._node_id}/heartbeat/config",
                payload=json.dumps(heartbeat_payload, separators=(",", ":")),
            )
        )

        core_entities: list[tuple[str, str, dict[str, Any]]] = [
            ("cost_last", "sensor", {
                "name": "Synthia Vision Last Cost",
                "icon": "mdi:currency-usd",
                "state_topic": self._core_topic("cost.last", "cost/last"),
                "unit_of_measurement": "USD",
            }),
            ("cost_daily_total", "sensor", {
                "name": "Synthia Vision Daily Cost",
                "icon": "mdi:calendar-today",
                "state_topic": self._core_topic("cost.daily_total", "cost/daily_total"),
                "unit_of_measurement": "USD",
            }),
            ("cost_month2day_total", "sensor", {
                "name": "Synthia Vision Month Cost",
                "icon": "mdi:calendar-month",
                "state_topic": self._core_topic("cost.month2day_total", "cost/month2day_total"),
                "unit_of_measurement": "USD",
            }),
            ("cost_avg_per_event", "sensor", {
                "name": "Synthia Vision Avg Cost Event",
                "icon": "mdi:calculator-variant",
                "state_topic": self._core_topic("cost.avg_per_event", "cost/avg_per_event"),
                "unit_of_measurement": "USD",
            }),
            ("tokens_avg_per_request", "sensor", {
                "name": "Synthia Vision Avg Tokens Request",
                "icon": "mdi:counter",
                "state_topic": self._core_topic("tokens.avg_per_request", "tokens/avg_per_request"),
                "unit_of_measurement": "tokens",
            }),
            ("tokens_avg_per_day", "sensor", {
                "name": "Synthia Vision Avg Tokens Day",
                "icon": "mdi:calendar-clock",
                "state_topic": self._core_topic("tokens.avg_per_day", "tokens/avg_per_day"),
                "unit_of_measurement": "tokens/day",
            }),
            ("events_count_total", "sensor", {
                "name": "Synthia Vision Events Total",
                "icon": "mdi:counter",
                "state_topic": self._core_topic("events.count_total", "events/count_total"),
                "unit_of_measurement": "events",
            }),
            ("events_count_today", "sensor", {
                "name": "Synthia Vision Events Today",
                "icon": "mdi:counter",
                "state_topic": self._core_topic("events.count_today", "events/count_today"),
                "unit_of_measurement": "events",
            }),
            ("control_enabled", "switch", {
                "name": "Synthia Vision Enabled",
                "icon": "mdi:power",
                "state_topic": self._core_topic("control.enabled", "control/enabled"),
                "command_topic": self._core_topic("control.enabled_set", "control/enabled/set"),
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_on": "ON",
                "state_off": "OFF",
            }),
            ("control_monthly_budget", "number", {
                "name": "Synthia Vision Monthly Budget",
                "icon": "mdi:cash-check",
                "state_topic": self._core_topic("control.monthly_budget", "control/monthly_budget"),
                "command_topic": self._core_topic("control.monthly_budget_set", "control/monthly_budget/set"),
                "min": 0,
                "max": 200,
                "step": 0.5,
                "unit_of_measurement": "USD",
                "mode": "box",
            }),
            ("control_confidence_threshold", "number", {
                "name": "Synthia Vision Confidence Threshold",
                "icon": "mdi:percent",
                "state_topic": self._core_topic("control.confidence_threshold", "control/confidence_threshold"),
                "command_topic": self._core_topic("control.confidence_threshold_set", "control/confidence_threshold/set"),
                "min": 0,
                "max": 100,
                "step": 1,
                "unit_of_measurement": "%",
                "mode": "box",
            }),
        ]

        for entity_key, component, data in core_entities:
            payload = {
                "object_id": f"synthia_vision_{entity_key}",
                "unique_id": f"sv_{self._node_id}_core_{entity_key}",
                "device": core_device,
                **data,
            }
            messages.append(
                DiscoveryMessage(
                    topic=f"{self._prefix}/{component}/{self._node_id}/{entity_key}/config",
                    payload=json.dumps(payload, separators=(",", ":")),
                )
            )
        return messages

    def _camera_messages(self, camera: str) -> list[DiscoveryMessage]:
        camera_slug = camera.replace(" ", "_").lower()
        configured_name = None
        camera_cfg = self._config.policy.cameras.get(camera)
        if camera_cfg is not None:
            configured_name = camera_cfg.name
        camera_name = configured_name or _display_camera_name(camera)
        device = {
            "name": camera_name,
            # Requested behavior: use camera key itself as the stable device identifier.
            "identifiers": [camera],
            "manufacturer": self._device.manufacturer,
            "model": "Synthia Vision Camera",
            "sw_version": self._device.sw_version,
            "via_device": "synthia_vision",
        }

        entities: list[tuple[str, str, dict[str, Any]]] = [
            (
                "enabled",
                "switch",
                {
                    "name": "Enabled",
                    "icon": "mdi:power",
                    "state_topic": self._camera_topic(camera, "enabled"),
                    "command_topic": self._camera_topic(camera, "enabled_set"),
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "state_on": "ON",
                    "state_off": "OFF",
                },
            ),
            (
                "action",
                "sensor",
                {
                    "name": "Action",
                    "icon": "mdi:cctv",
                    "state_topic": self._camera_topic(camera, "action"),
                },
            ),
            (
                "confidence",
                "sensor",
                {
                    "name": "Confidence",
                    "icon": "mdi:percent",
                    "state_topic": self._camera_topic(camera, "confidence"),
                    "unit_of_measurement": "%",
                },
            ),
            (
                "description",
                "sensor",
                {
                    "name": "Description",
                    "icon": "mdi:text",
                    "state_topic": self._camera_topic(camera, "description"),
                },
            ),
            (
                "result_status",
                "sensor",
                {
                    "name": "Result Status",
                    "icon": "mdi:shield-alert",
                    "state_topic": self._camera_topic(camera, "result_status"),
                },
            ),
            (
                "last_event_id",
                "sensor",
                {
                    "name": "Last Event ID",
                    "icon": "mdi:identifier",
                    "state_topic": self._camera_topic(camera, "last_event_id"),
                },
            ),
            (
                "last_event_ts",
                "sensor",
                {
                    "name": "Last Event Time",
                    "icon": "mdi:clock-outline",
                    "state_topic": self._camera_topic(camera, "last_event_ts"),
                    "device_class": "timestamp",
                },
            ),
            (
                "monthly_cost",
                "sensor",
                {
                    "name": "Monthly Cost",
                    "icon": "mdi:currency-usd",
                    "state_topic": self._core_topic_for_camera(
                        camera=camera,
                        dotted_key="cost.monthly_by_camera",
                        fallback_suffix="cost/monthly_by_camera/{camera}",
                    ),
                    "unit_of_measurement": "USD",
                },
            ),
        ]

        messages: list[DiscoveryMessage] = []
        for entity_key, component, data in entities:
            payload = {
                "object_id": f"sv_{camera_slug}_{entity_key}",
                "unique_id": f"sv_{self._node_id}_{camera_slug}_{entity_key}",
                "device": device,
                **data,
            }
            messages.append(
                DiscoveryMessage(
                    topic=f"{self._prefix}/{component}/{self._node_id}/{camera_slug}_{entity_key}/config",
                    payload=json.dumps(payload, separators=(",", ":")),
                )
            )
        return messages

    def _topic(self, suffix: str) -> str:
        return f"{self._runtime_prefix}/{suffix}"

    def _camera_topic(self, camera: str, key: str) -> str:
        camera_topics = self._config.topics.get("camera", {})
        template = str(camera_topics.get(key, f"{{mqtt_prefix}}/camera/{{camera}}/{key}"))
        return (
            template.replace("{mqtt_prefix}", self._runtime_prefix)
            .replace("{camera}", camera)
        )

    def _core_topic(self, dotted_key: str, fallback_suffix: str) -> str:
        node: Any = self._config.topics
        for part in dotted_key.split("."):
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(part)
        template = str(node) if isinstance(node, str) else f"{{mqtt_prefix}}/{fallback_suffix}"
        return template.replace("{mqtt_prefix}", self._runtime_prefix)

    def _core_topic_for_camera(
        self,
        *,
        camera: str,
        dotted_key: str,
        fallback_suffix: str,
    ) -> str:
        return self._core_topic(dotted_key, fallback_suffix).replace("{camera}", camera)


def _display_camera_name(camera: str) -> str:
    base = camera.replace("_", " ").strip()
    no_doorbell = re.sub(r"\bdoorbell\b", "", base, flags=re.IGNORECASE)
    collapsed = re.sub(r"\s+", " ", no_doorbell).strip()
    return collapsed.title() if collapsed else "Camera"
