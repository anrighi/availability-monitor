from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from availability_monitor import storage, telegram
from availability_monitor.job import run_stored_monitor_pass
from availability_monitor.protocol import MonitorProvider, StorageHandle


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def templates_dir() -> Path:
    override = os.environ.get("MONITOR_TEMPLATES_DIR", "").strip()
    if override:
        return Path(override).resolve()
    return package_root() / "templates"


def static_dir() -> Path:
    override = os.environ.get("MONITOR_STATIC_DIR", "").strip()
    if override:
        return Path(override).resolve()
    return package_root() / "static"


def require_password_config() -> str:
    pwd = os.environ.get("WEB_UI_PASSWORD", "").strip()
    if not pwd:
        raise RuntimeError("WEB_UI_PASSWORD must be set for the web UI")
    return pwd


def mask_secret(value: str, *, visible_tail: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible_tail + 2:
        return "••••"
    return "••••" + value[-visible_tail:]


def format_ts(ts: object) -> str:
    if ts is None:
        return ""
    try:
        value = float(ts)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    return datetime.datetime.utcfromtimestamp(value).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def pretty_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return str(value)


def create_app(provider: MonitorProvider) -> FastAPI:
    app_data_dir = Path(os.environ.get("APP_DATA_DIR", "/data")).resolve()
    app = FastAPI(title=f"{provider.title} UI")
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.environ.get("SESSION_SECRET", "change-me-in-production"),
        same_site="lax",
        https_only=os.environ.get("SESSION_HTTPS_ONLY", "").lower()
        in ("1", "true", "yes"),
    )
    templates = Jinja2Templates(directory=str(templates_dir()))
    templates.env.globals["format_ts"] = format_ts
    templates.env.filters["pretty_json"] = pretty_json
    templates.env.globals["provider_title"] = provider.title

    static_path = static_dir()
    if static_path.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    def session_ok(request: Request) -> bool:
        return bool(request.session.get("auth"))

    def require_session(request: Request) -> None:
        if session_ok(request):
            return
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    def get_db_file() -> Path:
        return storage.db_path_for_data_dir(app_data_dir)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> Any:
        if session_ok(request):
            return RedirectResponse("/", status_code=302)
        auth_ok = bool(os.environ.get("WEB_UI_PASSWORD", "").strip())
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": None, "auth_configured": auth_ok},
        )

    @app.post("/login", response_class=HTMLResponse)
    async def login_submit(
        request: Request,
        password: str = Form(...),
    ) -> Any:
        try:
            expected = require_password_config()
        except RuntimeError:
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "error": "WEB_UI_PASSWORD is not set on the server",
                    "auth_configured": False,
                },
                status_code=503,
            )
        given = hashlib.sha256(password.encode("utf-8")).digest()
        want = hashlib.sha256(expected.encode("utf-8")).digest()
        if not hmac.compare_digest(given, want):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Invalid password", "auth_configured": True},
                status_code=401,
            )
        request.session["auth"] = True
        return RedirectResponse("/", status_code=302)

    @app.get("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/login", status_code=302)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> Any:
        if not session_ok(request):
            return RedirectResponse("/login", status_code=302)
        db_file = get_db_file()
        storage.ensure_defaults(
            db_file,
            default_settings=provider.default_settings(),
            allowed_keys=provider.all_setting_keys(),
        )
        settings = storage.get_all_settings(db_file)
        handle = StorageHandle(db_file=db_file)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "settings": settings,
                "setting_fields": provider.setting_fields(),
                "masked_token": mask_secret(settings.get("telegram_bot_token", "")),
                "masked_chat": mask_secret(settings.get("telegram_chat_id", "")),
                "executions": storage.list_executions(db_file, limit=50),
                "state_item_count": len(storage.list_state_items(db_file)),
                **provider.extra_dashboard_context(handle),
            },
        )

    @app.post("/api/settings")
    async def api_settings(request: Request) -> RedirectResponse:
        require_session(request)
        form = await request.form()
        db_file = get_db_file()
        stored = storage.get_all_settings(db_file)
        updates: dict[str, str] = {}

        for field in provider.setting_fields():
            raw = str(form.get(field.key, "") or "").strip()
            if raw:
                updates[field.key] = raw

        new_token = str(form.get("telegram_bot_token", "") or "").strip()
        if new_token:
            updates["telegram_bot_token"] = new_token
        elif str(form.get("keep_telegram_token", "")) != "1":
            updates["telegram_bot_token"] = ""

        new_chat = str(form.get("telegram_chat_id", "") or "").strip()
        if new_chat:
            updates["telegram_chat_id"] = new_chat
        elif str(form.get("keep_telegram_chat", "")) != "1":
            updates["telegram_chat_id"] = ""

        effective = dict(stored)
        effective.update(updates)
        error = provider.validate_settings_update(updates, stored, effective)
        if error:
            return RedirectResponse(f"/?settings_error={error}", status_code=303)

        storage.set_settings_batch(
            db_file, updates, allowed_keys=provider.all_setting_keys()
        )
        return RedirectResponse("/?settings=ok", status_code=303)

    @app.post("/api/telegram/test")
    async def api_telegram_test(request: Request) -> RedirectResponse:
        require_session(request)
        db_file = get_db_file()
        settings = storage.get_all_settings(db_file)
        token = (settings.get("telegram_bot_token") or "").strip()
        chat = (settings.get("telegram_chat_id") or "").strip()
        if not token or not chat:
            raise HTTPException(400, "Telegram token and chat id must be configured")
        session = requests.Session()
        session.trust_env = False
        ok, err = telegram.send_plain(
            session,
            token=token,
            chat_id=chat,
            message=provider.telegram_test_message(),
        )
        if not ok:
            raise HTTPException(502, err[:2000])
        return RedirectResponse("/?telegram_test=ok", status_code=303)

    @app.post("/api/run-now")
    async def api_run_now(request: Request) -> RedirectResponse:
        require_session(request)

        def job() -> dict[str, Any]:
            return run_stored_monitor_pass(
                provider,
                app_data_dir,
                dry_run=False,
                verbose=False,
                telegram_dry_run=False,
                trust_proxy_env=False,
            )

        result = await run_in_threadpool(job)
        exit_code = int(result.get("exit_code", 1))
        return RedirectResponse(f"/?run_exit={exit_code}", status_code=303)

    @app.post("/api/clear-state")
    async def api_clear_state(request: Request) -> RedirectResponse:
        require_session(request)
        storage.clear_state_items(get_db_file())
        return RedirectResponse("/?state_cleared=ok", status_code=303)

    return app
