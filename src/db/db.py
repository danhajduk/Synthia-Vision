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
