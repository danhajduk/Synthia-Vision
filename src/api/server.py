"""HTTP API server for guest/admin endpoints."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from src.config import ServiceConfig
from src.db import AdminStore, SummaryStore
from src.auth import SessionManager, UserStore
from src.auth.session import (
    SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE,
    SESSION_TTL_SECONDS,
)


def create_guest_api_app(config: ServiceConfig):
    from fastapi import Cookie, FastAPI, HTTPException, Response

    summary_store = SummaryStore(config.paths.db_file)
    admin_store = AdminStore(config.paths.db_file)
    user_store = UserStore(config.paths.db_file)
    session_secret = os.getenv("SYNTHIA_SESSION_SECRET", f"{config.service.slug}-dev-secret")
    session_manager = SessionManager(secret=session_secret, ttl_seconds=SESSION_TTL_SECONDS)
    app = FastAPI(title="Synthia Vision API", version="0.1.0")

    def _session_principal(raw_token: str | None):
        if not raw_token:
            return None
        return session_manager.parse_token(raw_token)

    def _require_admin(raw_token: str | None) -> None:
        principal = _session_principal(raw_token)
        if not session_manager.require_role(principal, "admin"):
            raise HTTPException(status_code=401, detail="admin authentication required")

    @app.post("/api/auth/login")
    async def api_auth_login(payload: dict, response: Response):
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        ok, role = user_store.authenticate(username=username, password=password)
        if not ok or role is None:
            raise HTTPException(status_code=401, detail="invalid credentials")
        token = session_manager.create_token(username=username, role=role)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            httponly=SESSION_COOKIE_HTTPONLY,
            samesite=SESSION_COOKIE_SAMESITE,
            secure=SESSION_COOKIE_SECURE,
            max_age=SESSION_TTL_SECONDS,
            path="/",
        )
        return {"ok": True, "role": role}

    @app.post("/api/auth/logout")
    async def api_auth_logout(response: Response):
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/auth/me")
    async def api_auth_me(
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        principal = _session_principal(session_token)
        if principal is None:
            return {"authenticated": False}
        return {
            "authenticated": True,
            "username": principal.username,
            "role": principal.role,
            "expires_at": principal.expires_at,
        }

    @app.get("/api/status")
    async def api_status():
        return summary_store.get_guest_status_payload()

    @app.get("/api/metrics/summary")
    async def api_metrics_summary():
        return {"metrics": summary_store.get_guest_metrics_payload()}

    @app.get("/api/cameras/summary")
    async def api_cameras_summary():
        return summary_store.get_guest_cameras_payload()

    @app.get("/api/events")
    async def api_events(
        limit: int = 100,
        offset: int = 0,
        camera: str | None = None,
        accepted: bool | None = None,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        return admin_store.list_events(
            limit=limit,
            offset=offset,
            camera=camera,
            accepted=accepted,
        )

    @app.get("/api/events/{event_id}")
    async def api_event_detail(
        event_id: str,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        item = admin_store.get_event(event_id)
        if item is None:
            raise HTTPException(status_code=404, detail="event not found")
        return item

    @app.get("/api/cameras")
    async def api_cameras(
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        return admin_store.list_cameras()

    @app.post("/api/cameras/{camera_key}")
    async def api_camera_update(
        camera_key: str,
        payload: dict,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        try:
            return admin_store.update_camera(camera_key, payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/control/{name}")
    async def api_control_update(
        name: str,
        payload: dict,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        if "value" not in payload:
            raise HTTPException(status_code=400, detail="payload.value is required")
        try:
            return admin_store.update_control(name, payload["value"])
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/errors")
    async def api_errors(
        limit: int = 100,
        offset: int = 0,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
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
