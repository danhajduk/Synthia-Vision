# Synthia Vision Current Runtime Contract

Last updated: 2026-02-23

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
- Queue card:
  - `queue_depth`
  - `dropped_events_total`
- Cost card:
  - `cost_daily_total`
  - `cost_month2day_total`
  - `cost_avg_per_event` (alias: `avg_cost_per_event_usd`)
- AI Calls card:
  - `count_today` / `ai_calls_today`
  - `tokens_today_total`
  - `avg_tokens_per_event`

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

## Common status/result strings

Service status (`service.status`):
- `starting`, `enabled`, `degraded`, `disabled`, `budget_blocked`, `stopped`, `unavailable`

Per-camera `result_status` examples:
- `waiting`, `processing`, `ok`, `unchanged`, `snapshot_failed`, `schema_failed`, `openai_failed`, `token_budget_exceeded`, `blocked_budget`, `skipped`, `suppressed`
