# Synthia Vision Current Runtime Contract

Last updated: 2026-02-28

This file is the practical source of truth for active development. It reflects current code behavior (not historical phase notes).

## UI KPI behavior (`/ui`)

- Refresh interval: every `2` seconds.
- Poll sources:
  - `GET /api/status`
  - `GET /api/metrics/summary`
- Heartbeat display format (browser local time): `MM/DD/YYYY HH:MM:SS`
- Cost display precision: 4 decimals (example: `$0.0000`)

## Guest KPI fields in use

- Health card:
  - `service_status`
  - `heartbeat_ts`
  - `current_mode`
- Queue card:
  - `queue_depth`
  - `suppressed_count_today`
  - `suppressed_rate_today`
  - `dropped_events_total`
- Cost card:
  - `cost_daily_total`
  - `cost_month2day_total`
  - `cost_avg_per_event` (alias: `avg_cost_per_event_usd`)
- AI Calls card:
  - `count_today` / `ai_calls_today`
  - `tokens_today_total`
  - `avg_tokens_per_event`
  - `avg_ai_confidence_today` (ratio 0.0-1.0)

Budget intelligence fields (admin summary + MQTT):
- `cost_24h_total`
- `burn_rate_24h`
- `projected_month_total`
- `tokens_24h_total`
- `tokens_month2day_total`

Embedding cache hooks:
- Config knobs:
  - `embeddings.enabled`
  - `embeddings.model`
  - `embeddings.retention_days`
  - `embeddings.retention_max_rows`
  - `embeddings.store_vectors`
- Runtime behavior:
  - when enabled, service writes `embeddings_cache` rows linked to `event_id`
  - vector payload is stored only when `embeddings.store_vectors=true`
  - retention pruning runs on write using day and max-row limits

## Status/KV keys used by API + UI

- `service.status`
- `runtime.heartbeat_ts`
- `runtime.queue_depth`

These are seeded on bootstrap if missing, and updated at runtime.

## DB bootstrap behavior

- Service runtime bootstraps DB in `src/main.py` via `DatabaseBootstrap.initialize()`.
- API app also bootstraps DB in `src/api/server.py` inside `create_guest_api_app()`.
- Bootstrap is idempotent.

## API route surface (active)

Guest:
- `GET /api/status`
- `GET /api/metrics/summary`
- `GET /api/cameras/summary`
- `GET /api/cameras/{camera_key}/card`
- `POST /api/cameras/{camera_key}/toggle`
- `GET /api/cameras/{camera_key}/preview.jpg`

Admin (session required):
- `GET /api/events`
- `GET /api/events/{event_id}`
- `GET /api/cameras`
- `POST /api/cameras/{camera_key}`
- `POST /api/control/{name}`
- `GET /api/errors`
- `GET /api/admin/settings`
- `POST /api/admin/settings/apply`
- `POST /api/admin/settings/save`
- `GET /api/admin/cameras`
- `POST /api/admin/cameras/{camera_key}/apply`
- `POST /api/admin/cameras/{camera_key}/save`
- `GET /api/admin/cameras/{camera_key}/profile`
- `PUT /api/admin/cameras/{camera_key}/profile`
- `GET /api/admin/cameras/{camera_key}/views`
- `PUT /api/admin/cameras/{camera_key}/views/{view_id}`
- `POST /api/admin/cameras/{camera_key}/views/{view_id}/setup/snapshot`
- `POST /api/admin/cameras/{camera_key}/views/{view_id}/setup/generate_context`

Auth/setup:
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/setup/first-run`

## Camera preview behavior

- Route: `GET /api/cameras/{camera_key}/preview.jpg`
- Must satisfy both:
  - `kv ui.preview_enabled=1`
  - `cameras.guest_preview_enabled=1`
- Intervals:
  - enabled camera: `ui.preview_enabled_interval_s` (default `2`)
  - disabled camera: `ui.preview_disabled_interval_s` (default `60`)
- Max concurrent refreshing cards: `ui.preview_max_active` (default `1`)

## Guest camera status toggle behavior

- Route: `POST /api/cameras/{camera_key}/toggle`
- Behavior:
  - flips camera `enabled` state
  - returns updated enabled value
- Intended use:
  - guest dashboard status-pill click interaction

## Admin mode surfaces

- `/ui/setup` exposes global `modes.current` control.
- `/ui/admin` displays `current_mode` in header and health card.
- `/ui/admin` displays budget intelligence widgets:
  - rolling 24h cost and burn rate
  - month-to-date cost and projected month cost
  - rolling 24h and month-to-date token totals

## Common status/result strings

Service status (`service.status`):
- `starting`, `enabled`, `degraded`, `disabled`, `budget_blocked`, `stopped`, `unavailable`

Global runtime mode:
- `runtime.current_mode` / `modes.current` values:
  - `normal`, `delivery_watch`, `guest_expected`, `high_alert`
- MQTT control topic:
  - `.../control/mode` + `.../control/mode/set`

Per-camera `result_status` examples:
- `waiting`, `processing`, `ok`, `unchanged`, `snapshot_failed`, `schema_failed`, `openai_failed`, `token_budget_exceeded`, `blocked_budget`, `skipped`, `suppressed`

Suppression-specific:
- `reject_reason=suppressed_duplicate`
- `suppressed_by_event_id` links suppressed event to the kept event in admin journal APIs

AI explainability (admin event APIs only):
- `ai_confidence` stores normalized model confidence (`0.0` to `1.0`)
- `ai_reason` stores a short sanitized reason snippet (1-2 sentences, no guest exposure)
- `/ui/events` admin table + detail modal render both fields for operator review

MQTT metrics:
- `.../events/avg_confidence_today` publishes rolling daily average AI confidence (ratio)

## Camera setup context

Camera profile fields are persisted in `cameras`:
- `environment`, `purpose`, `view_type`, `mounting_location`, `view_notes`
- `delivery_focus_json`, `privacy_mode`, `setup_completed`, `default_view_id`

Per-view setup context is persisted in `camera_views`:
- `camera_key`, `view_id`, `label`, `ha_preset_id`, `setup_snapshot_path`
- `context_summary`, `expected_activity_json`, `zones_json`, `focus_notes`

Runtime prompt builder uses these context fields when available:
- `environment`, `purpose`, `view_type`, `context_summary`, `focus_notes`, `typical_activities`
