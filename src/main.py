"""Application entrypoint and lifecycle wiring for Synthia Vision."""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Sequence

if __package__ is None or __package__ == "":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_settings
from src.errors import SynthiaVisionError
from src.logging_utils import configure_logging
from src.mqtt import MQTTClient

LOGGER = logging.getLogger("synthia_vision")

LifecycleHook = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class AppDependencies:
    """Container for startup/shutdown hooks as modules are implemented."""

    startup_hooks: list[LifecycleHook] = field(default_factory=list)
    shutdown_hooks: list[LifecycleHook] = field(default_factory=list)


class SynthiaVisionApp:
    """Core service runtime with graceful startup and shutdown behavior."""

    def __init__(self, dependencies: AppDependencies | None = None) -> None:
        self._dependencies = dependencies or AppDependencies()
        self._shutdown_event = asyncio.Event()
        self._is_running = False

    async def start(self) -> None:
        if self._is_running:
            return
        LOGGER.info("Starting Synthia Vision service")
        await self._run_hooks(self._dependencies.startup_hooks, "startup")
        self._is_running = True

    async def run(self) -> None:
        await self.start()
        LOGGER.info("Service is running")
        await self._shutdown_event.wait()

    async def stop(self) -> None:
        if not self._is_running:
            return
        LOGGER.info("Stopping Synthia Vision service")
        await self._run_hooks(
            list(reversed(self._dependencies.shutdown_hooks)),
            "shutdown",
        )
        self._is_running = False
        self._shutdown_event.set()
        LOGGER.info("Service stopped")

    def request_shutdown(self) -> None:
        self._shutdown_event.set()

    async def _run_hooks(self, hooks: Sequence[LifecycleHook], phase: str) -> None:
        for hook in hooks:
            hook_name = getattr(hook, "__name__", repr(hook))
            LOGGER.debug("Running %s hook: %s", phase, hook_name)
            await hook()


def _register_signal_handlers(app: SynthiaVisionApp) -> None:
    loop = asyncio.get_running_loop()

    def _on_signal(received_signal: signal.Signals) -> None:
        LOGGER.info("Received signal %s; shutting down", received_signal.name)
        app.request_shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal, sig)
        except NotImplementedError:
            signal.signal(sig, lambda _s, _f, _sig=sig: _on_signal(_sig))


async def _main_async() -> int:
    configure_logging()

    try:
        config = load_settings()
    except SynthiaVisionError as exc:
        LOGGER.error("Configuration error: %s", exc)
        return 1

    configure_logging(
        default_level=config.logging.level,
        file_path=config.logging.file,
        json_logs=config.logging.json,
        retention_days=config.logging.retention_days,
        component_levels={
            "core": config.logging.components.core,
            "mqtt": config.logging.components.mqtt,
            "config": config.logging.components.config,
            "policy": config.logging.components.policy,
            "ai": config.logging.components.ai,
        },
        component_files={
            "core": config.logging_files.core,
            "mqtt": config.logging_files.mqtt,
            "config": config.logging_files.config,
            "policy": config.logging_files.policy,
            "ai": config.logging_files.ai,
        },
    )
    LOGGER.info("Loaded configuration from config file and environment")

    mqtt_client = MQTTClient(config)
    dependencies = AppDependencies(
        startup_hooks=[mqtt_client.startup_connect, mqtt_client.startup_ready],
        shutdown_hooks=[mqtt_client.shutdown],
    )
    app = SynthiaVisionApp(dependencies=dependencies)
    _register_signal_handlers(app)

    try:
        await app.run()
        return 0
    except SynthiaVisionError as exc:
        LOGGER.error("Application error: %s", exc)
        return 1
    except Exception:
        LOGGER.exception("Unhandled fatal error in service runtime")
        return 1
    finally:
        await app.stop()


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
