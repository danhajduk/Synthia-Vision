# Synthia Vision

Synthia Vision is a standalone, event-aware AI service for Frigate + OpenAI + MQTT + Home Assistant.

## Current Status

- Foundation is complete.
- Phase 2 (MQTT + Event Intake) is complete.
- Phase 3.1 policy decision logic is implemented and wired into MQTT intake.
- Phase 3.2 event routing is implemented (accepted vs rejected routes + counters/logs).
- Next: Phase 4 snapshot manager and downstream pipeline stages.

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
- Subscribe to Frigate events topic and log `event_id`, `camera`, `type`
- Policy decision evaluation is executed for incoming events
- Policy runtime state is persisted atomically to state JSON

### Policy Engine
- Pure function: `should_process(event, state, config) -> Decision`
- Rules implemented:
  - allowed event types (`policy.defaults.process_on`)
  - duplicate event check
  - camera enabled check
  - doorbell-only mode camera gating
  - label allow-list
  - confidence threshold
  - cooldown/min interval enforcement
- Decision logs emitted on `synthia_vision.policy`
- Rejection logs include explicit reason and details

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
- `logging.files.core|mqtt|config|policy|ai`
- `logging.retention_days`
- `service.paths.state_file`

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
- `SYNTHIA_LOG_RETENTION_DAYS`
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
- Optional per-component files: `logging.files.*`
- Daily rotation at midnight with filename pattern: `[name]-YYYY-MM-DD.log`
- Log retention window: `logging.retention_days`
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
Container timezone is set to Pacific via `TZ=America/Los_Angeles`.

```bash
docker compose up -d --build
docker compose logs -f synthia-vision
```

If you update compose environment (such as timezone), recreate the container:
```bash
docker compose up -d --force-recreate
```

Stop:
```bash
docker compose down
```

## State Persistence

Policy runtime state is persisted in JSON with atomic writes:
- `events.recent_event_ids`
- `events.last_by_camera.<camera>.last_event_id`
- `events.last_by_camera.<camera>.last_event_ts`

Configured via:
- `service.paths.state_file`
