-- Synthia Vision — SQLite Schema (v1)
-- This file is pure DDL and can be executed directly during DB initialization.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- =========================
-- kv
-- =========================
CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL,
  updated_ts TEXT NOT NULL
);

-- =========================
-- users
-- =========================
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','guest')),
  created_ts TEXT NOT NULL,
  last_login_ts TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- =========================
-- cameras
-- =========================
CREATE TABLE IF NOT EXISTS cameras (
  camera_key TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 0,

  discovered_first_ts TEXT NOT NULL,
  last_seen_ts TEXT NOT NULL,

  prompt_preset TEXT,
  confidence_threshold REAL,
  cooldown_s INTEGER,

  process_end_events INTEGER,
  process_update_events INTEGER,
  updates_per_event INTEGER,
  guest_preview_enabled INTEGER NOT NULL DEFAULT 0,
  security_capable INTEGER NOT NULL DEFAULT 0,
  security_mode INTEGER NOT NULL DEFAULT 0,
  environment TEXT,
  purpose TEXT,
  view_type TEXT,
  mounting_location TEXT,
  view_notes TEXT,
  delivery_focus_json TEXT,
  privacy_mode TEXT NOT NULL DEFAULT 'no_identifying_details',
  setup_completed INTEGER NOT NULL DEFAULT 0,
  default_view_id TEXT,
  frigate_camera_id TEXT,
  detect_width INTEGER,
  detect_height INTEGER,
  detect_fps REAL,
  audio_enabled INTEGER NOT NULL DEFAULT 0,
  tracked_objects_json TEXT,
  snapshots_enabled INTEGER NOT NULL DEFAULT 0,
  record_enabled INTEGER NOT NULL DEFAULT 0,
  detect_stream_name TEXT,
  record_stream_name TEXT,
  health_status TEXT,
  health_detail TEXT,
  health_updated_ts TEXT,

  vision_detail TEXT CHECK (vision_detail IN ('low','high')),
  phash_threshold INTEGER,

  last_phash TEXT,
  last_phash_ts TEXT
);

CREATE INDEX IF NOT EXISTS idx_cameras_last_seen ON cameras(last_seen_ts);
CREATE INDEX IF NOT EXISTS idx_cameras_enabled ON cameras(enabled);

-- =========================
-- camera_views
-- =========================
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

-- =========================
-- events
-- =========================
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  event_id TEXT NOT NULL UNIQUE,
  ts TEXT NOT NULL,
  camera TEXT NOT NULL,
  event_type TEXT NOT NULL,

  accepted INTEGER NOT NULL,
  reject_reason TEXT,
  cooldown_remaining_s REAL,
  dedupe_hit INTEGER NOT NULL DEFAULT 0,
  suppressed_by_event_id TEXT,

  result_status TEXT,
  action TEXT,
  subject_type TEXT,
  frigate_score REAL,
  confidence REAL,
  ai_confidence REAL,
  ai_reason TEXT,
  risk_score REAL,
  description TEXT,

  snapshot_bytes INTEGER,
  image_width INTEGER,
  image_height INTEGER,
  vision_detail TEXT CHECK (vision_detail IN ('low','high')),

  created_ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_camera_ts ON events(camera, ts);
CREATE INDEX IF NOT EXISTS idx_events_accepted_ts ON events(accepted, ts);
CREATE INDEX IF NOT EXISTS idx_events_event_type_ts ON events(event_type, ts);

-- =========================
-- metrics
-- =========================
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
  skipped_openai_reason TEXT,

  created_ts TEXT NOT NULL,

  FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_metrics_event_id ON metrics(event_id);
CREATE INDEX IF NOT EXISTS idx_metrics_created_ts ON metrics(created_ts);

-- =========================
-- embeddings_cache
-- =========================
CREATE TABLE IF NOT EXISTS embeddings_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL,
  camera TEXT NOT NULL,
  model TEXT NOT NULL,
  snapshot_sha256 TEXT,
  embedding_dim INTEGER,
  vector_json TEXT,
  vector_stored INTEGER NOT NULL DEFAULT 0,
  created_ts TEXT NOT NULL,
  FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_embeddings_event_id ON embeddings_cache(event_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_camera_created ON embeddings_cache(camera, created_ts);
CREATE INDEX IF NOT EXISTS idx_embeddings_created_ts ON embeddings_cache(created_ts);

-- =========================
-- errors
-- =========================
CREATE TABLE IF NOT EXISTS errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  component TEXT NOT NULL,
  message TEXT NOT NULL,
  detail TEXT,
  event_id TEXT,
  camera TEXT
);

CREATE INDEX IF NOT EXISTS idx_errors_ts ON errors(ts);
CREATE INDEX IF NOT EXISTS idx_errors_component_ts ON errors(component, ts);

-- =========================
-- End of schema (v1)
-- =========================
