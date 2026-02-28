"""SQLite journaling helpers for events, metrics, and errors."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.models import FrigateEvent


@dataclass(slots=True)
class EventStore:
    db_path: Path

    def upsert_event(
        self,
        *,
        event: FrigateEvent,
        accepted: bool,
        reject_reason: str | None = None,
        cooldown_remaining_s: float | None = None,
        dedupe_hit: bool = False,
        suppressed_by_event_id: str | None = None,
        result_status: str | None = None,
        action: str | None = None,
        subject_type: str | None = None,
        frigate_score: float | None = None,
        confidence: float | None = None,
        description: str | None = None,
        snapshot_bytes: int | None = None,
        image_width: int | None = None,
        image_height: int | None = None,
        vision_detail: str | None = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        ts_iso = datetime.fromtimestamp(
            float(event.event_ts if event.event_ts is not None else datetime.now().timestamp()),
            tz=timezone.utc,
        ).isoformat()
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                """
                INSERT INTO events(
                  event_id, ts, camera, event_type, accepted, reject_reason, cooldown_remaining_s, dedupe_hit, suppressed_by_event_id,
                  result_status, action, subject_type, frigate_score, confidence, description,
                  snapshot_bytes, image_width, image_height, vision_detail, created_ts
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                  ts=excluded.ts,
                  camera=excluded.camera,
                  event_type=excluded.event_type,
                  accepted=excluded.accepted,
                  reject_reason=excluded.reject_reason,
                  cooldown_remaining_s=excluded.cooldown_remaining_s,
                  dedupe_hit=excluded.dedupe_hit,
                  suppressed_by_event_id=excluded.suppressed_by_event_id,
                  result_status=excluded.result_status,
                  action=excluded.action,
                  subject_type=excluded.subject_type,
                  frigate_score=excluded.frigate_score,
                  confidence=excluded.confidence,
                  description=excluded.description,
                  snapshot_bytes=excluded.snapshot_bytes,
                  image_width=excluded.image_width,
                  image_height=excluded.image_height,
                  vision_detail=excluded.vision_detail
                """,
                (
                    event.event_id,
                    ts_iso,
                    event.camera,
                    event.event_type,
                    1 if accepted else 0,
                    reject_reason,
                    cooldown_remaining_s,
                    1 if dedupe_hit else 0,
                    suppressed_by_event_id,
                    result_status,
                    action,
                    subject_type,
                    event.score if frigate_score is None else frigate_score,
                    confidence,
                    description,
                    snapshot_bytes,
                    image_width,
                    image_height,
                    vision_detail,
                    now_iso,
                ),
            )
            conn.commit()

    def insert_metric(
        self,
        *,
        event_id: str,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        cost_usd: float | None = None,
        model: str | None = None,
        phash: str | None = None,
        phash_distance: int | None = None,
        skipped_openai_reason: str | None = None,
        latency_snapshot_ms: float | None = None,
        latency_openai_ms: float | None = None,
        latency_total_ms: float | None = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                """
                INSERT INTO metrics(
                  event_id, latency_snapshot_ms, latency_openai_ms, latency_total_ms,
                  prompt_tokens, completion_tokens, cost_usd, model,
                  phash, phash_distance, skipped_openai_reason, created_ts
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    latency_snapshot_ms,
                    latency_openai_ms,
                    latency_total_ms,
                    prompt_tokens,
                    completion_tokens,
                    cost_usd,
                    model,
                    phash,
                    phash_distance,
                    skipped_openai_reason,
                    now_iso,
                ),
            )
            conn.commit()

    def insert_error(
        self,
        *,
        component: str,
        message: str,
        detail: str | None = None,
        event_id: str | None = None,
        camera: str | None = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                """
                INSERT INTO errors(ts, component, message, detail, event_id, camera)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (now_iso, component, message, detail, event_id, camera),
            )
            conn.commit()
