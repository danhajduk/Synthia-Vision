"""MQTT client wrapper with reconnect and lifecycle helpers."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
import json
import logging
import re
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from src.config import ServiceConfig
from src.db import CameraStore
from src.event_router import EventRouter
from src.ha_discovery import HADiscoveryPublisher
from src.errors import ExternalServiceError, ValidationError
from src.models import FrigateEvent
from src.policy_engine import should_process
from src.openai import (
    OpenAIClient,
    OpenAIUsage,
    apply_outdoor_action_heuristic,
    enforce_classification_result,
)
from src.runtime_controls import (
    EventControlSettings,
    apply_event_controls,
    bool_to_on_off,
    camera_event_controls_from_state,
    controls_from_state,
    parse_on_off,
    parse_updates_per_event,
)
from src.runtime import (
    DEGRADE_HIGH_WATERMARK,
    DEGRADE_LOW_WATERMARK,
    DEGRADE_SUSTAIN_SECONDS,
    EVENT_QUEUE_MAX_SIZE,
)
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
        self._last_error_topic = _resolve_last_error_topic(config)
        self._events_topic = config.mqtt.events_topic
        self._ha_status_topic = f"{config.mqtt_discovery.prefix}/status"
        self._control_set_pattern = re.compile(
            rf"^{re.escape(self._config.service.mqtt_prefix)}/control/([^/]+)/set$"
        )
        self._camera_control_set_pattern = re.compile(
            rf"^{re.escape(self._config.service.mqtt_prefix)}/camera/([^/]+)/([^/]+)/set$"
        )
        self._status_retain = config.mqtt.retain
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._queue_worker_task: asyncio.Task[None] | None = None
        self._degraded_monitor_task: asyncio.Task[None] | None = None
        self._queue_event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event_queue: deque[FrigateEvent] = deque(maxlen=EVENT_QUEUE_MAX_SIZE)
        self._event_queue_lock = threading.Lock()
        self._stop_requested = False
        self._is_degraded = False
        self._above_high_since: float | None = None
        self._dropped_events_total = 0
        self._dropped_update_total = 0
        self._dropped_queue_full_total = 0
        self._state_manager = StateManager(config.state_file)
        self._camera_store = CameraStore(config.paths.db_file)
        self._snapshot_manager = SnapshotManager(config)
        self._openai_client: OpenAIClient | None = None
        try:
            self._openai_client = OpenAIClient(config)
        except ExternalServiceError as exc:
            LOGGER.warning("OpenAI client unavailable at startup: %s", exc)
        self._ha_discovery = HADiscoveryPublisher(config)
        self._event_router = EventRouter()
        self._policy_runtime_state: dict[str, Any] = {
            "controls": {
                "enabled": True,
                "monthly_budget": float(self._config.budget.monthly_budget_limit),
                "confidence_threshold": int(round(self._config.policy.defaults.confidence_threshold * 100)),
                "doorbell_only_mode": bool(self._config.modes.doorbell_only_mode.enabled),
                "high_precision_mode": bool(self._config.modes.high_precision_mode.enabled),
                "updates_per_event": 1,
                "camera_event_processing": {},
            },
            "metrics": {
                "count_total": 0,
                "count_today": 0,
                "count_today_date": datetime.now().date().isoformat(),
                "count_month_key": datetime.now().strftime("%Y-%m"),
                "cost_last": 0.0,
                "cost_daily_total": 0.0,
                "cost_month2day_total": 0.0,
                "cost_monthly_by_camera": {},
                "cost_avg_per_event": 0.0,
                "tokens_avg_per_request": 0.0,
                "tokens_avg_per_day": 0.0,
            },
            "events": {
                "recent_event_ids": [],
                "last_by_camera": {},
            }
        }
        self._event_controls = EventControlSettings()
        self._runtime_metrics: dict[str, Any] = {}
        self._service_enabled: bool = True
        self._monthly_budget_limit: float = float(self._config.budget.monthly_budget_limit)
        self._confidence_threshold_percent: int = int(
            round(self._config.policy.defaults.confidence_threshold * 100)
        )
        self._process_end_events_by_camera: dict[str, bool] = {}
        self._process_update_events_by_camera: dict[str, bool] = {}
        self._updates_processed_count: dict[str, int] = {}
        self._updates_last_seen_ts: dict[str, float] = {}
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
        self._loop = asyncio.get_running_loop()
        await self._load_policy_state()
        self._disconnect_requested = False
        self._stop_requested = False
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
        self._publish_global_metrics()
        self._start_queue_worker()
        await self.publish_status(self._effective_runtime_status())
        self._start_heartbeat()
        LOGGER.info("MQTT ready status published")

    async def shutdown(self) -> None:
        """Graceful shutdown with final retained status publication."""
        self._disconnect_requested = True
        self._stop_requested = True
        await self._stop_queue_worker()
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
        self._subscribe_control_topics()
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
        topic = f"{self._config.service.mqtt_prefix}/camera/+/+/set"
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

    def _subscribe_control_topics(self) -> None:
        topic = f"{self._config.service.mqtt_prefix}/control/+/set"
        result, _message_id = self._client.subscribe(
            topic,
            qos=self._config.mqtt.qos,
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            LOGGER.warning(
                "Failed to subscribe to core control topic %s (rc=%s)",
                topic,
                result,
            )
            return
        LOGGER.info("Subscribed to core control topic: %s", topic)

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        if self._handle_core_control_message(message.topic, message.payload):
            return
        if self._handle_camera_control_message(message.topic, message.payload):
            return
        if message.topic == self._ha_status_topic:
            self._handle_ha_status_message(message.payload)
            return
        if message.topic != self._events_topic:
            return
        event = self._decode_event_payload(message.payload)
        if event is None:
            return
        LOGGER.info(
            "Frigate event received: event_id=%s camera=%s type=%s",
            event.event_id,
            event.camera,
            event.event_type,
        )
        self._enqueue_event_from_callback(event)

    def _handle_core_control_message(self, topic: str, payload: bytes) -> bool:
        match = self._control_set_pattern.match(topic)
        if match is None:
            return False

        key = match.group(1)
        raw_value = payload.decode("utf-8", errors="replace").strip()
        topics = self._resolve_core_topics()

        if key == "enabled":
            parsed = parse_on_off(raw_value)
            if parsed is None:
                LOGGER.warning("Ignoring invalid enabled payload=%s", raw_value)
                self._publish_last_error(f"invalid enabled payload: {raw_value}")
                return True
            self._service_enabled = parsed
            self._publish_sync(topics["control_enabled"], bool_to_on_off(parsed))
            self._persist_runtime_controls()
            LOGGER.info("Updated service enabled=%s", parsed)
            return True

        if key == "monthly_budget":
            parsed_budget = _parse_monthly_budget(raw_value)
            if parsed_budget is None:
                LOGGER.warning("Ignoring invalid monthly_budget payload=%s", raw_value)
                self._publish_last_error(f"invalid monthly_budget payload: {raw_value}")
                return True
            self._monthly_budget_limit = parsed_budget
            self._config.budget.monthly_budget_limit = parsed_budget
            self._publish_sync(topics["control_monthly_budget"], f"{parsed_budget:.2f}")
            self._publish_sync(self._status_topic, self._effective_runtime_status())
            self._persist_runtime_controls()
            LOGGER.info("Updated monthly_budget=%s", parsed_budget)
            return True

        if key == "confidence_threshold":
            parsed_threshold = _parse_confidence_threshold(raw_value)
            if parsed_threshold is None:
                LOGGER.warning("Ignoring invalid confidence_threshold payload=%s", raw_value)
                self._publish_last_error(f"invalid confidence_threshold payload: {raw_value}")
                return True
            self._confidence_threshold_percent = parsed_threshold
            self._config.policy.defaults.confidence_threshold = parsed_threshold / 100.0
            self._publish_sync(topics["control_confidence_threshold"], str(parsed_threshold))
            self._persist_runtime_controls()
            LOGGER.info("Updated confidence_threshold_percent=%s", parsed_threshold)
            return True

        if key == "doorbell_only_mode":
            parsed = parse_on_off(raw_value)
            if parsed is None:
                LOGGER.warning("Ignoring invalid doorbell_only_mode payload=%s", raw_value)
                self._publish_last_error(f"invalid doorbell_only_mode payload: {raw_value}")
                return True
            self._config.modes.doorbell_only_mode.enabled = parsed
            self._publish_sync(topics["control_doorbell_only_mode"], bool_to_on_off(parsed))
            self._persist_runtime_controls()
            LOGGER.info("Updated doorbell_only_mode=%s", parsed)
            return True

        if key == "high_precision_mode":
            parsed = parse_on_off(raw_value)
            if parsed is None:
                LOGGER.warning("Ignoring invalid high_precision_mode payload=%s", raw_value)
                self._publish_last_error(f"invalid high_precision_mode payload: {raw_value}")
                return True
            self._config.modes.high_precision_mode.enabled = parsed
            self._publish_sync(topics["control_high_precision_mode"], bool_to_on_off(parsed))
            self._persist_runtime_controls()
            LOGGER.info("Updated high_precision_mode=%s", parsed)
            return True

        if key == "updates_per_event":
            parsed_int = parse_updates_per_event(raw_value)
            if parsed_int is None:
                LOGGER.warning("Ignoring invalid updates_per_event payload=%s", raw_value)
                self._publish_last_error(f"invalid updates_per_event payload: {raw_value}")
                return True
            self._event_controls.updates_per_event = parsed_int
            self._publish_sync(topics["control_updates_per_event"], str(parsed_int))
            self._persist_runtime_controls()
            LOGGER.info("Updated updates_per_event=%s", parsed_int)
            return True

        return False

    def _handle_camera_control_message(self, topic: str, payload: bytes) -> bool:
        match = self._camera_control_set_pattern.match(topic)
        if match is None:
            return False

        camera = match.group(1)
        key = match.group(2)

        raw_value = payload.decode("utf-8", errors="replace").strip()
        topics = self._resolve_camera_topics(camera)
        if key == "enabled":
            parsed = parse_on_off(raw_value)
            if parsed is None:
                LOGGER.warning(
                    "Ignoring invalid camera enabled payload camera=%s payload=%s",
                    camera,
                    raw_value,
                )
                self._publish_last_error(
                    f"invalid camera enabled payload camera={camera} payload={raw_value}"
                )
                return True
            self._camera_enabled_overrides[camera] = parsed
            try:
                self._camera_store.set_camera_enabled(camera, parsed)
            except Exception as exc:
                LOGGER.warning("Failed to persist camera enabled camera=%s error=%s", camera, exc)
            self._publish_sync(topics["enabled"], bool_to_on_off(parsed))
            if not parsed:
                self._publish_camera_unknown(camera)
            LOGGER.info("Camera enabled updated camera=%s enabled=%s", camera, parsed)
            return True

        if key == "process_end_events":
            parsed = parse_on_off(raw_value)
            if parsed is None:
                LOGGER.warning(
                    "Ignoring invalid camera process_end_events payload camera=%s payload=%s",
                    camera,
                    raw_value,
                )
                self._publish_last_error(
                    f"invalid camera process_end_events payload camera={camera} payload={raw_value}"
                )
                return True
            self._process_end_events_by_camera[camera] = parsed
            try:
                self._camera_store.set_camera_event_controls(
                    camera,
                    process_end_events=parsed,
                )
            except Exception as exc:
                LOGGER.warning("Failed to persist process_end_events camera=%s error=%s", camera, exc)
            self._publish_sync(topics["process_end_events"], bool_to_on_off(parsed))
            self._persist_runtime_controls()
            LOGGER.info("Camera process_end_events updated camera=%s enabled=%s", camera, parsed)
            return True

        if key == "process_update_events":
            parsed = parse_on_off(raw_value)
            if parsed is None:
                LOGGER.warning(
                    "Ignoring invalid camera process_update_events payload camera=%s payload=%s",
                    camera,
                    raw_value,
                )
                self._publish_last_error(
                    f"invalid camera process_update_events payload camera={camera} payload={raw_value}"
                )
                return True
            self._process_update_events_by_camera[camera] = parsed
            try:
                self._camera_store.set_camera_event_controls(
                    camera,
                    process_update_events=parsed,
                )
            except Exception as exc:
                LOGGER.warning("Failed to persist process_update_events camera=%s error=%s", camera, exc)
            self._publish_sync(topics["process_update_events"], bool_to_on_off(parsed))
            self._persist_runtime_controls()
            LOGGER.info(
                "Camera process_update_events updated camera=%s enabled=%s",
                camera,
                parsed,
            )
            return True

        return False

    def _handle_ha_status_message(self, payload: bytes) -> None:
        status = payload.decode("utf-8", errors="replace").strip().lower()
        LOGGER.debug("Received HA status payload=%s", status)
        if status == "online":
            LOGGER.info("Home Assistant online detected; republishing discovery configs")
            self._publish_discovery_configs()

    def _decode_event_payload(self, payload_bytes: bytes) -> FrigateEvent | None:
        try:
            decoded = json.loads(payload_bytes.decode("utf-8"))
        except UnicodeDecodeError:
            LOGGER.warning("Ignoring Frigate event message: invalid UTF-8 payload")
            self._publish_last_error("frigate event invalid UTF-8 payload")
            return None
        except json.JSONDecodeError:
            LOGGER.warning("Ignoring Frigate event message: invalid JSON payload")
            self._publish_last_error("frigate event invalid JSON payload")
            return None

        if not isinstance(decoded, dict):
            LOGGER.warning("Ignoring Frigate event message: payload is not a JSON object")
            self._publish_last_error("frigate event payload is not JSON object")
            return None
        try:
            return FrigateEvent.from_mqtt_payload(decoded)
        except ValidationError as exc:
            LOGGER.warning("Skipping policy evaluation: invalid event payload (%s)", exc)
            self._publish_last_error(f"invalid event payload: {exc}")
            return None

    def _enqueue_event_from_callback(self, event: FrigateEvent) -> None:
        event_type = event.event_type.strip().lower()
        with self._event_queue_lock:
            queue_len = len(self._event_queue)
            if queue_len >= EVENT_QUEUE_MAX_SIZE:
                if event_type == "update":
                    self._dropped_events_total += 1
                    self._dropped_update_total += 1
                    self._sync_queue_stats_to_db()
                    LOGGER.warning(
                        "Dropped incoming update due to full queue event_id=%s camera=%s depth=%s",
                        event.event_id,
                        event.camera,
                        queue_len,
                    )
                    return
                if self._event_queue:
                    dropped = self._event_queue.popleft()
                    self._dropped_events_total += 1
                    self._dropped_queue_full_total += 1
                    self._sync_queue_stats_to_db()
                    LOGGER.warning(
                        "Dropped oldest event due to full queue dropped_event_id=%s dropped_camera=%s depth=%s",
                        dropped.event_id,
                        dropped.camera,
                        queue_len,
                    )
            self._event_queue.append(event)
            queue_depth = len(self._event_queue)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._queue_event.set)
        self._sync_queue_depth_to_db(queue_depth)

    def _evaluate_policy(self, event: FrigateEvent) -> None:
        self._upsert_discovered_camera(event)
        camera_runtime = self._resolve_camera_runtime_settings(event.camera)

        if not self._service_enabled:
            LOGGER.info(
                "Event suppressed by service enabled toggle event_id=%s camera=%s",
                event.event_id,
                event.camera,
            )
            self._publish_camera_status_only(event=event, result_status="skipped")
            return

        gate = apply_event_controls(
            event_id=f"{event.camera}:{event.event_id}",
            event_type=event.event_type,
            settings=EventControlSettings(
                process_end_events=camera_runtime.process_end_events,
                process_update_events=camera_runtime.process_update_events,
                updates_per_event=camera_runtime.updates_per_event,
                update_ttl_seconds=self._event_controls.update_ttl_seconds,
            ),
            updates_processed_count=self._updates_processed_count,
            last_seen_ts=self._updates_last_seen_ts,
            event_ts=event.event_ts,
        )
        if not gate.allow:
            LOGGER.info(
                "Event suppressed by core controls event_id=%s camera=%s event_type=%s reason=%s",
                event.event_id,
                event.camera,
                event.event_type,
                gate.reason,
            )
            self._publish_camera_status_only(event=event, result_status="suppressed")
            return

        if not camera_runtime.enabled:
            LOGGER.info(
                "Event suppressed by camera toggle event_id=%s camera=%s",
                event.event_id,
                event.camera,
            )
            self._publish_camera_status_only(event=event, result_status="skipped")
            return

        decision = should_process(
            event=event,
            state=self._policy_runtime_state,
            config=self._config,
        )
        route_result = self._event_router.route(event, decision)
        if route_result.route == "processing":
            self._record_processed_event_metrics()
            self._remember_policy_event(event)
            self._fetch_snapshot_for_event(event)
            return

        self._publish_camera_status_only(event=event, result_status="skipped")

    async def _queue_worker_loop(self) -> None:
        LOGGER.info("Started event queue worker max_size=%s", EVENT_QUEUE_MAX_SIZE)
        while not self._stop_requested:
            event: FrigateEvent | None = None
            with self._event_queue_lock:
                if self._event_queue:
                    event = self._event_queue.popleft()
                else:
                    self._queue_event.clear()
            if event is None:
                try:
                    await asyncio.wait_for(self._queue_event.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                continue
            try:
                self._evaluate_policy(event)
            except Exception:
                LOGGER.exception(
                    "Unhandled event processing failure event_id=%s camera=%s",
                    event.event_id,
                    event.camera,
                )
        LOGGER.info("Event queue worker stopped")

    async def _degraded_monitor_loop(self) -> None:
        LOGGER.info(
            "Started degraded monitor high=%s low=%s sustain_s=%s",
            DEGRADE_HIGH_WATERMARK,
            DEGRADE_LOW_WATERMARK,
            DEGRADE_SUSTAIN_SECONDS,
        )
        while not self._stop_requested:
            depth = self._queue_depth()
            now = time.monotonic()
            if depth > DEGRADE_HIGH_WATERMARK:
                if self._above_high_since is None:
                    self._above_high_since = now
                elif not self._is_degraded and (now - self._above_high_since) >= DEGRADE_SUSTAIN_SECONDS:
                    self._is_degraded = True
                    self._publish_sync(self._status_topic, "degraded")
                    LOGGER.warning(
                        "Runtime degraded due to queue pressure depth=%s dropped_total=%s dropped_update=%s dropped_oldest=%s",
                        depth,
                        self._dropped_events_total,
                        self._dropped_update_total,
                        self._dropped_queue_full_total,
                    )
            elif depth < DEGRADE_LOW_WATERMARK:
                self._above_high_since = None
                if self._is_degraded:
                    self._is_degraded = False
                    self._publish_sync(self._status_topic, self._effective_runtime_status())
                    LOGGER.info("Runtime recovered from degraded mode depth=%s", depth)
            await asyncio.sleep(1.0)
        LOGGER.info("Degraded monitor stopped")

    def _queue_depth(self) -> int:
        with self._event_queue_lock:
            return len(self._event_queue)

    def _start_queue_worker(self) -> None:
        if self._queue_worker_task is None or self._queue_worker_task.done():
            self._queue_worker_task = asyncio.create_task(
                self._queue_worker_loop(),
                name="event-queue-worker",
            )
        if self._degraded_monitor_task is None or self._degraded_monitor_task.done():
            self._degraded_monitor_task = asyncio.create_task(
                self._degraded_monitor_loop(),
                name="degraded-monitor",
            )

    async def _stop_queue_worker(self) -> None:
        self._queue_event.set()
        if self._queue_worker_task is not None:
            self._queue_worker_task.cancel()
            try:
                await self._queue_worker_task
            except asyncio.CancelledError:
                pass
            self._queue_worker_task = None
        if self._degraded_monitor_task is not None:
            self._degraded_monitor_task.cancel()
            try:
                await self._degraded_monitor_task
            except asyncio.CancelledError:
                pass
            self._degraded_monitor_task = None

    def _resolve_camera_runtime_settings(self, camera: str):
        try:
            return self._camera_store.get_runtime_settings(
                camera,
                default_process_end_events=self._process_end_events_by_camera.get(camera, True),
                default_process_update_events=self._process_update_events_by_camera.get(
                    camera,
                    False,
                ),
                default_updates_per_event=self._event_controls.updates_per_event,
            )
        except Exception as exc:
            LOGGER.warning("Camera runtime settings lookup failed camera=%s error=%s", camera, exc)
            from types import SimpleNamespace

            return SimpleNamespace(
                enabled=False,
                process_end_events=self._process_end_events_by_camera.get(camera, True),
                process_update_events=self._process_update_events_by_camera.get(camera, False),
                updates_per_event=self._event_controls.updates_per_event,
            )

    def _remember_policy_event(self, event: FrigateEvent) -> None:
        events_data = self._policy_runtime_state.setdefault("events", {})
        recent_event_ids = events_data.setdefault("recent_event_ids", [])
        if isinstance(recent_event_ids, list) and event.event_type.lower() == "end":
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

        metrics_data = loaded.get("metrics")
        if not isinstance(metrics_data, dict):
            metrics_data = {}
        today_key = datetime.now().date().isoformat()
        loaded_metrics = {
            "count_total": int(metrics_data.get("count_total", 0)),
            "count_today": int(metrics_data.get("count_today", 0)),
            "count_today_date": str(metrics_data.get("count_today_date", today_key)),
            "count_month_key": str(metrics_data.get("count_month_key", datetime.now().strftime("%Y-%m"))),
            "cost_last": float(metrics_data.get("cost_last", 0.0)),
            "cost_daily_total": float(metrics_data.get("cost_daily_total", 0.0)),
            "cost_month2day_total": float(metrics_data.get("cost_month2day_total", 0.0)),
            "cost_monthly_by_camera": {},
            "cost_avg_per_event": float(metrics_data.get("cost_avg_per_event", 0.0)),
            "tokens_avg_per_request": float(metrics_data.get("tokens_avg_per_request", 0.0)),
            "tokens_avg_per_day": float(metrics_data.get("tokens_avg_per_day", 0.0)),
        }
        raw_by_camera = metrics_data.get("cost_monthly_by_camera")
        if isinstance(raw_by_camera, dict):
            loaded_metrics["cost_monthly_by_camera"] = {
                str(camera): float(amount) for camera, amount in raw_by_camera.items()
            }
        self._apply_metric_rollovers(loaded_metrics)

        max_ids = max(1, self._config.dedupe.recent_event_ids_max)
        loaded_controls = controls_from_state(loaded)
        self._event_controls = loaded_controls
        self._runtime_metrics = loaded_metrics
        controls_data = loaded.get("controls")
        if not isinstance(controls_data, dict):
            controls_data = {}

        self._service_enabled = bool(controls_data.get("enabled", True))
        self._monthly_budget_limit = float(
            controls_data.get("monthly_budget", self._config.budget.monthly_budget_limit)
        )
        self._config.budget.monthly_budget_limit = self._monthly_budget_limit
        self._confidence_threshold_percent = int(
            controls_data.get(
                "confidence_threshold",
                round(self._config.policy.defaults.confidence_threshold * 100),
            )
        )
        self._confidence_threshold_percent = max(0, min(100, self._confidence_threshold_percent))
        self._config.policy.defaults.confidence_threshold = (
            self._confidence_threshold_percent / 100.0
        )
        self._config.modes.doorbell_only_mode.enabled = bool(
            controls_data.get("doorbell_only_mode", self._config.modes.doorbell_only_mode.enabled)
        )
        self._config.modes.high_precision_mode.enabled = bool(
            controls_data.get("high_precision_mode", self._config.modes.high_precision_mode.enabled)
        )
        loaded_camera_controls: dict[str, dict[str, bool]] = {}
        for camera in self._config.policy.cameras:
            process_end_events, process_update_events = camera_event_controls_from_state(
                loaded,
                camera,
                default_process_end_events=loaded_controls.process_end_events,
                default_process_update_events=loaded_controls.process_update_events,
            )
            self._process_end_events_by_camera[camera] = process_end_events
            self._process_update_events_by_camera[camera] = process_update_events
            loaded_camera_controls[camera] = {
                "process_end_events": process_end_events,
                "process_update_events": process_update_events,
            }
        self._policy_runtime_state = {
            "controls": {
                "enabled": self._service_enabled,
                "monthly_budget": self._monthly_budget_limit,
                "confidence_threshold": self._confidence_threshold_percent,
                "doorbell_only_mode": self._config.modes.doorbell_only_mode.enabled,
                "high_precision_mode": self._config.modes.high_precision_mode.enabled,
                "updates_per_event": loaded_controls.updates_per_event,
                "camera_event_processing": loaded_camera_controls,
            },
            "metrics": loaded_metrics,
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
        if self._is_budget_blocked():
            self._publish_sync(self._status_topic, "budget_blocked")
            self._publish_last_error(
                f"budget_blocked camera={event.camera} event_id={event.event_id}"
            )
            self._publish_camera_result(
                event=event,
                result_status="blocked_budget",
                action="unknown",
                subject_type="unknown",
                confidence_percent="unknown",
                description="blocked: monthly budget exceeded",
            )
            return
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
            self._publish_last_error(f"snapshot_failed camera={event.camera} event_id={event.event_id}: {exc}")
            self._publish_camera_result(
                event=event,
                result_status="snapshot_failed",
                action="unknown",
                subject_type="unknown",
                confidence_percent="unknown",
                description="snapshot fetch failed",
            )
            return
        LOGGER.info(
            "Snapshot ready event_id=%s camera=%s bytes=%s",
            event.event_id,
            event.camera,
            len(snapshot),
        )
        if self._openai_client is None:
            self._publish_last_error(
                f"openai_failed camera={event.camera} event_id={event.event_id}: openai client unavailable"
            )
            self._publish_camera_result(
                event=event,
                result_status="openai_failed",
                action="unknown",
                subject_type="unknown",
                confidence_percent="unknown",
                description="openai client unavailable",
            )
            return
        try:
            classification, usage = self._openai_client.classify(
                snapshot_bytes=snapshot,
                camera_name=event.camera,
                bbox=event.bbox,
            )
        except ValidationError as exc:
            LOGGER.warning(
                "OpenAI schema validation failed event_id=%s camera=%s error=%s",
                event.event_id,
                event.camera,
                exc,
            )
            self._publish_last_error(
                f"schema_failed camera={event.camera} event_id={event.event_id}: {exc}"
            )
            self._publish_camera_result(
                event=event,
                result_status="schema_failed",
                action="unknown",
                subject_type="unknown",
                confidence_percent="unknown",
                description="classification schema validation failed",
            )
            return
        except ExternalServiceError as exc:
            LOGGER.warning(
                "OpenAI classification failed event_id=%s camera=%s error=%s",
                event.event_id,
                event.camera,
                exc,
            )
            self._publish_last_error(
                f"openai_failed camera={event.camera} event_id={event.event_id}: {exc}"
            )
            self._publish_camera_result(
                event=event,
                result_status="openai_failed",
                action="unknown",
                subject_type="unknown",
                confidence_percent="unknown",
                description="classification failed",
            )
            return
        if usage.total_tokens > 8000:
            LOGGER.warning(
                "Token budget exceeded event_id=%s camera=%s total_tokens=%s detail=%s dims=%sx%s image_bytes=%s; retrying with low-budget mode",
                event.event_id,
                event.camera,
                usage.total_tokens,
                usage.vision_detail,
                usage.processed_size[0],
                usage.processed_size[1],
                usage.image_bytes,
            )
            try:
                classification, usage = self._openai_client.classify(
                    snapshot_bytes=snapshot,
                    camera_name=event.camera,
                    bbox=event.bbox,
                    force_low_budget=True,
                )
            except (ValidationError, ExternalServiceError) as exc:
                self._publish_last_error(
                    f"token_budget_exceeded camera={event.camera} event_id={event.event_id}: {exc}"
                )
                self._publish_camera_result(
                    event=event,
                    result_status="token_budget_exceeded",
                    action="unknown",
                    subject_type="unknown",
                    confidence_percent="unknown",
                    description="token budget exceeded",
                )
                return
            if usage.total_tokens > 8000:
                self._publish_last_error(
                    f"token_budget_exceeded camera={event.camera} event_id={event.event_id} total_tokens={usage.total_tokens}"
                )
                self._publish_camera_result(
                    event=event,
                    result_status="token_budget_exceeded",
                    action="unknown",
                    subject_type="unknown",
                    confidence_percent="unknown",
                    description="token budget exceeded",
                )
                return

        confidence_percent = max(0, min(100, int(round(classification.confidence * 100.0))))
        action = apply_outdoor_action_heuristic(
            event=event,
            action=classification.action,
            config=self._config,
        )
        self._publish_camera_result(
            event=event,
            result_status="ok",
            action=action,
            subject_type=classification.subject_type,
            confidence_percent=confidence_percent,
            description=classification.description,
        )
        self._record_openai_usage_metrics(usage=usage, camera=event.camera)

    def _publish_camera_result(
        self,
        *,
        event: FrigateEvent,
        result_status: str,
        action: str | None = None,
        subject_type: str | None = None,
        confidence_percent: int | str | None = None,
        description: str | None = None,
    ) -> None:
        topics = self._resolve_camera_topics(event.camera)
        last_event_ts_iso = self._to_iso_timestamp(event.event_ts)

        effective_status = result_status
        effective_action = action
        effective_subject_type = subject_type
        effective_description = description
        if action is not None or subject_type is not None or description is not None:
            enforced_action, enforced_subject_type, enforced_description, enforce_status = (
                enforce_classification_result(
                    action=action or self._config.policy.actions.default_action,
                    subject_type=subject_type or self._config.policy.subject_types.default,
                    description=description or "",
                    camera=event.camera,
                    config=self._config,
                )
            )
            effective_action = enforced_action
            effective_subject_type = enforced_subject_type
            effective_description = enforced_description
            if enforce_status != "ok":
                effective_status = enforce_status

        # Publish order follows camera_mqtt.md recommendation.
        self._publish_sync(topics["last_event_id"], event.event_id)
        self._publish_sync(topics["last_event_ts"], last_event_ts_iso)
        self._publish_sync(topics["result_status"], effective_status)
        if effective_action is not None:
            self._publish_sync(topics["action"], effective_action)
        if effective_subject_type is not None:
            self._publish_sync(topics["subject_type"], effective_subject_type)
        if confidence_percent is not None:
            self._publish_sync(topics["confidence"], str(confidence_percent))
        if effective_description is not None:
            self._publish_sync(topics["description"], effective_description)

    def _publish_camera_status_only(self, *, event: FrigateEvent, result_status: str) -> None:
        topics = self._resolve_camera_topics(event.camera)
        last_event_ts_iso = self._to_iso_timestamp(event.event_ts)
        self._publish_sync(topics["last_event_id"], event.event_id)
        self._publish_sync(topics["last_event_ts"], last_event_ts_iso)
        self._publish_sync(topics["result_status"], result_status)

    def _publish_camera_defaults_all(self) -> None:
        for camera in sorted(self._config.policy.cameras.keys()):
            self._publish_camera_enabled_state(camera)
            self._publish_camera_event_control_states(camera)
            self._publish_camera_unknown(camera)
            self._publish_camera_monthly_cost(camera)

    def _publish_core_defaults_unknown(self) -> None:
        topics = self._resolve_core_topics()
        explicit_defaults = {
            "control_enabled": bool_to_on_off(self._service_enabled),
            "control_monthly_budget": f"{self._monthly_budget_limit:.2f}",
            "control_confidence_threshold": str(self._confidence_threshold_percent),
            "control_doorbell_only_mode": bool_to_on_off(
                self._config.modes.doorbell_only_mode.enabled
            ),
            "control_high_precision_mode": bool_to_on_off(
                self._config.modes.high_precision_mode.enabled
            ),
            "control_updates_per_event": str(self._event_controls.updates_per_event),
        }
        for key, topic in topics.items():
            self._publish_sync(topic, explicit_defaults.get(key, "unknown"))

    def _effective_runtime_status(self) -> str:
        if self._is_budget_blocked():
            return "budget_blocked"
        if self._is_degraded:
            return "degraded"
        return "enabled"

    def _publish_global_metrics(self) -> None:
        topics = self._resolve_core_topics()
        self._publish_sync(topics["events_count_total"], str(int(self._runtime_metrics.get("count_total", 0))))
        self._publish_sync(topics["events_count_today"], str(int(self._runtime_metrics.get("count_today", 0))))
        self._publish_sync(topics["cost_last"], f"{float(self._runtime_metrics.get('cost_last', 0.0)):.4f}")
        self._publish_sync(
            topics["cost_daily_total"],
            f"{float(self._runtime_metrics.get('cost_daily_total', 0.0)):.4f}",
        )
        self._publish_sync(
            topics["cost_month2day_total"],
            f"{float(self._runtime_metrics.get('cost_month2day_total', 0.0)):.4f}",
        )
        self._publish_sync(
            topics["cost_avg_per_event"],
            f"{float(self._runtime_metrics.get('cost_avg_per_event', 0.0)):.4f}",
        )
        self._publish_sync(
            topics["tokens_avg_per_request"],
            f"{float(self._runtime_metrics.get('tokens_avg_per_request', 0.0)):.2f}",
        )
        self._publish_sync(
            topics["tokens_avg_per_day"],
            f"{float(self._runtime_metrics.get('tokens_avg_per_day', 0.0)):.2f}",
        )

    def _record_processed_event_metrics(self) -> None:
        self._apply_metric_rollovers(self._runtime_metrics)

        self._runtime_metrics["count_total"] = int(self._runtime_metrics.get("count_total", 0)) + 1
        self._runtime_metrics["count_today"] = int(self._runtime_metrics.get("count_today", 0)) + 1

        count_total = max(1, int(self._runtime_metrics["count_total"]))
        month_total = float(self._runtime_metrics.get("cost_month2day_total", 0.0))
        self._runtime_metrics["cost_avg_per_event"] = month_total / float(count_total)

        self._policy_runtime_state["metrics"] = dict(self._runtime_metrics)
        self._save_policy_state()
        self._publish_global_metrics()

    def _record_openai_usage_metrics(self, *, usage: OpenAIUsage, camera: str) -> None:
        self._apply_metric_rollovers(self._runtime_metrics)

        self._runtime_metrics["cost_last"] = float(usage.cost_usd)
        self._runtime_metrics["cost_daily_total"] = float(
            self._runtime_metrics.get("cost_daily_total", 0.0)
        ) + float(usage.cost_usd)
        self._runtime_metrics["cost_month2day_total"] = float(
            self._runtime_metrics.get("cost_month2day_total", 0.0)
        ) + float(usage.cost_usd)

        camera_costs = self._runtime_metrics.get("cost_monthly_by_camera")
        if not isinstance(camera_costs, dict):
            camera_costs = {}
            self._runtime_metrics["cost_monthly_by_camera"] = camera_costs
        camera_costs[camera] = float(camera_costs.get(camera, 0.0)) + float(usage.cost_usd)

        count_total = max(1, int(self._runtime_metrics.get("count_total", 0)))
        self._runtime_metrics["cost_avg_per_event"] = float(
            self._runtime_metrics.get("cost_month2day_total", 0.0)
        ) / float(count_total)

        previous_avg = float(self._runtime_metrics.get("tokens_avg_per_request", 0.0))
        self._runtime_metrics["tokens_avg_per_request"] = (
            (previous_avg * float(count_total - 1)) + float(usage.total_tokens)
        ) / float(count_total)
        count_today = max(1, int(self._runtime_metrics.get("count_today", 0)))
        self._runtime_metrics["tokens_avg_per_day"] = (
            self._runtime_metrics["tokens_avg_per_request"] * float(count_today)
        )

        self._policy_runtime_state["metrics"] = dict(self._runtime_metrics)
        self._save_policy_state()
        self._publish_global_metrics()
        self._publish_camera_monthly_cost(camera)
        self._publish_sync(self._status_topic, self._effective_runtime_status())

    def _is_budget_blocked(self) -> bool:
        if not self._config.budget.enabled:
            return False
        month_total = float(self._runtime_metrics.get("cost_month2day_total", 0.0))
        return month_total >= float(self._monthly_budget_limit)

    def _apply_metric_rollovers(self, metrics: dict[str, Any]) -> None:
        today_key = datetime.now().date().isoformat()
        month_key = datetime.now().strftime("%Y-%m")
        if str(metrics.get("count_today_date", today_key)) != today_key:
            metrics["count_today"] = 0
            metrics["count_today_date"] = today_key
            metrics["cost_daily_total"] = 0.0
        if str(metrics.get("count_month_key", month_key)) != month_key:
            metrics["count_month_key"] = month_key
            metrics["cost_month2day_total"] = 0.0
            metrics["cost_monthly_by_camera"] = {}

    def _publish_camera_unknown(self, camera: str) -> None:
        topics = self._resolve_camera_topics(camera)
        self._publish_sync(topics["last_event_id"], "unknown")
        self._publish_sync(topics["last_event_ts"], "unknown")
        self._publish_sync(topics["result_status"], "waiting")
        self._publish_sync(topics["action"], "waiting")
        self._publish_sync(topics["subject_type"], "unknown")
        self._publish_sync(topics["confidence"], "unknown")
        self._publish_sync(topics["description"], "waiting for event")
        self._publish_sync(topics["monthly_cost"], "unknown")

    def _publish_camera_monthly_cost(self, camera: str) -> None:
        topics = self._resolve_camera_topics(camera)
        camera_costs = self._runtime_metrics.get("cost_monthly_by_camera", {})
        if not isinstance(camera_costs, dict):
            self._publish_sync(topics["monthly_cost"], "unknown")
            return
        self._publish_sync(topics["monthly_cost"], f"{float(camera_costs.get(camera, 0.0)):.4f}")

    def _publish_camera_enabled_state(self, camera: str) -> None:
        topics = self._resolve_camera_topics(camera)
        enabled = self._is_camera_enabled_runtime(camera)
        self._publish_sync(topics["enabled"], "ON" if enabled else "OFF")

    def _publish_camera_event_control_states(self, camera: str) -> None:
        topics = self._resolve_camera_topics(camera)
        process_end = self._process_end_events_by_camera.get(camera, True)
        process_update = self._process_update_events_by_camera.get(camera, False)
        self._publish_sync(topics["process_end_events"], bool_to_on_off(process_end))
        self._publish_sync(topics["process_update_events"], bool_to_on_off(process_update))

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
            "process_end_events": "{mqtt_prefix}/camera/{camera}/process_end_events",
            "process_end_events_set": "{mqtt_prefix}/camera/{camera}/process_end_events/set",
            "process_update_events": "{mqtt_prefix}/camera/{camera}/process_update_events",
            "process_update_events_set": "{mqtt_prefix}/camera/{camera}/process_update_events/set",
            "action": "{mqtt_prefix}/camera/{camera}/action",
            "subject_type": "{mqtt_prefix}/camera/{camera}/subject_type",
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
        try:
            db_enabled = self._camera_store.get_camera_enabled(camera)
            if db_enabled is not None:
                return db_enabled
        except Exception as exc:
            LOGGER.warning("Camera enabled lookup failed camera=%s error=%s", camera, exc)
        # Unknown cameras must remain disabled until explicitly enabled.
        return False

    def _upsert_discovered_camera(self, event: FrigateEvent) -> None:
        try:
            self._camera_store.upsert_discovered_camera(
                event.camera,
                last_seen_ts=event.event_ts,
            )
        except Exception as exc:
            LOGGER.warning(
                "Failed to upsert discovered camera camera=%s event_id=%s error=%s",
                event.camera,
                event.event_id,
                exc,
            )

    def _sync_queue_stats_to_db(self) -> None:
        try:
            self._camera_store.upsert_kv(
                "counters.dropped_events_total",
                str(self._dropped_events_total),
            )
            self._camera_store.upsert_kv(
                "counters.dropped_update_total",
                str(self._dropped_update_total),
            )
            self._camera_store.upsert_kv(
                "counters.dropped_queue_full_total",
                str(self._dropped_queue_full_total),
            )
        except Exception as exc:
            LOGGER.warning("Failed to persist queue drop counters: %s", exc)

    def _sync_queue_depth_to_db(self, depth: int) -> None:
        try:
            self._camera_store.upsert_kv("runtime.queue_depth", str(depth))
        except Exception as exc:
            LOGGER.warning("Failed to persist queue depth: %s", exc)

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
            "control_doorbell_only_mode": self._resolve_topic_path("control.doorbell_only_mode", "control/doorbell_only_mode"),
            "control_high_precision_mode": self._resolve_topic_path("control.high_precision_mode", "control/high_precision_mode"),
            "control_updates_per_event": self._resolve_topic_path("control.updates_per_event", "control/updates_per_event"),
        }

    def _persist_runtime_controls(self) -> None:
        controls = self._policy_runtime_state.setdefault("controls", {})
        if not isinstance(controls, dict):
            controls = {}
            self._policy_runtime_state["controls"] = controls
        controls["enabled"] = self._service_enabled
        controls["monthly_budget"] = self._monthly_budget_limit
        controls["confidence_threshold"] = self._confidence_threshold_percent
        controls["doorbell_only_mode"] = self._config.modes.doorbell_only_mode.enabled
        controls["high_precision_mode"] = self._config.modes.high_precision_mode.enabled
        controls["updates_per_event"] = self._event_controls.updates_per_event
        camera_event_processing: dict[str, dict[str, bool]] = {}
        for camera in self._config.policy.cameras:
            camera_event_processing[camera] = {
                "process_end_events": self._process_end_events_by_camera.get(camera, True),
                "process_update_events": self._process_update_events_by_camera.get(
                    camera,
                    False,
                ),
            }
        controls["camera_event_processing"] = camera_event_processing
        self._save_policy_state()

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

    def _publish_last_error(self, message: str) -> None:
        safe_message = message.strip()
        if not safe_message:
            return
        self._publish_sync(self._last_error_topic, safe_message)

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
                    await self.publish_status(self._effective_runtime_status())
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


def _resolve_last_error_topic(config: ServiceConfig) -> str:
    template = str(config.topics.get("last_error", "{mqtt_prefix}/last_error"))
    return template.replace("{mqtt_prefix}", config.service.mqtt_prefix)


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


def _parse_monthly_budget(value: str) -> float | None:
    try:
        parsed = float(value)
    except ValueError:
        return None
    if parsed < 0 or parsed > 200:
        return None
    return parsed


def _parse_confidence_threshold(value: str) -> int | None:
    try:
        parsed = int(float(value))
    except ValueError:
        return None
    if parsed < 0 or parsed > 100:
        return None
    return parsed
