"""Logging setup utilities."""

from __future__ import annotations

import logging

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure process-wide logging with a consistent format."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=DEFAULT_LOG_FORMAT,
        force=True,
    )
