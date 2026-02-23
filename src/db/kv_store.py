"""Small key/value helpers for SQLite-backed runtime state."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def kv_set(db_path: Path, key: str, value: str) -> None:
    """Insert or update a KV entry with current UTC timestamp."""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(db_path), timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute(
            """
            INSERT INTO kv(k, v, updated_ts) VALUES(?, ?, ?)
            ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_ts = excluded.updated_ts
            """,
            (str(key), str(value), now),
        )
        conn.commit()


def kv_get(db_path: Path, key: str) -> str | None:
    """Read a KV value by key."""
    with sqlite3.connect(str(db_path), timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000;")
        row = conn.execute("SELECT v FROM kv WHERE k = ?", (str(key),)).fetchone()
    if row is None:
        return None
    return str(row[0])
