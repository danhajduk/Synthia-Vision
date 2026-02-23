"""Frigate API helpers."""

from src.frigate.client import FrigateClient
from src.frigate.discovery_sync import sync_discovered_cameras_from_config

__all__ = ["FrigateClient", "sync_discovered_cameras_from_config"]
