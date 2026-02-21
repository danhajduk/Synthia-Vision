"""Logging setup utilities."""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import re

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
DATE_SUFFIX_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DailyNamedRotatingFileHandler(TimedRotatingFileHandler):
    """Rotate at midnight and archive as `name-YYYY-MM-DD.log`."""

    def __init__(self, file_target: Path, backup_count: int, encoding: str = "utf-8") -> None:
        super().__init__(
            filename=str(file_target),
            when="midnight",
            interval=1,
            backupCount=backup_count,
            encoding=encoding,
        )
        self.suffix = "%Y-%m-%d"
        self._file_target = file_target
        self._archive_prefix = f"{file_target.stem}-"
        self._archive_suffix = file_target.suffix or ".log"

    def rotation_filename(self, default_name: str) -> str:
        default_path = Path(default_name)
        date_part = default_path.name.rsplit(".", 1)[-1]
        return str(
            self._file_target.parent
            / f"{self._archive_prefix}{date_part}{self._archive_suffix}"
        )

    def getFilesToDelete(self) -> list[str]:
        candidates: list[str] = []
        for path in self._file_target.parent.glob(f"{self._archive_prefix}*{self._archive_suffix}"):
            name = path.name
            if not name.startswith(self._archive_prefix) or not name.endswith(self._archive_suffix):
                continue
            date_part = name[len(self._archive_prefix) : -len(self._archive_suffix)]
            if DATE_SUFFIX_PATTERN.fullmatch(date_part):
                candidates.append(str(path))

        candidates.sort()
        if len(candidates) <= self.backupCount:
            return []
        return candidates[: len(candidates) - self.backupCount]


def configure_logging(
    *,
    default_level: str = "INFO",
    file_path: str | None = None,
    json_logs: bool = False,
    retention_days: int = 14,
    component_levels: dict[str, str] | None = None,
    component_files: dict[str, str | None] | None = None,
) -> None:
    """Configure process-wide logging with optional per-component overrides."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if file_path:
        file_handler = _create_rotating_file_handler(
            file_path,
            retention_days=retention_days,
        )
        if file_handler is not None:
            handlers.append(file_handler)

    logging.basicConfig(
        level=_to_level(default_level),
        format=DEFAULT_LOG_FORMAT if not json_logs else "%(message)s",
        force=True,
        handlers=handlers,
    )
    _apply_component_levels(component_levels or {})
    _apply_component_file_handlers(
        component_files or {},
        json_logs=json_logs,
        retention_days=retention_days,
    )


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
    retention_days: int,
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
        handler = _create_rotating_file_handler(
            file_path,
            retention_days=retention_days,
        )
        if handler is None:
            continue
        handler.setFormatter(formatter)
        logger = logging.getLogger(logger_name)
        logger.addHandler(handler)
        logger.propagate = True


def _create_rotating_file_handler(
    file_path: str,
    *,
    retention_days: int,
) -> logging.Handler | None:
    try:
        file_target = Path(file_path)
        file_target.parent.mkdir(parents=True, exist_ok=True)
        return DailyNamedRotatingFileHandler(
            file_target=file_target,
            backup_count=max(1, retention_days),
            encoding="utf-8",
        )
    except OSError:
        return None


def _to_level(level_name: str) -> int:
    return getattr(logging, str(level_name).upper(), logging.INFO)
