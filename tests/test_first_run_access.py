"""Tests for first-run setup access policy."""

from __future__ import annotations

import os
import unittest

from src.auth import is_first_run_request_allowed


class FirstRunAccessTests(unittest.TestCase):
    def test_localhost_is_allowed_without_token(self) -> None:
        self.assertTrue(
            is_first_run_request_allowed(remote_host="127.0.0.1", provided_token=None)
        )
        self.assertTrue(
            is_first_run_request_allowed(remote_host="::1", provided_token=None)
        )

    def test_remote_requires_matching_token(self) -> None:
        previous = os.environ.get("FIRST_RUN_TOKEN")
        os.environ["FIRST_RUN_TOKEN"] = "abc123"
        try:
            self.assertFalse(
                is_first_run_request_allowed(remote_host="10.0.0.50", provided_token=None)
            )
            self.assertFalse(
                is_first_run_request_allowed(remote_host="10.0.0.50", provided_token="wrong")
            )
            self.assertTrue(
                is_first_run_request_allowed(remote_host="10.0.0.50", provided_token="abc123")
            )
        finally:
            if previous is None:
                os.environ.pop("FIRST_RUN_TOKEN", None)
            else:
                os.environ["FIRST_RUN_TOKEN"] = previous


if __name__ == "__main__":
    unittest.main()
