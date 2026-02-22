# Synthia Vision

Synthia Vision is a standalone, event-aware AI service for Frigate + OpenAI + MQTT + Home Assistant.

## Current Status

- Foundation is complete.
- Phase 2 (MQTT + Event Intake) is complete.
- Phase 3.1 policy decision logic is implemented and wired into MQTT intake.
- Phase 3.2 event routing is implemented (accepted vs rejected routes + counters/logs).
- Phase 4 snapshot manager is implemented and wired for accepted events.
- Next: Phase 5 OpenAI classification and downstream publishing stages.

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
- Runtime event-type controls via HA command topics:
  - process `end` events toggle
  - process `update` events toggle
  - updates-per-event limit (`1..2`) for each `event_id`

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

### Snapshot Manager
- Frigate snapshot fetch by event ID (`/api/events/{event_id}/snapshot.jpg`)
- Request timeout handling and retry/backoff policy
- Max-bytes guard for response safety
- Optional debug snapshot save to `service.paths.snapshots_dir` when `frigate.snapshot.debug_save=true`
- Snapshot fetch is invoked for events routed to `processing`
- Phase 5.1.1 publisher wiring:
  - publishes per-camera runtime topics after snapshot step
  - publishes `result_status=ok` with placeholder action/confidence/description until OpenAI stage
  - publishes `result_status=snapshot_failed` when snapshot retrieval fails
  - publishes HA discovery configs (core + per-camera) on startup and on `homeassistant/status=online`

## Active MQTT Topics (Now)

- Status: `synthia/synthiavision/status`
- Heartbeat: `synthia/synthiavision/heartbeat_ts`
- Subscribed input: `frigate/events` (from config)
- Core control topics:
  - `.../control/updates_per_event` + `.../set`
- Per-camera output:
  - `.../camera/{camera}/enabled` (`ON`/`OFF`)
  - `.../camera/{camera}/enabled/set` (`ON`/`OFF` command)
  - `.../camera/{camera}/process_end_events` (`ON`/`OFF`)
  - `.../camera/{camera}/process_end_events/set` (`ON`/`OFF` command)
  - `.../camera/{camera}/process_update_events` (`ON`/`OFF`)
  - `.../camera/{camera}/process_update_events/set` (`ON`/`OFF` command)
  - `.../camera/{camera}/last_event_id`
  - `.../camera/{camera}/last_event_ts` (ISO timestamp)
  - `.../camera/{camera}/result_status`
  - `.../camera/{camera}/action`
  - `.../camera/{camera}/confidence` (0-100 integer)
  - `.../camera/{camera}/description`
  - `.../cost/monthly_by_camera/{camera}`

## Configuration

Primary file:
- `config/config.yaml`

Key current settings:
- `mqtt.heartbeat_interval_seconds`
- `policy.defaults.process_on` (now supports list, e.g. `["end", "update"]`)
- `policy.defaults.min_process_interval_s` (future processing throttle)
- `topics.status`
- `topics.heartbeat_ts`
- `topics.camera.result_status`
- `topics.camera.process_end_events`
- `topics.camera.process_update_events`
- `topics.control.updates_per_event`
- `logging.level`
- `logging.components.core`
- `logging.components.mqtt`
- `logging.components.config`
- `logging.components.policy`
- `logging.components.ai`
- `logging.files.core|mqtt|config|policy|ai`
- `logging.retention_days`
- `service.paths.state_file`
- `service.paths.snapshots_dir`
- `frigate.snapshot.endpoint_template`
- `frigate.snapshot.timeout_s`
- `frigate.snapshot.retries`
- `frigate.snapshot.retry_backoff_s`
- `frigate.snapshot.max_bytes`
- `frigate.snapshot.debug_save`

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
