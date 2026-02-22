# Synthia Vision

Synthia Vision is a standalone, event-aware AI service for Frigate + OpenAI + MQTT + Home Assistant.

## Current Status

- Foundation is complete.
- Phase 2 (MQTT + Event Intake) is complete.
- Phase 3.1 policy decision logic is implemented and wired into MQTT intake.
- Phase 3.2 event routing is implemented (accepted vs rejected routes + counters/logs).
- Phase 4 snapshot manager is implemented and wired for accepted events.
- Phase 5.1 MQTT publishing + HA discovery is implemented (including identity-free `action` + `subject_type` contract scaffolding).
- Phase 6 OpenAI client is implemented with strict JSON schema validation and retry handling.
- Phase 7 state/cost counters, day/month rollovers, and budget guard are implemented.
- Local tooling, Docker hardening, and documentation/testing scaffolding are in place.

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
- Bounded internal event queue (`max=50`) between MQTT callback and processing worker
- Backpressure policy:
  - drop incoming `update` events first when queue is full
  - otherwise drop oldest queued event, then enqueue new event
- MQTT callback stays lightweight for Frigate events (decode/normalize/enqueue only)
- Degraded runtime status:
  - publishes `degraded` when queue pressure stays high
  - recovers to normal status when queue depth drops
- Policy decision evaluation is executed for incoming events
- Policy runtime state is persisted atomically to state JSON
- Non-processed events publish only `last_event_id`, `last_event_ts`, and `result_status` (no action/subject/confidence/description updates)
- Runtime event-type controls via HA command topics:
  - process `end` events toggle
  - process `update` events toggle
  - updates-per-event limit (`1..2`) for each `event_id`
- Global metrics publishing:
  - event counters (`count_total`, `count_today`)
  - core cost/token placeholders (`cost.*`, `tokens.*`)
  - retained publish on startup and after accepted processing events

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
  - publishes `result_status=ok` with placeholder action/subject_type/confidence/description until OpenAI stage
  - publishes `result_status=snapshot_failed` when snapshot retrieval fails
  - publishes HA discovery configs (core + per-camera) on startup and on `homeassistant/status=online`
- Phase 5.1.2 identity-free result contract scaffolding:
  - global action allowlist (`policy.actions.allowed`) with per-camera overrides
  - global subject type allowlist (`policy.subject_types.allowed`)
  - preset-aware prompt template support (`ai.prompts.default_preset`, `ai.prompts.presets`, camera `prompt_preset`)
  - post-classification enforcement helper (`invalid_action`, `invalid_subject_type`, description max 200 chars)

### OpenAI Client
- Implemented `src/openai/client.py`:
  - image + prompt request using Responses API structured JSON schema
  - image sent via `input_image` content blocks (not text payload)
  - dynamic per-camera action enums and global subject type enums
  - retries transient provider failures (`timeout`, connection, rate limit, API error)
  - no retries for schema/validation errors
  - preprocessing before encode (JPEG + resize/compress, full-frame only)
  - default vision detail `low` with optional per-camera override
  - hard token guard (`>8000`) with one low-budget retry before `token_budget_exceeded`
  - extracts prompt/completion/total tokens
  - estimates request cost for supported models and updates runtime cost metrics
- Smart update gating (update events only):
  - computes full-frame dHash (`src/pipeline/phash.py`) and compares to camera `last_phash`
  - skips OpenAI when hash distance is below per-camera threshold and publishes `result_status=unchanged`
  - persists `last_phash`/`last_phash_ts` and journals `metrics.phash`, `metrics.phash_distance`, `metrics.skipped_openai_reason`
- MQTT publish path now classifies accepted events and publishes:
  - `result_status=ok` with action/subject_type/confidence/description
  - `result_status=schema_failed` for invalid model payloads
  - `result_status=openai_failed` for provider/runtime failures

## Guest HTTP APIs

Guest endpoints are now exposed by the built-in API server:
- `GET /api/status`
- `GET /api/metrics/summary`
- `GET /api/cameras/summary`

Admin endpoints currently available:
- `GET /api/events`
- `GET /api/events/{id}`
- `GET /api/cameras`
- `POST /api/cameras/{camera_key}`
- `POST /api/control/{name}`
- `GET /api/errors`

Auth/session endpoints:
- `POST /api/auth/login` (sets HTTPOnly session cookie)
- `POST /api/auth/logout` (clears session cookie)
- `GET /api/auth/me`
- `POST /api/setup/first-run` (creates first admin only when no admin exists; localhost allowed, remote requires `FIRST_RUN_TOKEN`)

Authorization:
- Guest endpoints are readable without login (`/api/status`, `/api/metrics/summary`, `/api/cameras/summary`).
- Admin endpoints require an authenticated `admin` session cookie.
- Guest endpoint payloads are intentionally sanitized for iframe safety and do not expose reject reasons, skipped-openai reasons, or raw description fields.

Runtime:
- Server defaults to `0.0.0.0:8080`.
- Override with `SYNTHIA_API_HOST` and `SYNTHIA_API_PORT`.

## UI Routes (FastAPI + Jinja)

Guest/UI:
- `GET /` redirects to `GET /ui`
- `GET /ui` guest dashboard (HA iframe-safe, no sidebar, no admin controls)
- `GET /ui/login`
- `POST /ui/login`
- `POST /ui/logout`

Admin UI pages (require admin session):
- `GET /ui/admin`
- `GET /ui/setup`
- `GET /ui/events`
- `GET /ui/events/{id}`
- `GET /ui/errors`

Implementation paths:
- templates: `src/ui/templates`
- static assets: `src/ui/static`

## Active MQTT Topics (Now)

- Runtime prefix default: `home/synthiavision` (from `service.mqtt_prefix`)
- Status: `home/synthiavision/status`
- Heartbeat: `home/synthiavision/heartbeat_ts`
- Subscribed input: `frigate/events` (from config)
- Core control topics:
  - `.../control/enabled` + `.../set`
  - `.../control/monthly_budget` + `.../set`
  - `.../control/confidence_threshold` + `.../set`
  - `.../control/doorbell_only_mode` + `.../set`
  - `.../control/high_precision_mode` + `.../set`
  - `.../control/updates_per_event` + `.../set`
- Core metrics topics:
  - `.../events/count_total`
  - `.../events/count_today`
  - `.../cost/last`
  - `.../cost/daily_total`
  - `.../cost/month2day_total`
  - `.../cost/avg_per_event`
  - `.../tokens/avg_per_request`
  - `.../tokens/avg_per_day`
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
  - `.../camera/{camera}/subject_type`
  - `.../camera/{camera}/confidence` (0-100 integer)
  - `.../camera/{camera}/description`
  - `.../cost/monthly_by_camera/{camera}`
  - Camera idle defaults at startup:
    - `result_status=waiting`
    - `action=waiting`
    - `description=waiting for event`

## Configuration

Primary root file:
- `config/config.yaml`

Modular includes:
- `config/config.yaml` includes `config/config.d/*.yaml` in sorted order.
- Recommended convention:
  - `config/config.d/00-defaults.yaml` (repo defaults)
  - `config/config.d/99-local.yaml` (local overrides, gitignored)
- Merge precedence:
  - root config
  - included module files (in order)
  - environment overrides
- Merge behavior:
  - dictionaries deep-merge
  - lists replace earlier values (not concatenated)
- Config schema version is validated via `schema_version` at root.

Key current settings:
- `mqtt.heartbeat_interval_seconds`
- `policy.defaults.process_on` (now supports list, e.g. `["end", "update"]`)
- `policy.defaults.min_process_interval_s` (future processing throttle)
- `policy.actions.default_action`
- `policy.actions.allowed`
  - includes neutral indoor state action `room_occupied`
- `policy.subject_types.default`
- `policy.subject_types.allowed`
- `policy.cameras.<camera>.prompt_preset`
- `policy.cameras.<camera>.actions.allowed`
- `ai.prompts.default_preset`
- `ai.prompts.presets`
- `ai.openai.retry_attempts`
- `ai.openai.retry_backoff_s`
- `ai.vision_detail`
- `ai.image_preprocess.enabled|max_side_px|jpeg_quality|strip_metadata`
- `policy.cameras.<camera>.vision_detail`
- `policy.cameras.<camera>.max_side_px`
- `topics.status`
- `topics.heartbeat_ts`
- `topics.camera.result_status`
- `topics.camera.process_end_events`
- `topics.camera.process_update_events`
- `topics.control.updates_per_event`
- `topics.control.enabled`
- `topics.control.monthly_budget`
- `topics.control.confidence_threshold`
- `topics.control.doorbell_only_mode`
- `topics.control.high_precision_mode`
- `topics.events.count_total`
- `topics.events.count_today`
- `topics.cost.*`
- `topics.tokens.*`
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

Restart without rebuild:
```bash
docker compose restart synthia-vision
```

Run local tooling:
```bash
python tools/publish_sample_event.py --host 127.0.0.1 --topic frigate/events
python tools/run_pipeline_once.py --camera livingroom --event-type end
```

## State Persistence

Policy runtime state is persisted in JSON with atomic writes:
- `controls.updates_per_event`
- `controls.camera_event_processing.<camera>.process_end_events`
- `controls.camera_event_processing.<camera>.process_update_events`
- `metrics.count_total`
- `metrics.count_today`
- `metrics.count_today_date`
- `metrics.cost_*`
- `metrics.tokens_*`
- `events.recent_event_ids`
- `events.last_by_camera.<camera>.last_event_id`
- `events.last_by_camera.<camera>.last_event_ts`

Configured via:
- `service.paths.state_file`
- `service.paths.db_file` (SQLite event/metrics/errors store)

SQLite bootstrap:
- On startup, the service initializes SQLite schema from `Documents/schema.sql`.
- Connection pragmas include WAL mode, busy timeout, and foreign key enforcement.
- Seed defaults are written into `kv` if missing (idempotent).
- Worker-path journaling writes to SQLite:
  - `events`: one row per handled event (accepted or rejected) with latest result fields
  - `metrics`: processing-path rows for OpenAI usage or skip reasons
  - `errors`: runtime component errors with short detail + optional event/camera linkage
- Phase 8 bootstrap:
  - if `ADMIN_PASSWORD` is set and `users` is empty, startup creates one `admin` user (default username `admin`, override `ADMIN_USERNAME`)
  - bootstrap is one-time; when users already exist no new admin is created
  - startup synchronizes `kv.setup.completed` based on whether an admin exists
  - password hashing uses Argon2 when available (`argon2-cffi`) with scrypt compatibility fallback
  - signed session token primitives are available (`src/auth/session.py`) with role-aware payload (`guest`/`admin`)
  - session cookie defaults are defined for UI/API integration (`HttpOnly`, `SameSite=Lax`)
  - first-run API setup is available at `POST /api/setup/first-run` and enforces `src/auth/first_run.py` policy: setup allowed only when no admin exists; localhost is allowed, remote requires matching `FIRST_RUN_TOKEN`

Camera runtime source of truth:
- Discovered cameras are persisted in SQLite `cameras`.
- Runtime camera enable/event controls and per-camera overrides are resolved from SQLite.
- Legacy YAML `policy.cameras` values are not used as runtime source of truth.
- Optional one-time import tool: `python tools/migrate_policy_cameras_to_sqlite.py` (`--dry-run`, `--overwrite` supported).

Metric formulas:
- `metrics.cost_avg_per_event = metrics.cost_month2day_total / metrics.count_total`
- `metrics.tokens_avg_per_request` is maintained as a running average over processed requests
- `metrics.tokens_avg_per_day = metrics.tokens_avg_per_request * metrics.count_today` (estimated daily token total)

## Troubleshooting

- `status=budget_blocked`:
  - Raise `home/synthiavision/control/monthly_budget/set` or lower model usage settings (`ai.vision_detail`, `ai.image_preprocess.max_side_px`).
- High token usage:
  - Keep `ai.vision_detail=low` and `ai.image_preprocess.max_side_px=512`.
  - Check `synthia_vision.ai` logs for `total_tokens`, `detail`, image sizes, and bytes.
- No OpenAI results:
  - Ensure `OPENAI_API_KEY` is set in env and container.
  - Check `last_error` topic for `openai_failed` / `schema_failed`.
- Time/date rollover surprises:
  - Daily counters reset on date change, monthly totals reset when month key changes.
