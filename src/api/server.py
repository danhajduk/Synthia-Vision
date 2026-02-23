"""HTTP API server for guest/admin endpoints."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

try:
    from fastapi import Cookie, FastAPI, HTTPException, Request, Response
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
except ModuleNotFoundError:  # pragma: no cover - optional API dependency
    Cookie = FastAPI = HTTPException = Request = Response = None  # type: ignore[assignment]
    HTMLResponse = RedirectResponse = StaticFiles = Jinja2Templates = None  # type: ignore[assignment]

from src.config import ServiceConfig
from src.db import AdminStore, DatabaseBootstrap, SummaryStore
from src.auth import FirstRunBootstrap, SessionManager, UserStore
from src.snapshot_manager import SnapshotManager
from src.auth.session import (
    SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE,
    SESSION_TTL_SECONDS,
)


def create_guest_api_app(config: ServiceConfig):
    if (
        FastAPI is None
        or Cookie is None
        or HTTPException is None
        or Request is None
        or Response is None
        or HTMLResponse is None
        or RedirectResponse is None
        or StaticFiles is None
        or Jinja2Templates is None
    ):
        raise ModuleNotFoundError("fastapi and jinja2 are required for API server")

    # Ensure DB schema/seed exists even when API app is started standalone.
    DatabaseBootstrap(db_path=config.paths.db_file).initialize()

    summary_store = SummaryStore(config.paths.db_file)
    admin_store = AdminStore(config.paths.db_file)
    user_store = UserStore(config.paths.db_file)
    first_run_bootstrap = FirstRunBootstrap(config.paths.db_file)
    try:
        snapshot_manager = SnapshotManager(config)
    except Exception:
        # Keep API boot resilient for tests/minimal configs where Frigate config
        # is intentionally omitted.
        snapshot_manager = None
    preview_cache: dict[str, tuple[float, bytes]] = {}
    runtime_overrides: dict[str, Any] = {}
    runtime_camera_overrides: dict[str, dict[str, Any]] = {}
    session_secret = os.getenv("SYNTHIA_SESSION_SECRET", f"{config.service.slug}-dev-secret")
    session_manager = SessionManager(secret=session_secret, ttl_seconds=SESSION_TTL_SECONDS)
    app = FastAPI(title="Synthia Vision API", version="0.1.0")

    ADMIN_SETTING_KEYS = [
        "budget.monthly_limit_usd",
        "policy.defaults.confidence_threshold",
        "policy.modes.doorbell_only",
        "ai.modes.high_precision",
        "ai.defaults.vision_detail",
        "policy.smart_update.phash_threshold_default",
        "policy.smart_update.phash_threshold_update",
        "ui.subtitle",
        "ui.preview_enabled",
        "ui.preview_enabled_interval_s",
        "ui.preview_disabled_interval_s",
        "ui.preview_max_active",
    ]

    ui_root = Path(__file__).resolve().parent.parent / "ui"
    templates = Jinja2Templates(directory=str(ui_root / "templates"))
    app.mount("/ui/static", StaticFiles(directory=str(ui_root / "static")), name="ui-static")

    def _session_principal(raw_token: str | None):
        if not raw_token:
            return None
        return session_manager.parse_token(raw_token)

    def _require_admin(raw_token: str | None) -> None:
        principal = _session_principal(raw_token)
        if not session_manager.require_role(principal, "admin"):
            raise HTTPException(status_code=401, detail="admin authentication required")

    def _ui_admin_or_redirect(raw_token: str | None):
        principal = _session_principal(raw_token)
        if not session_manager.require_role(principal, "admin"):
            return None
        return principal

    def _to_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(int(value))
        text = str(value).strip().lower()
        if text in {"1", "true", "on", "yes"}:
            return True
        if text in {"0", "false", "off", "no"}:
            return False
        return default

    def _to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _get_effective_settings() -> tuple[dict[str, str], dict[str, str]]:
        persisted = admin_store.get_kv_many(ADMIN_SETTING_KEYS)
        merged = dict(persisted)
        for key, value in runtime_overrides.items():
            merged[key] = str(value)
        return persisted, merged

    def _get_admin_settings() -> dict[str, Any]:
        persisted, merged = _get_effective_settings()
        return {
            "persisted": persisted,
            "runtime": merged,
            "runtime_overrides": dict(runtime_overrides),
            "unsaved_changes": bool(runtime_overrides) or bool(runtime_camera_overrides),
        }

    def _normalize_setting_payload(payload: dict[str, Any]) -> dict[str, str]:
        updates: dict[str, str] = {}
        for key in ADMIN_SETTING_KEYS:
            if key not in payload:
                continue
            value = payload.get(key)
            if key in {"ui.preview_enabled", "policy.modes.doorbell_only", "ai.modes.high_precision"}:
                updates[key] = "1" if _to_bool(value, False) else "0"
            elif key in {
                "ui.preview_enabled_interval_s",
                "ui.preview_disabled_interval_s",
                "ui.preview_max_active",
            }:
                updates[key] = str(max(1, _to_int(value, 1)))
            elif key in {
                "policy.smart_update.phash_threshold_default",
                "policy.smart_update.phash_threshold_update",
            }:
                updates[key] = str(max(0, _to_int(value, 0)))
            elif key == "policy.defaults.confidence_threshold":
                try:
                    parsed = float(value)
                except Exception as exc:
                    raise ValueError("policy.defaults.confidence_threshold must be numeric") from exc
                if parsed > 1.0:
                    parsed = parsed / 100.0
                updates[key] = f"{max(0.0, min(1.0, parsed)):.4f}".rstrip("0").rstrip(".")
            elif key == "budget.monthly_limit_usd":
                try:
                    parsed = float(value)
                except Exception as exc:
                    raise ValueError("budget.monthly_limit_usd must be numeric") from exc
                updates[key] = f"{max(0.0, parsed):.2f}"
            elif key == "ai.defaults.vision_detail":
                detail = str(value).strip().lower()
                updates[key] = detail if detail in {"low", "high", "auto"} else "low"
            else:
                updates[key] = str(value)
        return updates

    def _normalize_camera_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        updates: dict[str, Any] = {}
        if "display_name" in payload:
            display_name = str(payload.get("display_name", "")).strip()
            if display_name:
                updates["display_name"] = display_name
        if "enabled" in payload:
            updates["enabled"] = _to_bool(payload.get("enabled"), False)
        if "process_end_events" in payload:
            updates["process_end_events"] = _to_bool(payload.get("process_end_events"), True)
        if "process_update_events" in payload:
            updates["process_update_events"] = _to_bool(payload.get("process_update_events"), True)
        if "guest_preview_enabled" in payload:
            updates["guest_preview_enabled"] = _to_bool(payload.get("guest_preview_enabled"), False)
        if "updates_per_event" in payload:
            try:
                updates_per_event = int(payload.get("updates_per_event"))
            except Exception as exc:
                raise ValueError("updates_per_event must be an integer") from exc
            updates["updates_per_event"] = max(1, min(2, updates_per_event))
        if "prompt_preset" in payload:
            prompt_preset = payload.get("prompt_preset")
            if prompt_preset is None:
                updates["prompt_preset"] = None
            else:
                prompt_preset_str = str(prompt_preset).strip()
                updates["prompt_preset"] = prompt_preset_str if prompt_preset_str else None
        if "confidence_threshold" in payload and payload.get("confidence_threshold") not in {"", None}:
            try:
                threshold = float(payload.get("confidence_threshold"))
            except Exception as exc:
                raise ValueError("confidence_threshold must be numeric") from exc
            if threshold > 1.0:
                threshold = threshold / 100.0
            updates["confidence_threshold"] = max(0.0, min(1.0, threshold))
        if "cooldown_s" in payload and payload.get("cooldown_s") not in {"", None}:
            try:
                updates["cooldown_s"] = max(0, int(payload.get("cooldown_s")))
            except Exception as exc:
                raise ValueError("cooldown_s must be an integer") from exc
        if "vision_detail" in payload and payload.get("vision_detail") not in {"", None}:
            detail = str(payload.get("vision_detail")).strip().lower()
            if detail not in {"low", "high"}:
                raise ValueError("vision_detail must be low or high")
            updates["vision_detail"] = detail
        if "phash_threshold" in payload and payload.get("phash_threshold") not in {"", None}:
            try:
                updates["phash_threshold"] = max(0, int(payload.get("phash_threshold")))
            except Exception as exc:
                raise ValueError("phash_threshold must be an integer") from exc
        return updates

    def _overlay_camera_runtime(camera: dict[str, Any]) -> dict[str, Any]:
        key = str(camera.get("camera_key", ""))
        override = runtime_camera_overrides.get(key)
        if not override:
            return dict(camera)
        merged = dict(camera)
        for field_name, value in override.items():
            merged[field_name] = value
        return merged

    def _health_label(status: str) -> str:
        normalized = str(status).strip().lower()
        if normalized == "degraded":
            return "Degraded"
        if normalized == "disabled":
            return "Disabled"
        if normalized == "budget_blocked":
            return "Budget Blocked"
        if normalized == "enabled":
            return "Healthy"
        return "Unknown"

    def _format_money(value: Any) -> str:
        try:
            return f"${float(value):.4f}"
        except Exception:
            return "—"

    def _camera_last_label(camera: dict[str, Any]) -> str:
        action = camera.get("last_action")
        confidence = camera.get("last_confidence")
        if not action:
            return "—"
        if confidence is None:
            return str(action)
        return f"{action} ({confidence}%)"

    def _build_guest_dashboard_context() -> dict[str, Any]:
        status = summary_store.get_status_summary()
        metrics = summary_store.get_guest_metrics_payload()
        _persisted_settings, settings = _get_effective_settings()
        service_status = str(status.get("service_status", "unknown")).lower()
        cameras_raw = summary_store.get_guest_camera_cards(service_status=service_status)
        preview_enabled_global = _to_bool(settings.get("ui.preview_enabled", "1"), True)
        preview_enabled_interval_s = max(
            1,
            _to_int(settings.get("ui.preview_enabled_interval_s", "2"), 2),
        )
        preview_disabled_interval_s = max(
            1,
            _to_int(settings.get("ui.preview_disabled_interval_s", "60"), 60),
        )
        preview_max_active = max(1, _to_int(settings.get("ui.preview_max_active", "1"), 1))
        cameras = [
            {
                "camera_key": str(camera.get("camera_key", "")),
                "display_name": str(camera.get("display_name", "—")),
                "enabled": bool(camera.get("enabled", False)),
                "guest_preview_enabled": bool(camera.get("guest_preview_enabled", False)),
                "status": str(camera.get("status", "disabled")),
                "last_seen_ts": str(camera.get("last_seen_ts", "—")),
                "last_action_confidence": _camera_last_label(camera),
                "mtd_cost": _format_money(camera.get("mtd_cost", 0.0)),
            }
            for camera in (_overlay_camera_runtime(camera) for camera in cameras_raw)
        ]
        return {
            "title": config.service.name,
            "subtitle": settings.get("ui.subtitle", "OpenAI-powered camera events"),
            "kpis": {
                "health_label": _health_label(service_status),
                "health_badge": service_status.replace("_", " ").title() if service_status else "Unknown",
                "heartbeat_ts": str(status.get("heartbeat_ts") or "—"),
                "queue_depth": int(metrics.get("queue_depth", status.get("queue_depth", 0)) or 0),
                "queue_max": 50,
                "drops_today": int(metrics.get("dropped_events_total", 0)),
                "cost_today": _format_money(metrics.get("cost_daily_total", 0.0)),
                "cost_mtd": _format_money(metrics.get("cost_month2day_total", 0.0)),
                "ai_calls_today": int(metrics.get("count_today", 0)),
                "avg_cost_per_event": _format_money(metrics.get("cost_avg_per_event", 0.0)),
                "tokens_today_total": int(metrics.get("tokens_today_total", 0)),
                "avg_tokens_per_event": int(round(float(metrics.get("avg_tokens_per_event", 0.0)))),
            },
            "cameras": cameras,
            "preview": {
                "enabled": preview_enabled_global,
                "enabled_interval_s": preview_enabled_interval_s,
                "disabled_interval_s": preview_disabled_interval_s,
                "max_active": preview_max_active,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _set_session_cookie(response: Response, *, username: str, role: str) -> None:
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

    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui", status_code=307)

    @app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
    async def ui_guest_dashboard(request: Request):
        context = _build_guest_dashboard_context()
        return templates.TemplateResponse(
            request=request,
            name="guest_dashboard.html",
            context=context,
        )

    @app.get("/ui/login", response_class=HTMLResponse, include_in_schema=False)
    async def ui_login_page(
        request: Request,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        principal = _session_principal(session_token)
        if session_manager.require_role(principal, "admin"):
            return RedirectResponse(url="/ui/admin", status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "title": config.service.name,
                "error": None,
            },
        )

    @app.post("/ui/login", include_in_schema=False)
    async def ui_login_submit(request: Request):
        body = (await request.body()).decode("utf-8", errors="ignore")
        form = parse_qs(body, keep_blank_values=True)
        username = str((form.get("username") or [""])[0]).strip()
        password = str((form.get("password") or [""])[0])
        ok, role = user_store.authenticate(username=username, password=password)
        if not ok or role is None or role != "admin":
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "title": config.service.name,
                    "error": "Invalid credentials",
                },
                status_code=401,
            )
        response = RedirectResponse(url="/ui/admin", status_code=303)
        _set_session_cookie(response, username=username, role=role)
        return response

    @app.post("/ui/logout", include_in_schema=False)
    async def ui_logout() -> RedirectResponse:
        response = RedirectResponse(url="/ui", status_code=303)
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
        return response

    @app.get("/ui/admin", response_class=HTMLResponse, include_in_schema=False)
    async def ui_admin(
        request: Request,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        principal = _ui_admin_or_redirect(session_token)
        if principal is None:
            return RedirectResponse(url="/ui/login", status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="admin.html",
            context={
                "title": config.service.name,
                "username": principal.username,
            },
        )

    @app.get("/ui/setup", response_class=HTMLResponse, include_in_schema=False)
    async def ui_setup(
        request: Request,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        if _ui_admin_or_redirect(session_token) is None:
            return RedirectResponse(url="/ui/login", status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="setup.html",
            context={"title": config.service.name},
        )

    @app.get("/ui/events", response_class=HTMLResponse, include_in_schema=False)
    async def ui_events(
        request: Request,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        if _ui_admin_or_redirect(session_token) is None:
            return RedirectResponse(url="/ui/login", status_code=303)
        events = admin_store.list_events(limit=50, offset=0)
        return templates.TemplateResponse(
            request=request,
            name="events.html",
            context={"title": config.service.name, "events": events.get("items", [])},
        )

    @app.get("/ui/events/{event_id}", response_class=HTMLResponse, include_in_schema=False)
    async def ui_event_detail(
        event_id: str,
        request: Request,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        if _ui_admin_or_redirect(session_token) is None:
            return RedirectResponse(url="/ui/login", status_code=303)
        event = admin_store.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        return templates.TemplateResponse(
            request=request,
            name="event_detail.html",
            context={"title": config.service.name, "event": event},
        )

    @app.get("/ui/errors", response_class=HTMLResponse, include_in_schema=False)
    async def ui_errors(
        request: Request,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        if _ui_admin_or_redirect(session_token) is None:
            return RedirectResponse(url="/ui/login", status_code=303)
        errors = admin_store.list_errors(limit=100, offset=0)
        return templates.TemplateResponse(
            request=request,
            name="errors.html",
            context={"title": config.service.name, "errors": errors.get("items", [])},
        )

    @app.post("/api/auth/login")
    async def api_auth_login(payload: dict, response: Response):
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        ok, role = user_store.authenticate(username=username, password=password)
        if not ok or role is None:
            raise HTTPException(status_code=401, detail="invalid credentials")
        _set_session_cookie(response, username=username, role=role)
        return {"ok": True, "role": role}

    @app.post("/api/setup/first-run")
    async def api_setup_first_run(payload: dict, request: Request, response: Response):
        username = str(payload.get("username", "admin")).strip() or "admin"
        password = str(payload.get("password", ""))
        provided_token = str(payload.get("token", "")).strip() or request.headers.get(
            "X-First-Run-Token"
        )
        remote_host = request.client.host if request.client is not None else None
        if not first_run_bootstrap.is_first_run_setup_allowed(
            remote_host=remote_host,
            provided_token=provided_token,
        ):
            raise HTTPException(status_code=403, detail="first-run setup not allowed")
        if len(password) < 12:
            raise HTTPException(status_code=400, detail="password must be at least 12 characters")
        try:
            created = user_store.create_admin_if_no_users(username=username, password=password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not created:
            raise HTTPException(status_code=409, detail="admin already exists")
        user_store.set_setup_completed(True)
        _set_session_cookie(response, username=username, role="admin")
        return {"ok": True, "created": True, "username": username, "role": "admin"}

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

    @app.get("/api/cameras/{camera_key}/card")
    async def api_camera_card(camera_key: str):
        service_status = str(summary_store.get_status_summary().get("service_status", "unknown")).lower()
        cards = summary_store.get_guest_camera_cards(service_status=service_status)
        for camera in cards:
            if str(camera.get("camera_key", "")) != camera_key:
                continue
            return {
                "camera_key": str(camera.get("camera_key", "")),
                "display_name": str(camera.get("display_name", "—")),
                "enabled": bool(camera.get("enabled", False)),
                "status": str(camera.get("status", "disabled")),
                "last_seen_ts": str(camera.get("last_seen_ts", "")),
                "last_action_confidence": _camera_last_label(camera),
                "mtd_cost": _format_money(camera.get("mtd_cost", 0.0)),
            }
        raise HTTPException(status_code=404, detail="camera not found")

    @app.get("/api/cameras/{camera_key}/preview.jpg")
    async def api_camera_preview(camera_key: str):
        try:
            camera = _overlay_camera_runtime(admin_store.get_camera(camera_key))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="camera not found") from exc
        _persisted_settings, runtime_settings = _get_effective_settings()
        if not _to_bool(runtime_settings.get("ui.preview_enabled", "1"), True):
            raise HTTPException(status_code=403, detail="preview disabled")
        if not bool(camera.get("guest_preview_enabled", False)):
            raise HTTPException(status_code=403, detail="camera preview disabled")

        cached = preview_cache.get(camera_key)
        if snapshot_manager is None:
            if cached is not None and (time.monotonic() - cached[0] <= 60.0):
                return Response(
                    content=cached[1],
                    media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"},
                )
            return Response(status_code=204, headers={"Cache-Control": "no-store"})
        try:
            image = snapshot_manager.fetch_camera_preview(camera_key, timeout_seconds=0.8)
            preview_cache[camera_key] = (time.monotonic(), image)
            return Response(
                content=image,
                media_type="image/jpeg",
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            if cached is not None and (time.monotonic() - cached[0] <= 60.0):
                return Response(
                    content=cached[1],
                    media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"},
                )
            return Response(status_code=204, headers={"Cache-Control": "no-store"})

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

    @app.get("/api/admin/settings")
    async def api_admin_settings(
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        return _get_admin_settings()

    @app.post("/api/admin/settings/apply")
    async def api_admin_settings_apply(
        payload: dict,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        try:
            updates = _normalize_setting_payload(payload if isinstance(payload, dict) else {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        runtime_overrides.update(updates)
        return {
            "ok": True,
            "applied": updates,
            "persisted": False,
            **_get_admin_settings(),
        }

    @app.post("/api/admin/settings/save")
    async def api_admin_settings_save(
        payload: dict,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        try:
            updates = _normalize_setting_payload(payload if isinstance(payload, dict) else {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updates:
            admin_store.upsert_kv_many(updates)
        runtime_overrides.update(updates)
        for key in updates:
            runtime_overrides.pop(key, None)
        return {
            "ok": True,
            "saved": updates,
            "persisted": True,
            **_get_admin_settings(),
        }

    @app.get("/api/admin/cameras")
    async def api_admin_cameras(
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        cameras = admin_store.list_cameras()
        items = [_overlay_camera_runtime(item) for item in cameras.get("items", [])]
        return {
            **cameras,
            "items": items,
            "runtime_overrides": dict(runtime_camera_overrides),
            "unsaved_changes": bool(runtime_overrides) or bool(runtime_camera_overrides),
        }

    @app.post("/api/admin/cameras/{camera_key}/apply")
    async def api_admin_camera_apply(
        camera_key: str,
        payload: dict,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        try:
            updates = _normalize_camera_payload(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        runtime_camera_overrides[camera_key] = updates
        return {
            "ok": True,
            "persisted": False,
            "camera_key": camera_key,
            "runtime_override": runtime_camera_overrides[camera_key],
            "unsaved_changes": True,
        }

    @app.post("/api/admin/cameras/{camera_key}/save")
    async def api_admin_camera_save(
        camera_key: str,
        payload: dict,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        try:
            updates = _normalize_camera_payload(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            saved = admin_store.update_camera(camera_key, updates)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        runtime_camera_overrides.pop(camera_key, None)
        return {
            "ok": True,
            "persisted": True,
            "camera": saved,
            "unsaved_changes": bool(runtime_overrides) or bool(runtime_camera_overrides),
        }

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
    _server: object | None = field(init=False, default=None, repr=False)
    _server_task: asyncio.Task[None] | None = field(
        init=False,
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.host = os.getenv("SYNTHIA_API_HOST", self.host)
        self.port = int(os.getenv("SYNTHIA_API_PORT", str(self.port)))

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
