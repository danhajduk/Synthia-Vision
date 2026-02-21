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
    component_files: dict[str, str | None] | None = None,
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
    _apply_component_file_handlers(component_files or {}, json_logs=json_logs)


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


def _apply_component_file_handlers(
    component_files: dict[str, str | None],
    *,
    json_logs: bool,
) -> None:
    logger_map = {
        "core": "synthia_vision",
        "mqtt": "synthia_vision.mqtt",
        "config": "synthia_vision.config",
        "policy": "synthia_vision.policy",
        "ai": "synthia_vision.ai",
    }
    formatter = logging.Formatter(DEFAULT_LOG_FORMAT if not json_logs else "%(message)s")

    for component, logger_name in logger_map.items():
        file_path = component_files.get(component)
        if not file_path:
            continue
        handler = _create_file_handler(file_path)
        if handler is None:
            continue
        handler.setFormatter(formatter)
        logger = logging.getLogger(logger_name)
        logger.addHandler(handler)
        logger.propagate = True


def _create_file_handler(file_path: str) -> logging.Handler | None:
    try:
        file_target = Path(file_path)
        file_target.parent.mkdir(parents=True, exist_ok=True)
        return logging.FileHandler(file_target, encoding="utf-8")
    except OSError:
        return None


def _to_level(level_name: str) -> int:
    return getattr(logging, str(level_name).upper(), logging.INFO)
