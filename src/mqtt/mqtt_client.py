"""MQTT client wrapper with reconnect and lifecycle helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from src.config import ServiceConfig
from src.event_router import EventRouter
from src.errors import ExternalServiceError, ValidationError
from src.models import FrigateEvent
from src.policy_engine import should_process
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
        self._status_retain = config.mqtt.retain
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._state_manager = StateManager(config.state_file)
        self._event_router = EventRouter()
        self._policy_runtime_state: dict[str, Any] = {
            "events": {
                "recent_event_ids": [],
                "last_by_camera": {},
            }
        }

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
            str(int(time.time())),
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
        publish_info = self._client.publish(
            topic=topic,
            payload=payload,
            qos=self._config.mqtt.qos if qos is None else qos,
            retain=self._status_retain if retain is None else retain,
        )
        await asyncio.to_thread(publish_info.wait_for_publish, 5.0)
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

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
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

        decision = should_process(
            event=event,
            state=self._policy_runtime_state,
            config=self._config,
        )
        route_result = self._event_router.route(event, decision)
        if route_result.route == "processing":
            self._remember_policy_event(event)

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
