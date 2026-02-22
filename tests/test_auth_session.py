"""Tests for signed session tokens and role checks."""

from __future__ import annotations

import unittest

from src.auth.session import SessionManager


class SessionManagerTests(unittest.TestCase):
    def test_create_and_parse_token(self) -> None:
        manager = SessionManager(secret="test-secret", ttl_seconds=600)
        token = manager.create_token(username="admin", role="admin", now=1000)
        principal = manager.parse_token(token, now=1100)
        self.assertIsNotNone(principal)
        assert principal is not None
        self.assertEqual(principal.username, "admin")
        self.assertEqual(principal.role, "admin")
        self.assertEqual(principal.issued_at, 1000)
        self.assertEqual(principal.expires_at, 1600)

    def test_rejects_tampered_or_expired_token(self) -> None:
        manager = SessionManager(secret="test-secret", ttl_seconds=60)
        token = manager.create_token(username="guest", role="guest", now=1000)
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        self.assertIsNone(manager.parse_token(tampered, now=1010))
        self.assertIsNone(manager.parse_token(token, now=2000))

    def test_require_role(self) -> None:
        manager = SessionManager(secret="test-secret")
        admin = manager.parse_token(
            manager.create_token(username="a", role="admin", now=1000),
            now=1001,
        )
        guest = manager.parse_token(
            manager.create_token(username="g", role="guest", now=1000),
            now=1001,
        )
        self.assertTrue(manager.require_role(admin, "admin"))
        self.assertTrue(manager.require_role(admin, "guest"))
        self.assertFalse(manager.require_role(guest, "admin"))
        self.assertTrue(manager.require_role(guest, "guest"))


if __name__ == "__main__":
    unittest.main()
