# Synthia Vision — SQLite Schema (v1)

This document is the **source of truth** for the SQLite schema used by Synthia Vision’s “Boring runtime + local explain UI” sprint.

## Connection pragmas (apply at init and/or per connection)

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

- **WAL** improves concurrency for mixed reads/writes.
- **busy_timeout** prevents “database is locked” under bursts.
- **foreign_keys** ensures referential integrity for metrics → events.

---

## Tables

### 1) `kv`
Global settings, flags, and schema versioning.

```sql
CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL,
  updated_ts TEXT NOT NULL
);
```

---

### 2) `users`
Built-in UI authentication (guest/admin).

```sql
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','guest')),
  created_ts TEXT NOT NULL,
  last_login_ts TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
```

---

### 3) `cameras`
Discovered cameras + per-camera overrides.

**Important:** Newly discovered cameras must default to **disabled**.

```sql
CREATE TABLE IF NOT EXISTS cameras (
  camera_key TEXT PRIMARY KEY,              -- Frigate camera id (stable)
  display_name TEXT NOT NULL,               -- UI-friendly name
  enabled INTEGER NOT NULL DEFAULT 0,        -- MUST default disabled

  discovered_first_ts TEXT NOT NULL,
  last_seen_ts TEXT NOT NULL,

  -- Per-camera overrides (NULL means "use global default")
  prompt_preset TEXT,
  confidence_threshold REAL,
  cooldown_s INTEGER,

  process_end_events INTEGER,
  process_update_events INTEGER,
  updates_per_event INTEGER,
  guest_preview_enabled INTEGER NOT NULL DEFAULT 0,
  environment TEXT,
  purpose TEXT,
  view_type TEXT,
  mounting_location TEXT,
  view_notes TEXT,
  delivery_focus_json TEXT,
  privacy_mode TEXT NOT NULL DEFAULT 'no_identifying_details',
  setup_completed INTEGER NOT NULL DEFAULT 0,
  default_view_id TEXT,

  vision_detail TEXT CHECK (vision_detail IN ('low','high')),
  phash_threshold INTEGER,

  -- Smart-update state cache (last accepted hash)
  last_phash TEXT,
  last_phash_ts TEXT
);

CREATE INDEX IF NOT EXISTS idx_cameras_last_seen ON cameras(last_seen_ts);
CREATE INDEX IF NOT EXISTS idx_cameras_enabled ON cameras(enabled);
```

---

### 3a) `camera_views`
Per-camera setup view/preset context records.

```sql
CREATE TABLE IF NOT EXISTS camera_views (
  id INTEGER PRIMARY KEY,
  camera_key TEXT NOT NULL,
  view_id TEXT NOT NULL,
  label TEXT NOT NULL,
  ha_preset_id TEXT,
  setup_snapshot_path TEXT,
  context_summary TEXT,
  expected_activity_json TEXT,
  zones_json TEXT,
  focus_notes TEXT,
  created_ts INTEGER NOT NULL,
  updated_ts INTEGER NOT NULL,
  UNIQUE(camera_key, view_id)
);

CREATE INDEX IF NOT EXISTS idx_camera_views_camera_key ON camera_views(camera_key);
CREATE INDEX IF NOT EXISTS idx_camera_views_camera_ha_preset ON camera_views(camera_key, ha_preset_id);
```

---

### 4) `events`
One row per Frigate event that the service **handled** (accepted OR rejected). This is the canonical timeline.

```sql
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  event_id TEXT NOT NULL UNIQUE,           -- Frigate event id
  ts TEXT NOT NULL,                        -- Event timestamp (ISO8601)
  camera TEXT NOT NULL,                    -- camera_key
  event_type TEXT NOT NULL,                -- 'start'/'end'/'update'/...

  accepted INTEGER NOT NULL,               -- 0/1
  reject_reason TEXT,                      -- enum-ish string if rejected
  cooldown_remaining_s REAL,
  dedupe_hit INTEGER NOT NULL DEFAULT 0,   -- 0/1

  -- Result fields (meaningful if accepted and processed)
  result_status TEXT,                      -- 'ok','unchanged','snapshot_fail','openai_fail', ...
  action TEXT,
  subject_type TEXT,
  confidence REAL,
  description TEXT,                        -- write-time truncation (<= 200 chars)

  snapshot_bytes INTEGER,
  image_width INTEGER,
  image_height INTEGER,
  vision_detail TEXT CHECK (vision_detail IN ('low','high')),

  created_ts TEXT NOT NULL                 -- ingestion/write timestamp (ISO8601)
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_camera_ts ON events(camera, ts);
CREATE INDEX IF NOT EXISTS idx_events_accepted_ts ON events(accepted, ts);
CREATE INDEX IF NOT EXISTS idx_events_event_type_ts ON events(event_type, ts);
```

---

### 5) `metrics`
Optional “explainability details” row for events that enter the processing path (snapshot/OpenAI). Kept separate so event list queries stay fast.

```sql
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  event_id TEXT NOT NULL,

  latency_snapshot_ms REAL,
  latency_openai_ms REAL,
  latency_total_ms REAL,

  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  cost_usd REAL,
  model TEXT,

  phash TEXT,
  phash_distance INTEGER,
  skipped_openai_reason TEXT,              -- 'phash_unchanged','budget_blocked','policy_reject', ...

  created_ts TEXT NOT NULL,

  FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_metrics_event_id ON metrics(event_id);
CREATE INDEX IF NOT EXISTS idx_metrics_created_ts ON metrics(created_ts);
```

---

### 6) `errors`
Recent runtime errors for UI/diagnostics (no MQTT clutter).

```sql
CREATE TABLE IF NOT EXISTS errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  component TEXT NOT NULL,                 -- 'mqtt','snapshot','ai','db','policy','ui'
  message TEXT NOT NULL,
  detail TEXT,                             -- short stack snippet ok
  event_id TEXT,
  camera TEXT
);

CREATE INDEX IF NOT EXISTS idx_errors_ts ON errors(ts);
CREATE INDEX IF NOT EXISTS idx_errors_component_ts ON errors(component, ts);
```

---

## Canonical “enum-ish” strings (validate in app)
Store these as **TEXT** and validate in application code so you can evolve values without DB migrations.

- `event_type`: `start|end|update|...`
- `reject_reason`: `camera_disabled|label_disallowed|cooldown|duplicate|doorbell_only|confidence|...`
- `result_status`: `ok|unchanged|snapshot_fail|openai_fail|schema_fail|budget_blocked|token_budget_exceeded|...`
- `skipped_openai_reason`: `phash_unchanged|budget_blocked|policy_reject|snapshot_fail|...`

---

## Seed keys for `kv` (exact list)

Seed these keys during DB initialization **if missing**. All timestamps are ISO8601 UTC strings.

### Schema / setup
- `db.schema_version` = `1`
- `setup.completed` = `0`  (set to `1` when an admin user exists; synchronized at startup)
- `service.status` = `starting`

### Runtime / pipeline knobs (persisted defaults)
These are the settings your **admin Setup page** should edit (persisted in `kv`). Per-camera overrides live in `cameras`.

- `runtime.enabled` = `1`  (master enable switch)
- `runtime.doorbell_only_mode` = `0`
- `runtime.high_precision_mode` = `0`

- `policy.default_confidence_threshold` = `0.65`
- `policy.default_cooldown_s` = `30`
- `policy.default_process_end_events` = `1`
- `policy.default_process_update_events` = `1`
- `policy.default_updates_per_event` = `1`

- `ai.default_vision_detail` = `low`
- `ai.smart_update.enabled` = `1`
- `ai.smart_update.phash_threshold` = `6`   (distance <= threshold => unchanged)
- `ai.preprocess.crop_enabled` = `0`        (must remain 0 permanently)
- `ai.preprocess.max_image_bytes` = `0`     (0 means "no explicit cap"; optional)
- `ai.preprocess.max_width` = `1280`        (optional; keep full frame, resize only)
- `ai.preprocess.jpeg_quality` = `75`       (optional)

### Phase 11 setup/preview keys
- `policy.defaults.confidence_threshold` = `0.65`
- `policy.modes.doorbell_only` = `0`
- `ai.modes.high_precision` = `0`
- `ai.defaults.vision_detail` = `low`
- `policy.smart_update.phash_threshold_default` = `6`
- `policy.smart_update.phash_threshold_update` = `6`
- `ui.subtitle` = `OpenAI-powered camera events`
- `ui.preview_enabled` = `1`
- `ui.preview_enabled_interval_s` = `2`
- `ui.preview_disabled_interval_s` = `60`
- `ui.preview_max_active` = `1`

### Budget keys
- `budget.monthly_limit_usd` = `10.00`
- `budget.behavior` = `block_openai`        (e.g., 'block_openai' | 'disable_service')
- `budget.current_month` = `YYYY-MM`        (e.g., '2026-02') — set on first run
- `budget.month_cost_usd` = `0.00`

### Counters (optional persisted counters; UI reads from queries when possible)
If you already keep counters in a state file, migrate into `kv` using these keys:

- `counters.total_events` = `0`
- `counters.accepted_events` = `0`
- `counters.rejected_events` = `0`
- `counters.openai_calls` = `0`
- `counters.dropped_events_total` = `0`
- `counters.dropped_update_total` = `0`
- `counters.dropped_queue_full_total` = `0`

### Optional: “lasts” for quick UI (non-critical)
- `last.event_id` = ``
- `last.event_ts` = ``
- `last.camera` = ``

---

## Notes / invariants (must hold)
1) **Newly discovered cameras must default to `enabled=0`.**
2) **Cropping must never be used** (operate on full-frame; resize/compress OK).
3) For performance: UI event listing should primarily query `events`, joining `metrics` only for detail view.
4) If you implement schema migrations later, store the current schema version in `kv.db.schema_version`.
