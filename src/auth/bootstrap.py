"""First-run auth bootstrap behavior."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from src.auth.user_store import UserStore

LOGGER = logging.getLogger("synthia_vision.auth")


@dataclass(slots=True)
class FirstRunBootstrap:
    db_path: Path

    def create_admin_from_env_if_needed(self) -> bool:
        password = os.getenv("ADMIN_PASSWORD", "").strip()
        username = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
        if not password:
            LOGGER.info("ADMIN_PASSWORD not set; skipping first-run admin bootstrap")
            return False
        store = UserStore(self.db_path)
        created = store.create_admin_if_no_users(username=username, password=password)
        if created:
            LOGGER.info("Created first admin user from ADMIN_PASSWORD bootstrap username=%s", username)
        else:
            LOGGER.info("Skipped admin bootstrap because users already exist")
        return created
