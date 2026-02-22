"""SQLite user persistence for auth/session bootstrap."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.auth.passwords import hash_password, verify_password


@dataclass(slots=True)
class UserStore:
    db_path: Path

    def count_users(self) -> int:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return int(row[0]) if row else 0

    def has_admin(self) -> bool:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            row = conn.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone()
        return row is not None

    def set_setup_completed(self, completed: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        value = "1" if completed else "0"
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                """
                INSERT INTO kv(k, v, updated_ts) VALUES('setup.completed', ?, ?)
                ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_ts=excluded.updated_ts
                """,
                (value, now),
            )
            conn.commit()

    def create_user(self, *, username: str, password: str, role: str) -> None:
        if role not in {"admin", "guest"}:
            raise ValueError("role must be admin or guest")
        password_hash = hash_password(password)
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute(
                """
                INSERT INTO users(username, password_hash, role, created_ts, last_login_ts)
                VALUES(?, ?, ?, ?, NULL)
                """,
                (username.strip(), password_hash, role, now),
            )
            conn.commit()

    def create_admin_if_no_users(self, *, username: str, password: str) -> bool:
        username = username.strip()
        if not username:
            raise ValueError("username is required")
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            count_row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
            count = int(count_row[0]) if count_row else 0
            if count > 0:
                return False
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO users(username, password_hash, role, created_ts, last_login_ts)
                VALUES(?, ?, 'admin', ?, NULL)
                """,
                (username, hash_password(password), now),
            )
            conn.execute(
                """
                INSERT INTO kv(k, v, updated_ts) VALUES('setup.completed', '1', ?)
                ON CONFLICT(k) DO UPDATE SET v='1', updated_ts=excluded.updated_ts
                """,
                (now,),
            )
            conn.commit()
            return True

    def authenticate(self, *, username: str, password: str) -> tuple[bool, str | None]:
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000;")
            row = conn.execute(
                "SELECT password_hash, role FROM users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
            if row is None:
                return (False, None)
            password_hash, role = str(row[0]), str(row[1])
            if not verify_password(password, password_hash):
                return (False, None)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE users SET last_login_ts = ? WHERE username = ?",
                (now, username.strip()),
            )
            conn.commit()
            return (True, role)
