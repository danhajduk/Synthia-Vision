"""Persistent state helpers with atomic JSON writes."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

LOGGER = logging.getLogger("synthia_vision")


class StateManager:
    """Read/write state file atomically."""

    def __init__(self, state_file: Path) -> None:
        self._state_file = state_file
        self._lock = Lock()

    def load_state(self) -> dict[str, Any]:
        with self._lock:
            if not self._state_file.exists():
                return {}
            try:
                with self._state_file.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                LOGGER.warning("Could not read state file %s (%s); using empty state", self._state_file, exc)
                return {}

            if not isinstance(loaded, dict):
                LOGGER.warning("State file %s root is not an object; using empty state", self._state_file)
                return {}
            return loaded

    def save_state_atomic(self, state: Mapping[str, Any]) -> None:
        with self._lock:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            temp_fd, temp_path = tempfile.mkstemp(
                prefix=f"{self._state_file.name}.",
                suffix=".tmp",
                dir=str(self._state_file.parent),
            )
            try:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as handle:
                    json.dump(state, handle, indent=2, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self._state_file)
            finally:
                try:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                except OSError:
                    pass
