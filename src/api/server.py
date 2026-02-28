"""HTTP API server for guest/admin endpoints."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode

try:
    from fastapi import Cookie, FastAPI, HTTPException, Request, Response
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
except ModuleNotFoundError:  # pragma: no cover - optional API dependency
    Cookie = FastAPI = HTTPException = Request = Response = None  # type: ignore[assignment]
    HTMLResponse = RedirectResponse = StaticFiles = Jinja2Templates = None  # type: ignore[assignment]

from src.config import ServiceConfig
from src.db import (
    AdminStore,
    DatabaseBootstrap,
    SummaryStore,
    db_get_camera_profile,
    db_upsert_camera_profile,
    db_list_camera_views,
    db_get_camera_view,
    db_upsert_camera_view,
)
from src.auth import FirstRunBootstrap, SessionManager, UserStore
from src.frigate import FrigateClient, sync_discovered_cameras_from_config
from src.snapshot_manager import SnapshotManager
from src.api.camera_setup_models import (
    CameraProfile,
    CameraView,
    CameraViewUpsertRequest,
    CameraSetupGenerateRequest,
    CameraSetupGenerateResponse,
)
from src.auth.session import (
    SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE,
    SESSION_TTL_SECONDS,
)

LOGGER = logging.getLogger("synthia_vision.api")
AI_LOGGER = logging.getLogger("synthia_vision.ai")


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
    setup_snapshot_dir_cache: Path | None = None
    runtime_overrides: dict[str, Any] = {}
    runtime_camera_overrides: dict[str, dict[str, Any]] = {}
    session_secret = os.getenv("SYNTHIA_SESSION_SECRET", f"{config.service.slug}-dev-secret")
    session_manager = SessionManager(secret=session_secret, ttl_seconds=SESSION_TTL_SECONDS)
    app = FastAPI(title="Synthia Vision API", version="0.1.0")
    PURPOSE_OPTIONS = [
        "general",
        "doorbell",
        "perimeter_security",
        "driveway",
        "backyard",
        "garage",
        "child_room",
    ]

    ADMIN_SETTING_KEYS = [
        "budget.monthly_limit_usd",
        "policy.defaults.confidence_threshold",
        "policy.modes.doorbell_only",
        "ai.modes.high_precision",
        "modes.current",
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

    def _safe_token(value: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value))
        return cleaned.strip("_") or "value"

    def _resolve_setup_snapshot_dir() -> Path:
        nonlocal setup_snapshot_dir_cache
        if setup_snapshot_dir_cache is not None:
            return setup_snapshot_dir_cache
        preferred = config.paths.snapshots_dir / "setup"
        fallback = Path("/tmp/synthia_vision/setup")
        for idx, candidate in enumerate((preferred, fallback)):
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                probe = candidate / ".write_probe"
                probe.write_bytes(b"ok")
                probe.unlink(missing_ok=True)
                setup_snapshot_dir_cache = candidate
                if idx == 1:
                    LOGGER.warning(
                        "Using fallback setup snapshot dir path=%s preferred=%s",
                        candidate,
                        preferred,
                    )
                return setup_snapshot_dir_cache
            except OSError as exc:
                LOGGER.warning("Setup snapshot dir not writable path=%s error=%s", candidate, exc)
        raise OSError("no writable setup snapshot directory available")

    def _camera_setup_context_schema() -> dict[str, Any]:
        return {
            "type": "json_schema",
            "name": "camera_setup_context_v1",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "environment",
                    "purpose",
                    "view_type",
                    "context_summary",
                    "expected_activity",
                    "zones",
                    "focus_notes",
                    "delivery_focus",
                    "privacy_mode",
                ],
                "properties": {
                    "schema_version": {"type": "integer", "enum": [1]},
                    "environment": {"type": "string", "enum": ["indoor", "outdoor"]},
                    "purpose": {"type": "string", "enum": PURPOSE_OPTIONS},
                    "view_type": {"type": "string", "enum": ["fixed", "wide", "ptz"]},
                    "context_summary": {"type": "string", "minLength": 10, "maxLength": 220},
                    "expected_activity": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 10,
                        "items": {"type": "string", "minLength": 3, "maxLength": 60},
                    },
                    "zones": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["zone_id", "label", "notes"],
                            "properties": {
                                "zone_id": {"type": "string", "minLength": 2, "maxLength": 40},
                                "label": {"type": "string", "minLength": 2, "maxLength": 50},
                                "notes": {"type": "string", "minLength": 5, "maxLength": 220},
                            },
                        },
                    },
                    "focus_notes": {"type": "string", "minLength": 5, "maxLength": 260},
                    "delivery_focus": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {"type": "string", "enum": ["package", "food", "grocery"]},
                    },
                    "privacy_mode": {
                        "type": "string",
                        "enum": ["no_identifying_details"],
                    },
                },
            },
        }

    def _normalize_openai_json_schema_format(
        raw_format: dict[str, Any],
        *,
        fallback_name: str,
    ) -> dict[str, Any]:
        schema_type = str(raw_format.get("type", "") or "").strip()
        if schema_type != "json_schema":
            raise ValueError("type must be json_schema")
        nested = raw_format.get("json_schema")
        if isinstance(nested, dict):
            name = str(nested.get("name") or raw_format.get("name") or fallback_name).strip()
            strict = bool(nested.get("strict", raw_format.get("strict", False)))
            schema = nested.get("schema", raw_format.get("schema"))
        else:
            name = str(raw_format.get("name") or fallback_name).strip()
            strict = bool(raw_format.get("strict", False))
            schema = raw_format.get("schema")
        if not name:
            raise ValueError("name is required")
        if strict is not True:
            raise ValueError("strict must be true")
        if not isinstance(schema, dict) or not schema:
            raise ValueError("schema must be a non-empty object")
        return {
            "type": "json_schema",
            "name": name,
            "strict": True,
            "schema": schema,
        }

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
            elif key == "modes.current":
                mode_value = str(value or "").strip().lower()
                allowed_modes = {str(item).strip().lower() for item in config.modes.intent_available}
                if mode_value not in allowed_modes:
                    raise ValueError(
                        f"modes.current must be one of: {', '.join(sorted(allowed_modes))}"
                    )
                updates[key] = mode_value
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
        if "security_capable" in payload:
            updates["security_capable"] = _to_bool(payload.get("security_capable"), False)
        if "security_mode" in payload:
            updates["security_mode"] = _to_bool(payload.get("security_mode"), False)
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
                "suppressed_today": int(metrics.get("suppressed_count_today", 0)),
                "suppressed_rate": f"{float(metrics.get('suppressed_rate_today', 0.0)) * 100:.1f}%",
                "cost_today": _format_money(metrics.get("cost_daily_total", 0.0)),
                "cost_mtd": _format_money(metrics.get("cost_month2day_total", 0.0)),
                "ai_calls_today": int(metrics.get("count_today", 0)),
                "avg_cost_per_event": _format_money(metrics.get("cost_avg_per_event", 0.0)),
                "tokens_today_total": int(metrics.get("tokens_today_total", 0)),
                "avg_tokens_per_event": int(round(float(metrics.get("avg_tokens_per_event", 0.0)))),
                "current_mode": str(status.get("current_mode", "normal")),
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

    def _get_frigate_health_payload() -> dict[str, Any]:
        kv = admin_store.get_kv_many(
            [
                "frigate.health.status",
                "frigate.health.last_ok_at",
                "frigate.health.updated_at",
            ]
        )
        with sqlite3.connect(str(config.paths.db_file), timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000;")
            rows = conn.execute(
                """
                SELECT camera_key, health_status, health_detail, health_updated_ts
                FROM cameras
                ORDER BY camera_key ASC
                """
            ).fetchall()
        cameras = [
            {
                "camera_id": str(row["camera_key"]),
                "status": str(row["health_status"] or "unknown"),
                "detail": str(row["health_detail"] or ""),
                "updated_at": str(row["health_updated_ts"] or ""),
            }
            for row in rows
        ]
        return {
            "frigate": {
                "status": str(kv.get("frigate.health.status", "unknown")),
                "last_ok_at": str(kv.get("frigate.health.last_ok_at", "")),
                "updated_at": str(kv.get("frigate.health.updated_at", "")),
            },
            "cameras": cameras,
        }

    def _set_session_cookie(
        response: Response,
        *,
        username: str,
        role: str,
        remember_me: bool = False,
    ) -> None:
        token = session_manager.create_token(username=username, role=role)
        max_age = 60 * 60 * 24 * 30 if remember_me else None
        expires = datetime.now(timezone.utc) + timedelta(seconds=max_age) if max_age else None
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            httponly=SESSION_COOKIE_HTTPONLY,
            samesite=SESSION_COOKIE_SAMESITE,
            secure=SESSION_COOKIE_SECURE,
            max_age=max_age,
            expires=expires,
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
        remember_me = _to_bool((form.get("remember_me") or [""])[0], False)
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
        _set_session_cookie(response, username=username, role=role, remember_me=remember_me)
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
        guest_context = _build_guest_dashboard_context()
        return templates.TemplateResponse(
            request=request,
            name="admin.html",
            context={
                "title": config.service.name,
                "username": principal.username,
                "kpis": guest_context.get("kpis", {}),
            },
        )

    @app.get("/ui/setup", response_class=HTMLResponse, include_in_schema=False)
    async def ui_setup(
        request: Request,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        if _ui_admin_or_redirect(session_token) is None:
            return RedirectResponse(url="/ui/login", status_code=303)
        setup_globals = _get_admin_settings().get("runtime", {})
        return templates.TemplateResponse(
            request=request,
            name="setup.html",
            context={
                "title": config.service.name,
                "setup_globals_json": json.dumps(setup_globals),
            },
        )

    @app.get("/ui/events", response_class=HTMLResponse, include_in_schema=False)
    async def ui_events(
        request: Request,
        camera: str | None = None,
        status: str | None = None,
        q: str | None = None,
        page: int = 1,
        page_size: int = 50,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        if _ui_admin_or_redirect(session_token) is None:
            return RedirectResponse(url="/ui/login", status_code=303)
        allowed_page_sizes = {25, 50, 100}
        normalized_page_size = page_size if page_size in allowed_page_sizes else 50
        normalized_page = max(1, int(page))
        normalized_camera = str(camera or "").strip() or None
        normalized_status = str(status or "").strip().lower() or None
        normalized_query = str(q or "").strip() or None
        offset = (normalized_page - 1) * normalized_page_size

        events = admin_store.list_events(
            limit=normalized_page_size,
            offset=offset,
            camera=normalized_camera,
            status=normalized_status,
            event_id_query=normalized_query,
        )
        total_count = int(events.get("total", 0) or 0)
        total_pages = max(1, math.ceil(total_count / normalized_page_size))
        current_page = min(normalized_page, total_pages)
        if current_page != normalized_page:
            offset = (current_page - 1) * normalized_page_size
            events = admin_store.list_events(
                limit=normalized_page_size,
                offset=offset,
                camera=normalized_camera,
                status=normalized_status,
                event_id_query=normalized_query,
            )
        page_start = 0 if total_count == 0 else offset + 1
        page_end = min(offset + normalized_page_size, total_count) if total_count > 0 else 0

        available_cameras = admin_store.list_event_cameras()
        available_statuses = ["ok", "suppressed", "skipped", "error"]
        query_base: dict[str, str] = {}
        if normalized_camera:
            query_base["camera"] = normalized_camera
        if normalized_status:
            query_base["status"] = normalized_status
        if normalized_query:
            query_base["q"] = normalized_query
        if normalized_page_size != 50:
            query_base["page_size"] = str(normalized_page_size)

        def _events_url_for(page_value: int) -> str:
            params = dict(query_base)
            if page_value > 1:
                params["page"] = str(page_value)
            encoded = urlencode(params)
            return f"/ui/events?{encoded}" if encoded else "/ui/events"

        prev_url = _events_url_for(current_page - 1) if current_page > 1 else None
        next_url = _events_url_for(current_page + 1) if current_page < total_pages else None

        page_links: list[int | None] = []
        candidate_pages: list[int] = [1]
        for page_value in range(current_page - 2, current_page + 3):
            if 1 <= page_value <= total_pages:
                candidate_pages.append(page_value)
        if total_pages > 1:
            candidate_pages.append(total_pages)
        deduped = sorted(set(candidate_pages))
        for idx, page_value in enumerate(deduped):
            if idx > 0 and page_value - deduped[idx - 1] > 1:
                page_links.append(None)
            page_links.append(page_value)

        return templates.TemplateResponse(
            request=request,
            name="events.html",
            context={
                "title": config.service.name,
                "events": events.get("items", []),
                "available_cameras": available_cameras,
                "available_statuses": available_statuses,
                "filters": {
                    "camera": normalized_camera or "",
                    "status": normalized_status or "",
                    "q": normalized_query or "",
                    "page": current_page,
                    "page_size": normalized_page_size,
                },
                "pagination": {
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "page": current_page,
                    "page_start": page_start,
                    "page_end": page_end,
                    "prev_url": prev_url,
                    "next_url": next_url,
                    "page_links": page_links,
                    "page_url_map": {p: _events_url_for(p) for p in deduped},
                },
            },
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

    @app.get("/ui/heatmap", response_class=HTMLResponse, include_in_schema=False)
    async def ui_heatmap(
        request: Request,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        if _ui_admin_or_redirect(session_token) is None:
            return RedirectResponse(url="/ui/login", status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="heatmap.html",
            context={"title": config.service.name},
        )

    @app.post("/api/auth/login")
    async def api_auth_login(payload: dict, response: Response):
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        remember_me = _to_bool(payload.get("remember_me"), False)
        ok, role = user_store.authenticate(username=username, password=password)
        if not ok or role is None:
            raise HTTPException(status_code=401, detail="invalid credentials")
        _set_session_cookie(response, username=username, role=role, remember_me=remember_me)
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
            raise HTTPException(status_code=401, detail="not authenticated")
        return {
            "authenticated": True,
            "username": principal.username,
            "role": principal.role,
            "expires_at": principal.expires_at,
        }

    @app.get("/api/admin/summary")
    async def api_admin_summary(
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)

        def _seconds_since(raw_ts: Any) -> int | None:
            value = str(raw_ts or "").strip()
            if not value:
                return None
            parsed_raw = value.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(parsed_raw)
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            seconds = (datetime.now(timezone.utc) - parsed).total_seconds()
            return max(0, int(seconds))

        status = summary_store.get_status_summary()
        metrics = summary_store.get_guest_metrics_payload()
        events = admin_store.list_events(limit=1, offset=0)
        errors = admin_store.list_errors(limit=1, offset=0)
        latest_event = (events.get("items") or [{}])[0]
        heartbeat_ts = status.get("heartbeat_ts") or status.get("timestamp")
        return {
            "service_status": str(status.get("service_status", "unknown")),
            "heartbeat_ts": heartbeat_ts,
            "heartbeat_age_s": _seconds_since(heartbeat_ts),
            "queue_depth": int(metrics.get("queue_depth", status.get("queue_depth", 0)) or 0),
            "cost_24h_total": float(metrics.get("cost_24h_total", 0.0) or 0.0),
            "burn_rate_24h": float(metrics.get("burn_rate_24h", 0.0) or 0.0),
            "cost_month2day_total": float(metrics.get("cost_month2day_total", 0.0) or 0.0),
            "projected_month_total": float(metrics.get("projected_month_total", 0.0) or 0.0),
            "tokens_24h_total": int(metrics.get("tokens_24h_total", 0) or 0),
            "tokens_month2day_total": int(metrics.get("tokens_month2day_total", 0) or 0),
            "suppressed_count_total": int(metrics.get("suppressed_count_total", 0) or 0),
            "suppressed_count_today": int(metrics.get("suppressed_count_today", 0) or 0),
            "suppressed_rate_today": float(metrics.get("suppressed_rate_today", 0.0) or 0.0),
            "current_mode": str(status.get("current_mode", "normal")),
            "last_event_ts": str(latest_event.get("ts") or ""),
            "events_total": int(events.get("total", 0) or 0),
            "errors_total": int(errors.get("total", 0) or 0),
        }

    @app.get("/api/admin/heatmap")
    async def api_admin_heatmap(
        hours: int = 24,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        return admin_store.get_timeline_heatmap(hours=hours)

    @app.get("/api/status")
    async def api_status():
        return summary_store.get_guest_status_payload()

    @app.get("/api/metrics/summary")
    async def api_metrics_summary():
        return {"metrics": summary_store.get_guest_metrics_payload()}

    @app.get("/api/cameras/summary")
    async def api_cameras_summary():
        return summary_store.get_guest_cameras_payload()

    @app.get("/api/frigate/health")
    async def api_frigate_health():
        return _get_frigate_health_payload()

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

    @app.post("/api/cameras/{camera_key}/toggle")
    async def api_camera_toggle(camera_key: str):
        try:
            camera = _overlay_camera_runtime(admin_store.get_camera(camera_key))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="camera not found") from exc
        next_enabled = not bool(camera.get("enabled", False))
        try:
            result = admin_store.update_camera(camera_key, {"enabled": next_enabled})
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "camera_key": camera_key,
            "enabled": bool(result.get("enabled", next_enabled)),
        }

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

    @app.get("/api/events/{event_id}/snapshot.jpg")
    async def api_event_snapshot(
        event_id: str,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        event = admin_store.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        if snapshot_manager is None:
            raise HTTPException(status_code=503, detail="snapshot service unavailable")
        try:
            snapshot = snapshot_manager.fetch_event_snapshot(
                event_id=event_id,
                camera=str(event.get("camera", "")).strip() or None,
            )
        except Exception as exc:
            LOGGER.warning(
                "Failed fetching event snapshot event_id=%s camera=%s error=%s",
                event_id,
                event.get("camera"),
                exc,
            )
            raise HTTPException(status_code=502, detail="snapshot fetch failed") from exc
        return Response(
            content=snapshot,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/cameras")
    async def api_cameras(
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        return admin_store.list_cameras()

    @app.post("/api/frigate/refresh")
    async def api_frigate_refresh(
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        try:
            client = FrigateClient(config)
            payload = await asyncio.to_thread(client.get_config)
            summary = await asyncio.to_thread(
                sync_discovered_cameras_from_config,
                db_path=config.paths.db_file,
                frigate_config_payload=payload,
            )
        except Exception as exc:
            LOGGER.warning("Frigate manual refresh failed error=%s", exc)
            raise HTTPException(status_code=502, detail=f"frigate refresh failed: {exc}") from exc
        LOGGER.info(
            "Frigate manual refresh complete cameras=%s ids=%s",
            int(summary.get("count", 0)),
            summary.get("camera_ids", []),
        )
        return {"ok": True, "summary": summary}

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
        persisted_updates = dict(updates)
        if "policy.defaults.confidence_threshold" in updates:
            persisted_updates["policy.default_confidence_threshold"] = updates[
                "policy.defaults.confidence_threshold"
            ]
        if persisted_updates:
            admin_store.upsert_kv_many(persisted_updates)
        runtime_overrides.update(updates)
        for key in persisted_updates:
            runtime_overrides.pop(key, None)
        return {
            "ok": True,
            "saved": persisted_updates,
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

    @app.get("/api/admin/cameras/{camera_key}/profile")
    async def api_admin_camera_profile_get(
        camera_key: str,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        profile = db_get_camera_profile(config.paths.db_file, camera_key)
        if profile is None:
            profile = db_upsert_camera_profile(config.paths.db_file, camera_key, {})
        return CameraProfile(**profile).model_dump()

    @app.put("/api/admin/cameras/{camera_key}/profile")
    async def api_admin_camera_profile_put(
        camera_key: str,
        payload: dict,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        normalized = payload if isinstance(payload, dict) else {}
        merged = {"camera_key": camera_key, **normalized}
        # Enforce fixed privacy mode and system-managed completion state.
        merged["privacy_mode"] = "no_identifying_details"
        required_fields_present = bool(
            merged.get("environment")
            and merged.get("purpose")
            and merged.get("view_type")
            and str(merged.get("mounting_location") or "").strip()
        )
        if not required_fields_present:
            raise HTTPException(
                status_code=400,
                detail=(
                    "environment, purpose, view_type, and mounting_location are required for camera profile"
                ),
            )
        merged["setup_completed"] = True
        # delivery_focus only applies for doorbell profiles.
        if merged.get("purpose") != "doorbell":
            merged["delivery_focus"] = []
        default_view_id = str(merged.get("default_view_id") or "").strip()
        if default_view_id:
            existing_view = db_get_camera_view(config.paths.db_file, camera_key, default_view_id)
            if existing_view is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"default_view_id '{default_view_id}' does not exist for camera '{camera_key}'",
                )
        try:
            validated = CameraProfile(**merged).model_dump()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        saved = db_upsert_camera_profile(config.paths.db_file, camera_key, validated)
        return CameraProfile(**saved).model_dump()

    @app.get("/api/admin/cameras/{camera_key}/views")
    async def api_admin_camera_views_get(
        camera_key: str,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        views = db_list_camera_views(config.paths.db_file, camera_key)
        return {
            "camera_key": camera_key,
            "count": len(views),
            "items": [CameraView(**item).model_dump() for item in views],
        }

    @app.put("/api/admin/cameras/{camera_key}/views/{view_id}")
    async def api_admin_camera_view_put(
        camera_key: str,
        view_id: str,
        payload: dict,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        if len(str(view_id or "").strip()) > 40:
            raise HTTPException(status_code=400, detail="view_id must be 40 characters or fewer")
        normalized = payload if isinstance(payload, dict) else {}
        try:
            view_payload = CameraViewUpsertRequest(**normalized).model_dump()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        saved = db_upsert_camera_view(
            config.paths.db_file,
            camera_key,
            view_id,
            view_payload,
        )
        return CameraView(**saved).model_dump()

    @app.post("/api/admin/cameras/{camera_key}/views/{view_id}/setup/snapshot")
    async def api_admin_camera_view_setup_snapshot(
        camera_key: str,
        view_id: str,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        if snapshot_manager is None:
            raise HTTPException(status_code=503, detail="snapshot manager unavailable")
        try:
            image = snapshot_manager.fetch_camera_preview(camera_key, timeout_seconds=2.0)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"snapshot fetch failed: {exc}") from exc
        try:
            setup_dir = _resolve_setup_snapshot_dir()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"no writable setup snapshot path: {exc}") from exc
        now_epoch = int(time.time())
        filename = f"{_safe_token(camera_key)}_{_safe_token(view_id)}_{now_epoch}.jpg"
        path = setup_dir / filename
        try:
            path.write_bytes(image)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed saving setup snapshot: {exc}") from exc
        existing = db_get_camera_view(config.paths.db_file, camera_key, view_id) or {}
        saved = db_upsert_camera_view(
            config.paths.db_file,
            camera_key,
            view_id,
            {
                "label": existing.get("label") or view_id,
                "ha_preset_id": existing.get("ha_preset_id"),
                "setup_snapshot_path": str(path),
                "context_summary": existing.get("context_summary"),
                "expected_activity": existing.get("expected_activity", []),
                "zones": existing.get("zones", []),
                "focus_notes": existing.get("focus_notes"),
            },
        )
        return {
            "camera_key": camera_key,
            "view_id": view_id,
            "snapshot_path": str(path),
            "snapshot_bytes": len(image),
            "view": CameraView(**saved).model_dump(),
        }

    @app.post("/api/admin/cameras/{camera_key}/views/{view_id}/setup/generate_context")
    async def api_admin_camera_view_generate_context(
        camera_key: str,
        view_id: str,
        payload: dict,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ):
        _require_admin(session_token)
        LOGGER.info("Setup context generation requested camera=%s view_id=%s", camera_key, view_id)
        started_at = time.monotonic()
        try:
            req = CameraSetupGenerateRequest(**(payload if isinstance(payload, dict) else {}))
        except Exception as exc:
            LOGGER.warning(
                "Setup context request validation failed camera=%s view_id=%s error=%s payload=%s",
                camera_key,
                view_id,
                exc,
                payload,
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if req.purpose != "doorbell":
            req.delivery_focus = []

        LOGGER.info("Setup context loading view row camera=%s view_id=%s", camera_key, view_id)
        try:
            view = await asyncio.wait_for(
                asyncio.to_thread(db_get_camera_view, config.paths.db_file, camera_key, view_id),
                timeout=3.0,
            )
        except TimeoutError as exc:
            LOGGER.exception(
                "Setup context view load timed out camera=%s view_id=%s",
                camera_key,
                view_id,
            )
            raise HTTPException(status_code=504, detail="timeout loading camera view from db") from exc
        view = view or {}
        LOGGER.info("Setup context view loaded camera=%s view_id=%s", camera_key, view_id)

        snapshot_bytes: bytes | None = None
        snapshot_path = str(view.get("setup_snapshot_path") or "").strip()
        if snapshot_path:
            LOGGER.info(
                "Setup context attempting existing snapshot camera=%s view_id=%s path=%s",
                camera_key,
                view_id,
                snapshot_path,
            )
        if snapshot_path:
            path_obj = Path(snapshot_path)
            if path_obj.exists() and path_obj.is_file():
                try:
                    snapshot_bytes = path_obj.read_bytes()
                    LOGGER.info(
                        "Setup context loaded existing snapshot camera=%s view_id=%s bytes=%s",
                        camera_key,
                        view_id,
                        len(snapshot_bytes),
                    )
                except OSError:
                    snapshot_bytes = None
        if snapshot_bytes is None:
            if snapshot_manager is None:
                raise HTTPException(status_code=503, detail="snapshot manager unavailable")
            try:
                LOGGER.info(
                    "Setup context fetching live snapshot camera=%s view_id=%s timeout_s=3.0",
                    camera_key,
                    view_id,
                )
                snapshot_bytes = await asyncio.wait_for(
                    asyncio.to_thread(
                        snapshot_manager.fetch_camera_preview,
                        camera_key,
                        timeout_seconds=2.0,
                    ),
                    timeout=3.0,
                )
            except Exception as exc:
                LOGGER.exception(
                    "Setup context snapshot fetch failed camera=%s view_id=%s error=%s",
                    camera_key,
                    view_id,
                    exc,
                )
                raise HTTPException(status_code=502, detail=f"snapshot fetch failed: {exc}") from exc
        LOGGER.info(
            "Setup context snapshot ready camera=%s view_id=%s bytes=%s",
            camera_key,
            view_id,
            len(snapshot_bytes),
        )

        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=503, detail="openai package unavailable") from exc

        setup_cfg = config.ai.setup
        if setup_cfg.structured_output.mode != "json_schema":
            raise HTTPException(status_code=500, detail="ai.setup.structured_output.mode must be json_schema")
        client = OpenAI(
            api_key=config.openai.api_key,
            timeout=float(setup_cfg.openai.timeout_seconds),
        )
        encoded = base64.b64encode(snapshot_bytes).decode("ascii")
        image_data_url = f"data:image/jpeg;base64,{encoded}"
        raw_setup_format = dict(setup_cfg.structured_output.schema or {})
        try:
            setup_format = _normalize_openai_json_schema_format(
                raw_setup_format,
                fallback_name=setup_cfg.structured_output.schema_name,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"ai.setup.structured_output.schema invalid: {exc}",
            ) from exc
        privacy_rules = str(setup_cfg.prompts.privacy_rules or "")
        system_prompt = str(setup_cfg.prompts.system or "").format(
            privacy_rules=privacy_rules,
        )
        user_prompt = str(setup_cfg.prompts.user or "").format(
            camera_name=camera_key,
            environment=req.environment,
            purpose=req.purpose,
            view_type=req.view_type,
            mounting_location=req.mounting_location or "",
            view_notes=req.view_notes or "",
            delivery_focus=",".join(req.delivery_focus),
        )
        AI_LOGGER.info(
            "setup_context_openai_request_start camera=%s view_id=%s model=%s timeout_s=%s",
            camera_key,
            view_id,
            setup_cfg.openai.model,
            setup_cfg.openai.timeout_seconds,
        )
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.responses.create,
                    model=setup_cfg.openai.model,
                    max_output_tokens=int(setup_cfg.openai.max_output_tokens),
                    input=[
                        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": user_prompt},
                                {"type": "input_image", "image_url": image_data_url, "detail": "high"},
                            ],
                        },
                    ],
                    text={"format": setup_format},
                ),
                timeout=float(setup_cfg.openai.timeout_seconds) + 10.0,
            )
        except Exception as exc:
            AI_LOGGER.exception(
                "setup_context_openai_request_failed camera=%s view_id=%s error=%s",
                camera_key,
                view_id,
                exc,
            )
            raise HTTPException(status_code=502, detail=f"openai request failed: {exc}") from exc
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "input_tokens", getattr(usage, "prompt_tokens", 0)) or 0)
        completion_tokens = int(
            getattr(usage, "output_tokens", getattr(usage, "completion_tokens", 0)) or 0
        )
        total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
        AI_LOGGER.info(
            "setup_context_openai_request_done camera=%s view_id=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            camera_key,
            view_id,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise HTTPException(status_code=502, detail="openai response missing output_text")
        try:
            decoded = json.loads(output_text)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"openai response invalid json: {exc}") from exc
        if not isinstance(decoded, dict):
            raise HTTPException(status_code=502, detail="openai response json must be object")
        decoded["environment"] = req.environment
        decoded["purpose"] = req.purpose
        decoded["view_type"] = req.view_type
        decoded["delivery_focus"] = list(req.delivery_focus)
        decoded["privacy_mode"] = "no_identifying_details"
        decoded["schema_version"] = 1

        try:
            generated = CameraSetupGenerateResponse(**decoded).model_dump()
        except Exception as exc:
            AI_LOGGER.error(
                "setup_context_validation_failed camera=%s view_id=%s error=%s payload=%s",
                camera_key,
                view_id,
                exc,
                decoded,
            )
            raise HTTPException(status_code=502, detail=f"openai response schema mismatch: {exc}") from exc

        try:
            profile_saved = await asyncio.wait_for(
                asyncio.to_thread(
                    db_upsert_camera_profile,
                    config.paths.db_file,
                    camera_key,
                    {
                        "environment": req.environment,
                        "purpose": req.purpose,
                        "view_type": req.view_type,
                        "mounting_location": req.mounting_location,
                        "view_notes": req.view_notes,
                        "delivery_focus": list(req.delivery_focus),
                        "privacy_mode": "no_identifying_details",
                        "setup_completed": True,
                        "default_view_id": view_id,
                    },
                ),
                timeout=3.0,
            )
            saved_view = await asyncio.wait_for(
                asyncio.to_thread(
                    db_upsert_camera_view,
                    config.paths.db_file,
                    camera_key,
                    view_id,
                    {
                        "label": str(view.get("label") or view_id),
                        "ha_preset_id": view.get("ha_preset_id"),
                        "setup_snapshot_path": snapshot_path or view.get("setup_snapshot_path"),
                        "context_summary": generated.get("context_summary"),
                        "expected_activity": generated.get("expected_activity", []),
                        "zones": generated.get("zones", []),
                        "focus_notes": generated.get("focus_notes"),
                    },
                ),
                timeout=3.0,
            )
        except TimeoutError as exc:
            LOGGER.exception(
                "Setup context db upsert timed out camera=%s view_id=%s",
                camera_key,
                view_id,
            )
            raise HTTPException(status_code=504, detail="timeout persisting setup context to db") from exc
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        LOGGER.info(
            "Setup context generation completed camera=%s view_id=%s elapsed_ms=%s",
            camera_key,
            view_id,
            elapsed_ms,
        )
        return {
            "ok": True,
            "camera_key": camera_key,
            "view_id": view_id,
            "profile": CameraProfile(**profile_saved).model_dump(),
            "view": CameraView(**saved_view).model_dump(),
            "generated": generated,
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
