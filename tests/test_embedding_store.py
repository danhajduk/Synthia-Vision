"""Tests for embeddings cache metadata store and pruning behavior."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.db import DatabaseBootstrap, EmbeddingStore, EventStore
from src.models import FrigateEvent


class EmbeddingStoreTests(unittest.TestCase):
    def test_insert_metadata_without_vector_and_prune(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()
            event_store = EventStore(db_path)
            event_store.upsert_event(
                event=FrigateEvent(
                    event_id="evt-1",
                    camera="doorbell",
                    label="person",
                    event_type="end",
                    event_ts=1700000000.0,
                ),
                accepted=True,
                result_status="ok",
            )
            store = EmbeddingStore(db_path)
            store.insert_embedding_cache(
                event_id="evt-1",
                camera="doorbell",
                model="text-embedding-3-small",
                snapshot_sha256="abc123",
                vector=None,
            )
            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                row = conn.execute(
                    """
                    SELECT event_id, camera, model, snapshot_sha256, embedding_dim, vector_json, vector_stored
                    FROM embeddings_cache
                    WHERE event_id='evt-1'
                    """
                ).fetchone()
            self.assertEqual(
                row,
                ("evt-1", "doorbell", "text-embedding-3-small", "abc123", None, None, 0),
            )

            store.prune(retention_days=30, max_rows=1)
            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                count = int(conn.execute("SELECT COUNT(*) FROM embeddings_cache").fetchone()[0])
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
