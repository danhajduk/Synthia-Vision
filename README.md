# Synthia Vision

Synthia Vision is a standalone, event-aware AI service for Frigate + OpenAI + MQTT + Home Assistant.

## Current Status

- Foundation is complete.
- Phase 2 (MQTT + Event Intake) is complete.
- Next: Phase 3 policy engine logic.

## Implemented

### Foundation
- Async service lifecycle and graceful shutdown (`src/main.py`)
- Centralized logging (`src/logging_utils.py`)
- Shared application errors (`src/errors.py`)
- Core Frigate/OpenAI models (`src/models.py`)
- Typed YAML config loader with env placeholders and validation (`src/config/settings.py`)

### MQTT + Event Intake
- MQTT connect/reconnect wrapper (`src/mqtt/mqtt_client.py`)
- MQTT Last Will status on unexpected disconnect: `unavailable`
- Retained status flow:
  - `starting` at startup
  - `enabled` when ready
  - `stopped` on graceful shutdown
- Heartbeat timestamp publishing on interval
- Subscribe to Frigate events topic and log `event_id`, `camera`, `type` (no routing yet)

## Active MQTT Topics (Now)

- Status: `synthia/synthiavision/status`
- Heartbeat: `synthia/synthiavision/heartbeat_ts`
- Subscribed input: `frigate/events` (from config)

## Configuration

Primary file:
- `config/config.yaml`

Key current settings:
- `mqtt.heartbeat_interval_seconds`
- `policy.defaults.process_on` (now supports list, e.g. `["end", "update"]`)
- `policy.defaults.min_process_interval_s` (future processing throttle)
- `topics.status`
- `topics.heartbeat_ts`
- `logging.level`
- `logging.components.core`
- `logging.components.mqtt`
- `logging.components.config`
- `logging.components.policy`
- `logging.components.ai`

Env overrides supported:
- `SYNTHIA_CONFIG`
- `OPENAI_API_KEY`
- `MQTT_HOST`
- `MQTT_PORT`
- `MQTT_USERNAME`
- `MQTT_PASSWORD`
- `MQTT_KEEPALIVE_SECONDS`
- `MQTT_HEARTBEAT_SECONDS`
- `FRIGATE_BASE_URL`
- `OPENAI_MODEL`
- `SYNTHIA_LOG_LEVEL`
- `SYNTHIA_LOG_CORE`
- `SYNTHIA_LOG_MQTT`
- `SYNTHIA_LOG_CONFIG`
- `SYNTHIA_LOG_POLICY`
- `SYNTHIA_LOG_AI`
- `SYNTHIA_MONTHLY_BUDGET_LIMIT`
- `SYNTHIA_CONFIDENCE_THRESHOLD`

## Logging

Logging is now configurable globally and per component through `config/config.yaml`.

- Global default: `logging.level`
- Component overrides:
  - `logging.components.core`
  - `logging.components.mqtt`
  - `logging.components.config`
  - `logging.components.policy`
  - `logging.components.ai`
- Optional file logging: `logging.file`
- JSON toggle placeholder: `logging.json`

## Run Locally

1. Install dependencies:
```bash
pip install -r requirements.txt
```
2. Set minimum secret:
```bash
export OPENAI_API_KEY="your-key"
```
3. Start:
```bash
python -m src.main
```

## Run With Docker Compose

Uses your existing external MQTT broker (no bundled Mosquitto service).

```bash
docker compose up -d --build
docker compose logs -f synthia-vision
```

Stop:
```bash
docker compose down
```
