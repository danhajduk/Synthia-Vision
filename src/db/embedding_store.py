"""SQLite helpers for embedding cache metadata and retention pruning."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(slots=True)
class EmbeddingStore:
    db_path: Path

    def insert_embedding_cache(
        self,
        *,
        event_id: str,
        camera: str,
        model: str,
        snapshot_sha256: str | None,
        vector: list[float] | None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        vector_json = json.dumps(vector, separators=(",", ":")) if vector is not None else None
        embedding_dim = len(vector) if vector is not None else None
        vector_stored = 1 if vector is not None else 0
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                """
                INSERT INTO embeddings_cache(
                  event_id, camera, model, snapshot_sha256, embedding_dim, vector_json, vector_stored, created_ts
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    camera,
                    model,
                    snapshot_sha256,
                    embedding_dim,
                    vector_json,
                    vector_stored,
                    now_iso,
                ),
            )
            conn.commit()

    def prune(self, *, retention_days: int, max_rows: int) -> None:
        retention_days = max(1, int(retention_days))
        max_rows = max(1, int(max_rows))
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                "DELETE FROM embeddings_cache WHERE created_ts < ?",
                (cutoff_iso,),
            )
            row = conn.execute("SELECT COUNT(*) FROM embeddings_cache").fetchone()
            count = int(row[0]) if row is not None else 0
            overflow = max(0, count - max_rows)
            if overflow > 0:
                conn.execute(
                    """
                    DELETE FROM embeddings_cache
                    WHERE id IN (
                      SELECT id FROM embeddings_cache
                      ORDER BY created_ts ASC, id ASC
                      LIMIT ?
                    )
                    """,
                    (overflow,),
                )
            conn.commit()
