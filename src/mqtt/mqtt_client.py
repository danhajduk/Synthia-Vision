"""MQTT client wrapper with reconnect and lifecycle helpers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import re
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from src.config import ServiceConfig
from src.event_router import EventRouter
from src.ha_discovery import HADiscoveryPublisher
from src.errors import ExternalServiceError, ValidationError
from src.models import FrigateEvent
from src.policy_engine import should_process
from src.snapshot_manager import SnapshotManager
from src.state_manager import StateManager

LOGGER = logging.getLogger("synthia_vision.mqtt")


class MQTTClient:
    """Stateful MQTT wrapper used by the service lifecycle."""

    def __init__(self, config: ServiceConfig) -> None:
        self._config = config
        self._connected_event = threading.Event()
        self._disconnect_requested = False
        self._status_topic = _resolve_status_topic(config)
        self._heartbeat_topic = _resolve_heartbeat_topic(config)
        self._events_topic = config.mqtt.events_topic
        self._ha_status_topic = f"{config.mqtt_discovery.prefix}/status"
        self._camera_enabled_set_pattern = re.compile(
            rf"^{re.escape(self._config.service.mqtt_prefix)}/camera/([^/]+)/enabled/set$"
        )
        self._status_retain = config.mqtt.retain
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._state_manager = StateManager(config.state_file)
        self._snapshot_manager = SnapshotManager(config)
        self._ha_discovery = HADiscoveryPublisher(config)
        self._event_router = EventRouter()
        self._policy_runtime_state: dict[str, Any] = {
            "events": {
                "recent_event_ids": [],
                "last_by_camera": {},
            }
        }
        self._camera_enabled_overrides: dict[str, bool] = {}

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=config.service.slug,
            clean_session=True,
            transport="tcp",
            reconnect_on_failure=True,
        )
        self._client.enable_logger(LOGGER)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

        if config.mqtt.username:
            self._client.username_pw_set(
                username=config.mqtt.username,
                password=config.mqtt.password,
            )
        if config.mqtt.tls:
            self._client.tls_set()

        # Published by broker on unexpected disconnect.
        self._client.will_set(
            self._status_topic,
            payload="unavailable",
            qos=config.mqtt.qos,
            retain=self._status_retain,
        )

    async def startup_connect(self) -> None:
        """Connect and publish initial retained startup status."""
        await self._load_policy_state()
        self._disconnect_requested = False
        self._client.loop_start()
        self._client.connect_async(
            host=self._config.mqtt.host,
            port=self._config.mqtt.port,
            keepalive=self._config.mqtt.keepalive_seconds,
        )

        connected = await asyncio.to_thread(self._connected_event.wait, 15.0)
        if not connected:
            self._client.loop_stop()
            raise ExternalServiceError(
                f"Timed out connecting to MQTT broker {self._config.mqtt.host}:{self._config.mqtt.port}"
            )

        await self.publish_status("starting")
        LOGGER.info("MQTT connected and startup status published")

    async def startup_ready(self) -> None:
        """Publish ready state once all startup hooks succeed."""
        self._publish_discovery_configs()
        self._publish_core_defaults_unknown()
        self._publish_camera_defaults_all()
        await self.publish_status("enabled")
        self._start_heartbeat()
        LOGGER.info("MQTT ready status published")

    async def shutdown(self) -> None:
        """Graceful shutdown with final retained status publication."""
        self._disconnect_requested = True
        await self._stop_heartbeat()
        try:
            await self.publish_status("stopped")
        except ExternalServiceError:
            LOGGER.warning("Could not publish shutdown status before disconnect")
        await asyncio.to_thread(self._client.disconnect)
        await asyncio.to_thread(self._client.loop_stop)
        self._connected_event.clear()
        LOGGER.info("MQTT client stopped")

    async def publish_status(self, payload: str) -> None:
        await self.publish(self._status_topic, payload, retain=self._status_retain)

    async def publish_heartbeat(self) -> None:
        await self.publish(
            self._heartbeat_topic,
            datetime.now(timezone.utc).isoformat(),
            retain=self._status_retain,
        )

    async def publish(
        self,
        topic: str,
        payload: str | bytes | bytearray,
        *,
        retain: bool | None = None,
        qos: int | None = None,
    ) -> None:
        if not self._connected_event.is_set():
            raise ExternalServiceError("MQTT publish attempted while disconnected")
        effective_qos = self._config.mqtt.qos if qos is None else qos
        effective_retain = self._status_retain if retain is None else retain
        LOGGER.debug(
            "MQTT publish async topic=%s qos=%s retain=%s payload=%s",
            topic,
            effective_qos,
            effective_retain,
            _safe_payload_preview(payload),
        )
        publish_info = self._client.publish(
            topic=topic,
            payload=payload,
            qos=effective_qos,
            retain=effective_retain,
        )
        await asyncio.to_thread(publish_info.wait_for_publish, 5.0)
        LOGGER.debug(
            "MQTT publish async result topic=%s rc=%s mid=%s",
            topic,
            publish_info.rc,
            publish_info.mid,
        )
        if publish_info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ExternalServiceError(f"MQTT publish failed (rc={publish_info.rc})")

    def _on_connect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None = None,
    ) -> None:
        if reason_code.is_failure:
            LOGGER.error("MQTT connection failed: %s", reason_code)
            self._connected_event.clear()
            return
        self._connected_event.set()
        LOGGER.info(
            "Connected to MQTT broker at %s:%s",
            self._config.mqtt.host,
            self._config.mqtt.port,
        )
        self._subscribe_events_topic()
        self._subscribe_ha_status_topic()
        self._subscribe_camera_control_topics()

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None = None,
    ) -> None:
        self._connected_event.clear()
        if self._disconnect_requested:
            LOGGER.info("MQTT disconnected cleanly")
            return
        LOGGER.warning("MQTT disconnected unexpectedly: %s; reconnecting", reason_code)

    def _subscribe_events_topic(self) -> None:
        result, _message_id = self._client.subscribe(
            self._events_topic,
            qos=self._config.mqtt.qos,
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            LOGGER.error(
                "Failed to subscribe to topic %s (rc=%s)",
                self._events_topic,
                result,
            )
            return
        LOGGER.info("Subscribed to Frigate events topic: %s", self._events_topic)

    def _subscribe_ha_status_topic(self) -> None:
        if not self._config.mqtt_discovery.enabled:
            return
        result, _message_id = self._client.subscribe(
            self._ha_status_topic,
            qos=self._config.mqtt.qos,
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            LOGGER.warning(
                "Failed to subscribe to HA status topic %s (rc=%s)",
                self._ha_status_topic,
                result,
            )
            return
        LOGGER.info("Subscribed to HA status topic: %s", self._ha_status_topic)

    def _subscribe_camera_control_topics(self) -> None:
        topic = f"{self._config.service.mqtt_prefix}/camera/+/enabled/set"
        result, _message_id = self._client.subscribe(
            topic,
            qos=self._config.mqtt.qos,
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            LOGGER.warning(
                "Failed to subscribe to camera control topic %s (rc=%s)",
                topic,
                result,
            )
            return
        LOGGER.info("Subscribed to camera control topic: %s", topic)

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        if self._handle_camera_control_message(message.topic, message.payload):
            return
        if message.topic == self._ha_status_topic:
            self._handle_ha_status_message(message.payload)
            return
        if message.topic != self._events_topic:
            return
        payload = self._decode_json_payload(message.payload)
        if payload is None:
            return

        event_block = payload.get("after") or payload.get("event") or {}
        if not isinstance(event_block, dict):
            event_block = {}

        event_id = event_block.get("id", "unknown")
        camera = event_block.get("camera", "unknown")
        event_type = payload.get("type", "unknown")
        LOGGER.info(
            "Frigate event received: event_id=%s camera=%s type=%s",
            event_id,
            camera,
            event_type,
        )
        self._evaluate_policy(payload)

    def _handle_camera_control_message(self, topic: str, payload: bytes) -> bool:
        match = self._camera_enabled_set_pattern.match(topic)
        if match is None:
            return False

        camera = match.group(1)
        if camera not in self._config.policy.cameras:
            LOGGER.warning("Ignoring enabled command for unknown camera=%s", camera)
            return True

        raw_value = payload.decode("utf-8", errors="replace").strip().upper()
        if raw_value not in {"ON", "OFF"}:
            LOGGER.warning(
                "Ignoring invalid camera enabled payload camera=%s payload=%s",
                camera,
                raw_value,
            )
            return True

        enabled = raw_value == "ON"
        self._camera_enabled_overrides[camera] = enabled
        topics = self._resolve_camera_topics(camera)
        self._publish_sync(topics["enabled"], "ON" if enabled else "OFF")
        if not enabled:
            self._publish_camera_unknown(camera)
        LOGGER.info("Camera enabled updated camera=%s enabled=%s", camera, enabled)
        return True

    def _handle_ha_status_message(self, payload: bytes) -> None:
        status = payload.decode("utf-8", errors="replace").strip().lower()
        LOGGER.debug("Received HA status payload=%s", status)
        if status == "online":
            LOGGER.info("Home Assistant online detected; republishing discovery configs")
            self._publish_discovery_configs()

    def _decode_json_payload(self, payload_bytes: bytes) -> dict[str, Any] | None:
        try:
            decoded = json.loads(payload_bytes.decode("utf-8"))
        except UnicodeDecodeError:
            LOGGER.warning("Ignoring Frigate event message: invalid UTF-8 payload")
            return None
        except json.JSONDecodeError:
            LOGGER.warning("Ignoring Frigate event message: invalid JSON payload")
            return None

        if not isinstance(decoded, dict):
            LOGGER.warning("Ignoring Frigate event message: payload is not a JSON object")
            return None
        return decoded

    def _evaluate_policy(self, payload: dict[str, Any]) -> None:
        try:
            event = FrigateEvent.from_mqtt_payload(payload)
        except ValidationError as exc:
            LOGGER.warning("Skipping policy evaluation: invalid event payload (%s)", exc)
            return

        if not self._is_camera_enabled_runtime(event.camera):
            LOGGER.info(
                "Event suppressed by camera toggle event_id=%s camera=%s",
                event.event_id,
                event.camera,
            )
            self._publish_camera_unknown(event.camera)
            return

        decision = should_process(
            event=event,
            state=self._policy_runtime_state,
            config=self._config,
        )
        route_result = self._event_router.route(event, decision)
        if route_result.route == "processing":
            self._remember_policy_event(event)
            self._fetch_snapshot_for_event(event)
        elif route_result.reason == "camera_disabled":
            self._publish_camera_unknown(event.camera)

    def _remember_policy_event(self, event: FrigateEvent) -> None:
        events_data = self._policy_runtime_state.setdefault("events", {})
        recent_event_ids = events_data.setdefault("recent_event_ids", [])
        if isinstance(recent_event_ids, list):
            recent_event_ids.append(event.event_id)
            max_ids = max(1, self._config.dedupe.recent_event_ids_max)
            if len(recent_event_ids) > max_ids:
                del recent_event_ids[:-max_ids]

        last_by_camera = events_data.setdefault("last_by_camera", {})
        if isinstance(last_by_camera, dict):
            last_by_camera[event.camera] = {
                "last_event_id": event.event_id,
                "last_event_ts": event.event_ts if event.event_ts is not None else time.time(),
            }
        self._save_policy_state()

    async def _load_policy_state(self) -> None:
        loaded = await asyncio.to_thread(self._state_manager.load_state)
        events_data = loaded.get("events")
        if not isinstance(events_data, dict):
            events_data = {"recent_event_ids": [], "last_by_camera": {}}

        recent_event_ids = events_data.get("recent_event_ids")
        if not isinstance(recent_event_ids, list):
            recent_event_ids = []

        last_by_camera = events_data.get("last_by_camera")
        if not isinstance(last_by_camera, dict):
            last_by_camera = {}

        max_ids = max(1, self._config.dedupe.recent_event_ids_max)
        self._policy_runtime_state = {
            "events": {
                "recent_event_ids": recent_event_ids[-max_ids:],
                "last_by_camera": last_by_camera,
            }
        }
        LOGGER.info(
            "Loaded policy state from %s (recent_event_ids=%s cameras=%s)",
            self._config.state_file,
            len(self._policy_runtime_state["events"]["recent_event_ids"]),
            len(self._policy_runtime_state["events"]["last_by_camera"]),
        )

    def _save_policy_state(self) -> None:
        try:
            self._state_manager.save_state_atomic(self._policy_runtime_state)
        except OSError as exc:
            LOGGER.warning("Failed to persist policy state: %s", exc)

    def _fetch_snapshot_for_event(self, event: FrigateEvent) -> None:
        try:
            snapshot = self._snapshot_manager.fetch_event_snapshot(
                event.event_id,
                camera=event.camera,
            )
        except ExternalServiceError as exc:
            LOGGER.warning(
                "Snapshot fetch failed event_id=%s camera=%s error=%s",
                event.event_id,
                event.camera,
                exc,
            )
            self._publish_camera_result(
                event=event,
                result_status="snapshot_failed",
            )
            return
        LOGGER.info(
            "Snapshot ready event_id=%s camera=%s bytes=%s",
            event.event_id,
            event.camera,
            len(snapshot),
        )
        # Phase 5.1.1: Publish camera state topics before OpenAI is wired in.
        self._publish_camera_result(
            event=event,
            result_status="ok",
            action="unknown",
            confidence_percent=0,
            description="snapshot captured; classification pending",
        )

    def _publish_camera_result(
        self,
        *,
        event: FrigateEvent,
        result_status: str,
        action: str | None = None,
        confidence_percent: int | str | None = None,
        description: str | None = None,
    ) -> None:
        topics = self._resolve_camera_topics(event.camera)
        last_event_ts_iso = self._to_iso_timestamp(event.event_ts)

        # Publish order follows camera_mqtt.md recommendation.
        self._publish_sync(topics["last_event_id"], event.event_id)
        self._publish_sync(topics["last_event_ts"], last_event_ts_iso)
        self._publish_sync(topics["result_status"], result_status)
        if action is not None:
            self._publish_sync(topics["action"], action)
        if confidence_percent is not None:
            self._publish_sync(topics["confidence"], str(confidence_percent))
        if description is not None:
            self._publish_sync(topics["description"], description)

    def _publish_camera_defaults_all(self) -> None:
        for camera in sorted(self._config.policy.cameras.keys()):
            self._publish_camera_enabled_state(camera)
            self._publish_camera_unknown(camera)

    def _publish_core_defaults_unknown(self) -> None:
        topics = self._resolve_core_topics()
        for key, topic in topics.items():
            payload = "unknown"
            if key == "control_enabled":
                payload = "OFF"
            self._publish_sync(topic, payload)

    def _publish_camera_unknown(self, camera: str) -> None:
        topics = self._resolve_camera_topics(camera)
        self._publish_sync(topics["last_event_id"], "unknown")
        self._publish_sync(topics["last_event_ts"], "unknown")
        self._publish_sync(topics["result_status"], "unknown")
        self._publish_sync(topics["action"], "unknown")
        self._publish_sync(topics["confidence"], "unknown")
        self._publish_sync(topics["description"], "unknown")
        self._publish_sync(topics["monthly_cost"], "unknown")

    def _publish_camera_enabled_state(self, camera: str) -> None:
        topics = self._resolve_camera_topics(camera)
        enabled = self._is_camera_enabled_runtime(camera)
        self._publish_sync(topics["enabled"], "ON" if enabled else "OFF")

    def _publish_discovery_configs(self) -> None:
        if not self._config.mqtt_discovery.enabled:
            return
        cameras = sorted(self._config.policy.cameras.keys())
        messages = self._ha_discovery.build_messages(cameras)
        for message in messages:
            self._publish_sync(message.topic, message.payload, retain=True)
        LOGGER.info("Published HA discovery configs count=%s cameras=%s", len(messages), cameras)

    def _resolve_camera_topics(self, camera: str) -> dict[str, str]:
        camera_topics = self._mapping(self._config.topics.get("camera"))
        cost_topics = self._mapping(self._config.topics.get("cost"))
        defaults = {
            "enabled": "{mqtt_prefix}/camera/{camera}/enabled",
            "enabled_set": "{mqtt_prefix}/camera/{camera}/enabled/set",
            "action": "{mqtt_prefix}/camera/{camera}/action",
            "confidence": "{mqtt_prefix}/camera/{camera}/confidence",
            "description": "{mqtt_prefix}/camera/{camera}/description",
            "result_status": "{mqtt_prefix}/camera/{camera}/result_status",
            "last_event_id": "{mqtt_prefix}/camera/{camera}/last_event_id",
            "last_event_ts": "{mqtt_prefix}/camera/{camera}/last_event_ts",
            "monthly_cost": str(
                cost_topics.get(
                    "monthly_by_camera",
                    "{mqtt_prefix}/cost/monthly_by_camera/{camera}",
                )
            ),
        }
        topics: dict[str, str] = {}
        for key, default_template in defaults.items():
            template = str(camera_topics.get(key, default_template))
            if key == "monthly_cost":
                template = default_template
            topics[key] = (
                template.replace("{mqtt_prefix}", self._config.service.mqtt_prefix)
                .replace("{camera}", camera)
            )
        return topics

    def _is_camera_enabled_runtime(self, camera: str) -> bool:
        if camera in self._camera_enabled_overrides:
            return self._camera_enabled_overrides[camera]
        camera_policy = self._config.policy.cameras.get(camera)
        if camera_policy is not None:
            return camera_policy.enabled
        return self._config.policy.defaults.enabled

    def _resolve_core_topics(self) -> dict[str, str]:
        return {
            "cost_last": self._resolve_topic_path("cost.last", "cost/last"),
            "cost_daily_total": self._resolve_topic_path("cost.daily_total", "cost/daily_total"),
            "cost_month2day_total": self._resolve_topic_path("cost.month2day_total", "cost/month2day_total"),
            "cost_avg_per_event": self._resolve_topic_path("cost.avg_per_event", "cost/avg_per_event"),
            "tokens_avg_per_request": self._resolve_topic_path("tokens.avg_per_request", "tokens/avg_per_request"),
            "tokens_avg_per_day": self._resolve_topic_path("tokens.avg_per_day", "tokens/avg_per_day"),
            "events_count_total": self._resolve_topic_path("events.count_total", "events/count_total"),
            "events_count_today": self._resolve_topic_path("events.count_today", "events/count_today"),
            "control_enabled": self._resolve_topic_path("control.enabled", "control/enabled"),
            "control_monthly_budget": self._resolve_topic_path("control.monthly_budget", "control/monthly_budget"),
            "control_confidence_threshold": self._resolve_topic_path("control.confidence_threshold", "control/confidence_threshold"),
        }

    def _resolve_topic_path(self, dotted_key: str, fallback_suffix: str) -> str:
        node: Any = self._config.topics
        for part in dotted_key.split("."):
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(part)
        template = str(node) if isinstance(node, str) else f"{{mqtt_prefix}}/{fallback_suffix}"
        return template.replace("{mqtt_prefix}", self._config.service.mqtt_prefix)

    def _publish_sync(self, topic: str, payload: str, *, retain: bool | None = None) -> None:
        try:
            effective_retain = self._status_retain if retain is None else retain
            LOGGER.debug(
                "MQTT publish sync topic=%s qos=%s retain=%s payload=%s",
                topic,
                self._config.mqtt.qos,
                effective_retain,
                _safe_payload_preview(payload),
            )
            publish_info = self._client.publish(
                topic=topic,
                payload=payload,
                qos=self._config.mqtt.qos,
                retain=effective_retain,
            )
            LOGGER.debug(
                "MQTT publish sync result topic=%s rc=%s mid=%s",
                topic,
                publish_info.rc,
                publish_info.mid,
            )
            if publish_info.rc != mqtt.MQTT_ERR_SUCCESS:
                LOGGER.warning(
                    "MQTT publish failed topic=%s rc=%s payload=%s",
                    topic,
                    publish_info.rc,
                    payload,
                )
        except Exception as exc:
            LOGGER.warning("MQTT publish error topic=%s error=%s", topic, exc)

    def _to_iso_timestamp(self, event_ts: float | None) -> str:
        ts = event_ts if event_ts is not None else time.time()
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    def _mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}

    def _start_heartbeat(self) -> None:
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name="mqtt-heartbeat",
        )

    async def _stop_heartbeat(self) -> None:
        if self._heartbeat_task is None:
            return
        self._heartbeat_task.cancel()
        try:
            await self._heartbeat_task
        except asyncio.CancelledError:
            pass
        self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        interval_seconds = max(5, self._config.mqtt.heartbeat_interval_seconds)
        LOGGER.info(
            "Starting MQTT heartbeat loop (%ss) on topic %s",
            interval_seconds,
            self._heartbeat_topic,
        )
        try:
            while True:
                try:
                    await self.publish_heartbeat()
                    await self.publish_status("enabled")
                except ExternalServiceError as exc:
                    LOGGER.warning("Failed to publish heartbeat/status: %s", exc)
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            LOGGER.info("MQTT heartbeat loop stopped")
            raise


def _resolve_status_topic(config: ServiceConfig) -> str:
    status_template = str(config.topics.get("status", "{mqtt_prefix}/status"))
    return status_template.replace("{mqtt_prefix}", config.service.mqtt_prefix)


def _resolve_heartbeat_topic(config: ServiceConfig) -> str:
    heartbeat_template = str(
        config.topics.get("heartbeat_ts", "{mqtt_prefix}/heartbeat_ts")
    )
    return heartbeat_template.replace("{mqtt_prefix}", config.service.mqtt_prefix)


def _safe_payload_preview(payload: str | bytes | bytearray) -> str:
    if isinstance(payload, str):
        preview = payload
    else:
        try:
            preview = bytes(payload).decode("utf-8", errors="replace")
        except Exception:
            preview = repr(payload)
    if len(preview) > 240:
        return f"{preview[:240]}...(+{len(preview) - 240} chars)"
    return preview
