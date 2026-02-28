"""SQLite bootstrap helpers for Synthia Vision."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.errors import ConfigError

PRAGMA_STATEMENTS = (
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA foreign_keys = ON;",
    "PRAGMA busy_timeout = 5000;",
)

SEED_KV_KEYS: tuple[tuple[str, str], ...] = (
    ("db.schema_version", "1"),
    ("setup.completed", "0"),
    ("service.status", "starting"),
    ("runtime.enabled", "1"),
    ("runtime.doorbell_only_mode", "0"),
    ("runtime.high_precision_mode", "0"),
    ("policy.default_confidence_threshold", "0.65"),
    ("policy.default_cooldown_s", "30"),
    ("policy.default_process_end_events", "1"),
    ("policy.default_process_update_events", "1"),
    ("policy.default_updates_per_event", "1"),
    ("ai.default_vision_detail", "low"),
    ("ai.smart_update.enabled", "1"),
    ("ai.smart_update.phash_threshold", "6"),
    ("ai.preprocess.crop_enabled", "0"),
    ("ai.preprocess.max_image_bytes", "0"),
    ("ai.preprocess.max_width", "1280"),
    ("ai.preprocess.jpeg_quality", "75"),
    ("budget.monthly_limit_usd", "10.00"),
    ("policy.defaults.confidence_threshold", "0.65"),
    ("policy.modes.doorbell_only", "0"),
    ("ai.modes.high_precision", "0"),
    ("modes.current", "normal"),
    ("runtime.current_mode", "normal"),
    ("ai.defaults.vision_detail", "low"),
    ("policy.smart_update.phash_threshold_default", "6"),
    ("policy.smart_update.phash_threshold_update", "6"),
    ("ui.subtitle", "OpenAI-powered camera events"),
    ("ui.preview_enabled", "1"),
    ("ui.preview_enabled_interval_s", "2"),
    ("ui.preview_disabled_interval_s", "60"),
    ("ui.preview_max_active", "1"),
    ("budget.behavior", "block_openai"),
    ("budget.month_cost_usd", "0.00"),
    ("counters.total_events", "0"),
    ("counters.accepted_events", "0"),
    ("counters.rejected_events", "0"),
    ("counters.openai_calls", "0"),
    ("counters.dropped_events_total", "0"),
    ("counters.dropped_update_total", "0"),
    ("counters.dropped_queue_full_total", "0"),
    ("last.event_id", ""),
    ("last.event_ts", ""),
    ("last.camera", ""),
)


@dataclass(slots=True)
class DatabaseBootstrap:
    """Initialize SQLite DB schema, pragmas, and seed keys."""

    db_path: Path
    schema_sql_path: Path = Path("Documents/schema.sql")

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        schema_sql = self._load_schema_sql()
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            self._apply_pragmas(conn)
            conn.executescript(schema_sql)
            self._migrate_schema(conn)
            self._seed_kv(conn)
            conn.commit()

    def _load_schema_sql(self) -> str:
        if not self.schema_sql_path.exists():
            raise ConfigError(f"Schema SQL file not found: {self.schema_sql_path}")
        try:
            return self.schema_sql_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Failed to read schema SQL: {exc}") from exc

    @staticmethod
    def _apply_pragmas(conn: sqlite3.Connection) -> None:
        cur = conn.cursor()
        try:
            for stmt in PRAGMA_STATEMENTS:
                cur.execute(stmt)
        finally:
            cur.close()

    @staticmethod
    def _seed_kv(conn: sqlite3.Connection) -> None:
        now = datetime.now(timezone.utc).isoformat()
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        cur = conn.cursor()
        try:
            for k, default_v in SEED_KV_KEYS:
                cur.execute(
                    "INSERT OR IGNORE INTO kv(k, v, updated_ts) VALUES(?, ?, ?)",
                    (k, default_v, now),
                )
            cur.execute(
                "INSERT OR IGNORE INTO kv(k, v, updated_ts) VALUES(?, ?, ?)",
                ("budget.current_month", month_key, now),
            )
        finally:
            cur.close()

    @staticmethod
    def _migrate_schema(conn: sqlite3.Connection) -> None:
        cur = conn.cursor()
        try:
            columns = conn.execute("PRAGMA table_info(cameras)").fetchall()
            column_names = {str(row[1]) for row in columns}
            camera_column_additions: tuple[str, ...] = (
                "guest_preview_enabled INTEGER NOT NULL DEFAULT 0",
                "security_capable INTEGER NOT NULL DEFAULT 0",
                "security_mode INTEGER NOT NULL DEFAULT 0",
                "environment TEXT",
                "purpose TEXT",
                "view_type TEXT",
                "mounting_location TEXT",
                "view_notes TEXT",
                "delivery_focus_json TEXT",
                "privacy_mode TEXT NOT NULL DEFAULT 'no_identifying_details'",
                "setup_completed INTEGER NOT NULL DEFAULT 0",
                "default_view_id TEXT",
                "frigate_camera_id TEXT",
                "detect_width INTEGER",
                "detect_height INTEGER",
                "detect_fps REAL",
                "audio_enabled INTEGER NOT NULL DEFAULT 0",
                "tracked_objects_json TEXT",
                "snapshots_enabled INTEGER NOT NULL DEFAULT 0",
                "record_enabled INTEGER NOT NULL DEFAULT 0",
                "detect_stream_name TEXT",
                "record_stream_name TEXT",
                "health_status TEXT",
                "health_detail TEXT",
                "health_updated_ts TEXT",
            )
            for column_def in camera_column_additions:
                column_name = column_def.split(" ", 1)[0]
                if column_name in column_names:
                    continue
                cur.execute(f"ALTER TABLE cameras ADD COLUMN {column_def}")
                column_names.add(column_name)

            cur.execute(
                """
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
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_camera_views_camera_key ON camera_views(camera_key)"
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_camera_views_camera_ha_preset
                ON camera_views(camera_key, ha_preset_id)
                """
            )
            # Keep this migration conservative: only rewrite preview interval values
            # when they still match historical defaults.
            preview_enabled_row = conn.execute(
                "SELECT v FROM kv WHERE k='ui.preview_enabled_interval_s' LIMIT 1"
            ).fetchone()
            preview_disabled_row = conn.execute(
                "SELECT v FROM kv WHERE k='ui.preview_disabled_interval_s' LIMIT 1"
            ).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if preview_enabled_row is not None and str(preview_enabled_row[0]).strip() == "5":
                cur.execute(
                    "UPDATE kv SET v=?, updated_ts=? WHERE k='ui.preview_enabled_interval_s'",
                    ("2", now),
                )
            if preview_disabled_row is not None and str(preview_disabled_row[0]).strip() == "600":
                cur.execute(
                    "UPDATE kv SET v=?, updated_ts=? WHERE k='ui.preview_disabled_interval_s'",
                    ("60", now),
                )
            # Normalize legacy purpose values to the new enum set.
            cur.execute(
                "UPDATE cameras SET purpose='doorbell' WHERE purpose='doorbell_entry'"
            )
            cur.execute(
                "UPDATE cameras SET purpose='general' WHERE purpose='indoor_general'"
            )
            cur.execute(
                "UPDATE cameras SET purpose='general' WHERE purpose='other'"
            )
            event_columns = conn.execute("PRAGMA table_info(events)").fetchall()
            event_column_names = {str(row[1]) for row in event_columns}
            if "frigate_score" not in event_column_names:
                cur.execute("ALTER TABLE events ADD COLUMN frigate_score REAL")
            if "suppressed_by_event_id" not in event_column_names:
                cur.execute("ALTER TABLE events ADD COLUMN suppressed_by_event_id TEXT")
            if "ai_confidence" not in event_column_names:
                cur.execute("ALTER TABLE events ADD COLUMN ai_confidence REAL")
            if "ai_reason" not in event_column_names:
                cur.execute("ALTER TABLE events ADD COLUMN ai_reason TEXT")
            if "risk_score" not in event_column_names:
                cur.execute("ALTER TABLE events ADD COLUMN risk_score REAL")
            cur.execute(
                """
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
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_event_id ON embeddings_cache(event_id)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_embeddings_camera_created ON embeddings_cache(camera, created_ts)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_created_ts ON embeddings_cache(created_ts)")
        finally:
            cur.close()
