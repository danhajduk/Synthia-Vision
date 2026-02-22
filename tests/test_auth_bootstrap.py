"""Tests for auth password hashing and first-run bootstrap."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.auth import FirstRunBootstrap, UserStore, hash_password, verify_password
from src.db import DatabaseBootstrap


class AuthBootstrapTests(unittest.TestCase):
    def test_password_hash_roundtrip(self) -> None:
        encoded = hash_password("supersecurepass")
        self.assertTrue(verify_password("supersecurepass", encoded))
        self.assertFalse(verify_password("wrongpass", encoded))

    def test_create_admin_from_env_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "synthia_vision.db"
            DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()

            previous_admin_password = os.environ.get("ADMIN_PASSWORD")
            previous_admin_username = os.environ.get("ADMIN_USERNAME")
            os.environ["ADMIN_PASSWORD"] = "supersecurepass"
            os.environ["ADMIN_USERNAME"] = "admin"
            try:
                bootstrap = FirstRunBootstrap(db_path=db_path)
                self.assertTrue(bootstrap.create_admin_from_env_if_needed())
                self.assertFalse(bootstrap.create_admin_from_env_if_needed())
            finally:
                if previous_admin_password is None:
                    os.environ.pop("ADMIN_PASSWORD", None)
                else:
                    os.environ["ADMIN_PASSWORD"] = previous_admin_password
                if previous_admin_username is None:
                    os.environ.pop("ADMIN_USERNAME", None)
                else:
                    os.environ["ADMIN_USERNAME"] = previous_admin_username

            store = UserStore(db_path)
            self.assertTrue(store.has_admin())
            ok, role = store.authenticate(username="admin", password="supersecurepass")
            self.assertTrue(ok)
            self.assertEqual(role, "admin")

            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                kv = conn.execute("SELECT v FROM kv WHERE k='setup.completed'").fetchone()
            self.assertIsNotNone(kv)
            self.assertEqual(kv[0], "1")


if __name__ == "__main__":
    unittest.main()
