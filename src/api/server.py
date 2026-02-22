"""HTTP API server for guest/admin endpoints."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from src.config import ServiceConfig
from src.db import AdminStore, SummaryStore


def create_guest_api_app(config: ServiceConfig):
    from fastapi import FastAPI, HTTPException

    summary_store = SummaryStore(config.paths.db_file)
    admin_store = AdminStore(config.paths.db_file)
    app = FastAPI(title="Synthia Vision API", version="0.1.0")

    @app.get("/api/status")
    async def api_status():
        return summary_store.get_status_summary()

    @app.get("/api/metrics/summary")
    async def api_metrics_summary():
        return {"metrics": summary_store.get_metrics_summary()}

    @app.get("/api/cameras/summary")
    async def api_cameras_summary():
        return summary_store.get_cameras_summary()

    @app.get("/api/events")
    async def api_events(
        limit: int = 100,
        offset: int = 0,
        camera: str | None = None,
        accepted: bool | None = None,
    ):
        return admin_store.list_events(
            limit=limit,
            offset=offset,
            camera=camera,
            accepted=accepted,
        )

    @app.get("/api/events/{event_id}")
    async def api_event_detail(event_id: str):
        item = admin_store.get_event(event_id)
        if item is None:
            raise HTTPException(status_code=404, detail="event not found")
        return item

    @app.get("/api/cameras")
    async def api_cameras():
        return admin_store.list_cameras()

    @app.post("/api/cameras/{camera_key}")
    async def api_camera_update(camera_key: str, payload: dict):
        try:
            return admin_store.update_camera(camera_key, payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/control/{name}")
    async def api_control_update(name: str, payload: dict):
        if "value" not in payload:
            raise HTTPException(status_code=400, detail="payload.value is required")
        try:
            return admin_store.update_control(name, payload["value"])
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/errors")
    async def api_errors(limit: int = 100, offset: int = 0):
        return admin_store.list_errors(limit=limit, offset=offset)

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
