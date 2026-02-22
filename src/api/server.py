"""HTTP API server for guest/admin endpoints."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from src.config import ServiceConfig
from src.db import SummaryStore


def create_guest_api_app(config: ServiceConfig):
    from fastapi import FastAPI

    store = SummaryStore(config.paths.db_file)
    app = FastAPI(title="Synthia Vision API", version="0.1.0")

    @app.get("/api/status")
    async def api_status():
        return store.get_status_summary()

    @app.get("/api/metrics/summary")
    async def api_metrics_summary():
        return {"metrics": store.get_metrics_summary()}

    @app.get("/api/cameras/summary")
    async def api_cameras_summary():
        return store.get_cameras_summary()

    return app


@dataclass(slots=True)
class APIServer:
    config: ServiceConfig
    host: str = "0.0.0.0"
    port: int = 8080

    def __post_init__(self) -> None:
        self.host = os.getenv("SYNTHIA_API_HOST", self.host)
        self.port = int(os.getenv("SYNTHIA_API_PORT", str(self.port)))
        self._server = None
        self._server_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        import uvicorn

        app = create_guest_api_app(self.config)
        cfg = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=False,
            loop="asyncio",
        )
        self._server = uvicorn.Server(cfg)
        self._server_task = asyncio.create_task(self._server.serve(), name="api-server")
        await asyncio.sleep(0.05)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            await self._server_task
            self._server_task = None
