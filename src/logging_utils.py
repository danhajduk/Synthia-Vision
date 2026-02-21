"""Logging setup utilities."""

from __future__ import annotations

import logging
from pathlib import Path

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(
    *,
    default_level: str = "INFO",
    file_path: str | None = None,
    json_logs: bool = False,
    component_levels: dict[str, str] | None = None,
) -> None:
    """Configure process-wide logging with optional per-component overrides."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if file_path:
        try:
            file_target = Path(file_path)
            file_target.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(file_target, encoding="utf-8"))
        except OSError:
            # Keep startup resilient if file logging path is unavailable.
            pass

    logging.basicConfig(
        level=_to_level(default_level),
        format=DEFAULT_LOG_FORMAT if not json_logs else "%(message)s",
        force=True,
        handlers=handlers,
    )
    _apply_component_levels(component_levels or {})


def _apply_component_levels(component_levels: dict[str, str]) -> None:
    logger_map = {
        "core": "synthia_vision",
        "mqtt": "synthia_vision.mqtt",
        "config": "synthia_vision.config",
        "policy": "synthia_vision.policy",
        "ai": "synthia_vision.ai",
    }
    for component, logger_name in logger_map.items():
        level = component_levels.get(component)
        if level:
            logging.getLogger(logger_name).setLevel(_to_level(level))


def _to_level(level_name: str) -> int:
    return getattr(logging, str(level_name).upper(), logging.INFO)
