from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from .config_files import ConfigFilesManager
from .deps import Services, build_runtime_env, require_services
from .routers import auth, config, meta, runs, schedules, settings_api, users
from .runner import RunQueueManager
from .scheduler import SchedulerService
from .security import SecretCipher, hash_password
from .settings import WebUISettings, load_webui_settings
from .state import StateStore
from .tasks import TaskRegistry


def _select_ui_root(settings: WebUISettings) -> Path:
    if (settings.web_dist_dir / "index.html").exists():
        return settings.web_dist_dir
    return settings.static_dir


def _resolve_ui_file(ui_root: Path, relative: str) -> Path | None:
    target = (ui_root / relative).resolve()
    try:
        target.relative_to(ui_root.resolve())
    except ValueError:
        return None
    if target.is_file():
        return target
    return None


def _render_index(ui_root: Path, base_path: str) -> str:
    index_path = ui_root / "index.html"
    if not index_path.exists():
        return "<html><body><h1>Organizer UI build missing.</h1></body></html>"
    html = index_path.read_text(encoding="utf-8")
    if "__BASE_PATH__" in html:
        return html.replace("__BASE_PATH__", base_path)
    if "<base " not in html and "<head>" in html:
        html = html.replace("<head>", f"<head>\n    <base href=\"{base_path}/\" />", 1)
    return html


def create_app() -> FastAPI:
    settings = load_webui_settings()
    state = StateStore(settings.state_db_path)
    registry = TaskRegistry()
    state.initialize(registry.task_ids)
    cipher = SecretCipher(settings.fernet_key)

    if not state.has_users():
        if settings.bootstrap_password:
            state.upsert_user(settings.bootstrap_user, hash_password(settings.bootstrap_password))
            print(f"[webui] bootstrapped login user '{settings.bootstrap_user}'", flush=True)
        else:
            print("[webui] no users found. First-time setup is required.", flush=True)

    config_files = ConfigFilesManager(settings.config_root)
    runner = RunQueueManager(
        state=state,
        registry=registry,
        environment_provider=lambda: build_runtime_env(state, cipher),
        logs_dir=settings.logs_dir,
        max_log_files=settings.max_log_files,
    )
    scheduler = SchedulerService(
        state=state,
        runner=runner,
        registry=registry,
        sqlite_path=str(settings.state_db_path),
    )
    ui_root = _select_ui_root(settings)

    services = Services(
        settings=settings,
        state=state,
        registry=registry,
        runner=runner,
        scheduler=scheduler,
        config_files=config_files,
        cipher=cipher,
        ui_root=ui_root,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services
        services.runner.start()
        services.scheduler.start()
        print(
            f"[start] webui-server listening on http://{settings.bind_host}:{settings.bind_port}{settings.base_path}",
            flush=True,
        )
        try:
            yield
        finally:
            services.scheduler.shutdown()
            services.runner.stop()

    app = FastAPI(title="CookDex Web UI", version="1.0", lifespan=lifespan)
    api_prefix = f"{settings.base_path}/api/v1"

    # --- Include routers ---
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(users.router, prefix=api_prefix)
    app.include_router(runs.router, prefix=api_prefix)
    app.include_router(schedules.router, prefix=api_prefix)
    app.include_router(settings_api.router, prefix=api_prefix)
    app.include_router(config.router, prefix=api_prefix)
    app.include_router(meta.router, prefix=api_prefix)

    # --- Static / UI routes (not under api_prefix) ---

    @app.get("/")
    async def root_redirect() -> Response:
        return RedirectResponse(url=settings.base_path, status_code=307)

    @app.get("/favicon.ico")
    async def root_favicon(svc: Services = Depends(require_services)) -> Response:
        resolved = _resolve_ui_file(svc.ui_root, "favicon.ico")
        if resolved is None:
            raise HTTPException(status_code=404, detail="Favicon not found.")
        return FileResponse(resolved)

    @app.get(settings.base_path)
    async def organizer_shell() -> HTMLResponse:
        return HTMLResponse(_render_index(services.ui_root, settings.base_path))

    @app.get(f"{settings.base_path}/login")
    async def organizer_login_shell() -> HTMLResponse:
        return HTMLResponse(_render_index(services.ui_root, settings.base_path))

    @app.get(f"{settings.base_path}/{{rest:path}}")
    async def organizer_assets(rest: str) -> Response:
        if rest.startswith("api/"):
            raise HTTPException(status_code=404, detail="Unknown API route.")
        if rest:
            resolved = _resolve_ui_file(services.ui_root, rest)
            if resolved is not None:
                return FileResponse(resolved)
        return HTMLResponse(_render_index(services.ui_root, settings.base_path))

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(_request: Request, exc: RuntimeError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": "runtime_error", "detail": str(exc)})

    return app
