from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from ..taxonomy_store import COLLECTION_FILES
from .config_files import ConfigFilesManager
from .deps import Services, build_runtime_env, require_services
from .routers import auth, config, meta, runs, schedules, settings_api, users
from .runner import RunQueueManager
from .scheduler import SchedulerService
from .security import SecretCipher, hash_password
from .settings import WebUISettings, load_webui_settings
from .state import StateStore
from .tasks import TaskRegistry


_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CSRFMiddleware(BaseHTTPMiddleware):
    """Require X-Requested-With header on state-changing API requests."""

    async def dispatch(self, request: Request, call_next):
        if request.method not in _CSRF_SAFE_METHODS and "/api/" in request.url.path:
            if request.headers.get("x-requested-with") != "XMLHttpRequest":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed"},
                )
        return await call_next(request)


class ETagMiddleware(BaseHTTPMiddleware):
    """Add ETag headers to GET JSON API responses; return 304 when unchanged."""

    async def dispatch(self, request: Request, call_next):
        if request.method != "GET" or "/api/" not in request.url.path:
            return await call_next(request)

        response = await call_next(request)
        if response.status_code != 200:
            return response

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        # Read streamed body
        body_chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            body_chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
        body = b"".join(body_chunks)

        etag = '"' + hashlib.md5(body).hexdigest() + '"'
        if_none_match = request.headers.get("if-none-match", "")
        if if_none_match == etag:
            return Response(status_code=304, headers={"ETag": etag})

        return Response(
            content=body,
            status_code=response.status_code,
            headers={**dict(response.headers), "ETag": etag},
            media_type=response.media_type,
        )


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

    # Seed taxonomy tables from JSON files on first boot.
    taxonomy_dir = settings.config_root / "taxonomy"
    for collection, filename in COLLECTION_FILES.items():
        seeded = state.taxonomy_seed_from_json(collection, taxonomy_dir / filename)
        if seeded:
            print(f"[webui] seeded taxonomy '{collection}' with {seeded} entries from {filename}", flush=True)

    cipher = SecretCipher(settings.fernet_key)

    if not state.has_users():
        if settings.bootstrap_password:
            state.upsert_user(settings.bootstrap_user, hash_password(settings.bootstrap_password))
            print(f"[webui] bootstrapped login user '{settings.bootstrap_user}'", flush=True)
        else:
            print("[webui] no users found. First-time setup is required.", flush=True)

    config_files = ConfigFilesManager(settings.config_root, state=state)
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
        # Suppress ConnectionResetError spam on Windows. The ProactorEventLoop
        # tries socket.shutdown() on already-closed connections, flooding the
        # terminal and sometimes locking it up.
        if sys.platform == "win32":
            loop = asyncio.get_running_loop()
            _default = loop.default_exception_handler

            def _handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
                if isinstance(context.get("exception"), ConnectionResetError):
                    return
                _default(context)

            loop.set_exception_handler(_handler)

        app.state.services = services
        services.runner.start()
        services.scheduler.start()
        scheme = "https" if settings.ssl_enabled else "http"
        addr = f"{scheme}://{settings.bind_host}:{settings.bind_port}{settings.base_path}"
        print(f"[start] webui-server listening on {addr}", flush=True)
        logger.info("webui-server started — %s", addr)
        try:
            yield
        finally:
            logger.info("webui-server shutting down")
            services.scheduler.shutdown()
            services.runner.stop()

    app = FastAPI(title="CookDex Web UI", version="1.0", lifespan=lifespan)
    app.add_middleware(ETagMiddleware)
    app.add_middleware(CSRFMiddleware)
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
    async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
        logger.exception("Unhandled RuntimeError on %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=500, content={"error": "runtime_error", "detail": "An internal error occurred."})

    return app
