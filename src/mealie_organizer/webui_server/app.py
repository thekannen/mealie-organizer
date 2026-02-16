from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from .config_files import ConfigFilesManager
from .env_catalog import ENV_SPEC_BY_KEY, ENV_VAR_SPECS, EnvVarSpec
from .runner import RunQueueManager
from .scheduler import SchedulePayload, SchedulerService
from .schemas import (
    ConfigWriteRequest,
    LoginRequest,
    PoliciesUpdateRequest,
    RunCreateRequest,
    ScheduleCreateRequest,
    ScheduleUpdateRequest,
    SettingsUpdateRequest,
)
from .security import SecretCipher, hash_password, new_session_token, verify_password
from .settings import WebUISettings, load_webui_settings
from .state import StateStore, utc_now_iso
from .tasks import TaskRegistry

_ENV_KEY_RE = re.compile(r"^[A-Z0-9_]+$")


@dataclass(frozen=True)
class Services:
    settings: WebUISettings
    state: StateStore
    registry: TaskRegistry
    runner: RunQueueManager
    scheduler: SchedulerService
    config_files: ConfigFilesManager
    cipher: SecretCipher
    ui_root: Path


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _expired(expires_at: str) -> bool:
    try:
        dt = _parse_iso(expires_at)
    except Exception:
        return True
    return dt <= datetime.now(UTC)


def _resolve_ui_file(ui_root: Path, relative: str) -> Path | None:
    target = (ui_root / relative).resolve()
    try:
        target.relative_to(ui_root.resolve())
    except Exception:
        return None
    if target.is_file():
        return target
    return None


def _render_index(ui_root: Path, base_path: str) -> str:
    index_path = ui_root / "index.html"
    if not index_path.exists():
        return "<html><body><h1>Organizer UI build missing.</h1></body></html>"
    html = index_path.read_text(encoding="utf-8")
    return html.replace("__BASE_PATH__", base_path)


def _build_runtime_env(state: StateStore, cipher: SecretCipher) -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in state.list_settings().items():
        if _ENV_KEY_RE.match(key):
            env[key] = str(value)

    encrypted = state.list_encrypted_secrets()
    for key, encrypted_value in encrypted.items():
        if not _ENV_KEY_RE.match(key):
            continue
        try:
            env[key] = cipher.decrypt(encrypted_value)
        except Exception:
            continue
    return env


def _value_from_runtime(spec: EnvVarSpec, settings: dict[str, Any], secrets: dict[str, str], cipher: SecretCipher) -> tuple[str, str, bool]:
    if spec.secret:
        if spec.key in secrets:
            encrypted = secrets[spec.key]
            try:
                cipher.decrypt(encrypted)
                return "********", "ui_secret", True
            except Exception:
                return "********", "ui_secret_invalid", True
        if os.environ.get(spec.key, "").strip():
            return "********", "environment", True
        if spec.default:
            return "********", "default", False
        return "", "unset", False

    if spec.key in settings:
        return str(settings[spec.key]), "ui_setting", True
    raw_env = os.environ.get(spec.key)
    if raw_env is not None and raw_env != "":
        return str(raw_env), "environment", True
    if spec.default != "":
        return spec.default, "default", False
    return "", "unset", False


def _env_payload(state: StateStore, cipher: SecretCipher) -> dict[str, Any]:
    settings = state.list_settings()
    secrets = state.list_encrypted_secrets()
    payload: dict[str, Any] = {}
    for spec in ENV_VAR_SPECS:
        value, source, has_value = _value_from_runtime(spec, settings, secrets, cipher)
        payload[spec.key] = {
            "key": spec.key,
            "value": value,
            "source": source,
            "secret": spec.secret,
            "has_value": has_value,
            "default": spec.default,
            "description": spec.description,
        }
    return payload


def _require_services(request: Request) -> Services:
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise RuntimeError("Web UI services are not initialized.")
    return services


def _require_session(request: Request, services: Services = Depends(_require_services)) -> dict[str, Any]:
    token = request.cookies.get(services.settings.cookie_name, "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")

    services.state.purge_expired_sessions(utc_now_iso())
    session = services.state.get_session(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid session.")
    if _expired(str(session["expires_at"])):
        services.state.delete_session(token)
        raise HTTPException(status_code=401, detail="Session expired.")
    return session


def _schedule_payload_from_create(request: ScheduleCreateRequest) -> SchedulePayload:
    kind = request.kind
    if kind == "interval":
        seconds = int(request.seconds or 0)
        if seconds <= 0:
            raise HTTPException(status_code=422, detail="Interval schedules require positive 'seconds'.")
        data = {"seconds": seconds}
    else:
        expression = str(request.cron or "").strip()
        if not expression:
            raise HTTPException(status_code=422, detail="Cron schedules require 'cron'.")
        data = {"expression": expression}
    return SchedulePayload(
        name=request.name.strip(),
        task_id=request.task_id.strip(),
        schedule_kind=kind,
        schedule_data=data,
        options=request.options,
        enabled=bool(request.enabled),
    )


def _schedule_payload_from_update(existing: dict[str, Any], request: ScheduleUpdateRequest) -> SchedulePayload:
    kind = request.kind or str(existing["schedule_kind"])
    if kind == "interval":
        existing_seconds = int(dict(existing["schedule_data"]).get("seconds", 0))
        seconds = request.seconds if request.seconds is not None else existing_seconds
        if int(seconds) <= 0:
            raise HTTPException(status_code=422, detail="Interval schedules require positive 'seconds'.")
        data = {"seconds": int(seconds)}
    else:
        existing_cron = str(dict(existing["schedule_data"]).get("expression", ""))
        expression = str(request.cron if request.cron is not None else existing_cron).strip()
        if not expression:
            raise HTTPException(status_code=422, detail="Cron schedules require 'cron'.")
        data = {"expression": expression}
    return SchedulePayload(
        name=(request.name or str(existing["name"])).strip(),
        task_id=(request.task_id or str(existing["task_id"])).strip(),
        schedule_kind=kind,
        schedule_data=data,
        options=request.options if request.options is not None else dict(existing["options"]),
        enabled=bool(request.enabled if request.enabled is not None else existing["enabled"]),
    )


def _enforce_safety(services: Services, task_id: str, options: dict[str, Any]) -> None:
    execution = services.registry.build_execution(task_id, options)
    policies = services.state.list_task_policies()
    task_policy = policies.get(task_id, {"allow_dangerous": False})
    if execution.dangerous_requested and not bool(task_policy.get("allow_dangerous")):
        raise HTTPException(
            status_code=403,
            detail=f"Dangerous options are blocked for task '{task_id}'. Update /policies to allow.",
        )


def _select_ui_root(settings: WebUISettings) -> Path:
    if (settings.web_dist_dir / "index.html").exists():
        return settings.web_dist_dir
    return settings.static_dir


def create_app() -> FastAPI:
    settings = load_webui_settings()
    state = StateStore(settings.state_db_path)
    registry = TaskRegistry()
    state.initialize(registry.task_ids)
    cipher = SecretCipher(settings.fernet_key)

    if not state.has_users():
        if not settings.bootstrap_password:
            raise RuntimeError(
                "No web user exists. Set WEB_BOOTSTRAP_PASSWORD for first-time startup."
            )
        state.upsert_user(settings.bootstrap_user, hash_password(settings.bootstrap_password))
        print(f"[webui] bootstrapped login user '{settings.bootstrap_user}'", flush=True)

    config_files = ConfigFilesManager(settings.config_root)
    runner = RunQueueManager(
        state=state,
        registry=registry,
        environment_provider=lambda: _build_runtime_env(state, cipher),
        logs_dir=settings.logs_dir,
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

    app = FastAPI(title="Mealie Organizer Web UI", version="1.0", lifespan=lifespan)
    api_prefix = f"{settings.base_path}/api/v1"

    @app.get("/")
    async def root_redirect() -> Response:
        return RedirectResponse(url=settings.base_path, status_code=307)

    @app.get(f"{api_prefix}/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "base_path": settings.base_path}

    @app.post(f"{api_prefix}/auth/login")
    async def login(payload: LoginRequest, response: Response, services: Services = Depends(_require_services)) -> dict[str, Any]:
        username = payload.username.strip()
        password_hash = services.state.get_password_hash(username)
        if password_hash is None or not verify_password(payload.password, password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password.")
        token = new_session_token()
        expires_at = (datetime.now(UTC) + timedelta(seconds=services.settings.session_ttl_seconds)).isoformat().replace(
            "+00:00", "Z"
        )
        services.state.create_session(token=token, username=username, expires_at=expires_at)
        response.set_cookie(
            key=services.settings.cookie_name,
            value=token,
            httponly=True,
            secure=False,
            samesite="lax",
            path=services.settings.base_path,
        )
        return {"ok": True, "username": username, "expires_at": expires_at}

    @app.post(f"{api_prefix}/auth/logout")
    async def logout(
        request: Request,
        response: Response,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, bool]:
        token = request.cookies.get(services.settings.cookie_name, "").strip()
        if token:
            services.state.delete_session(token)
        response.delete_cookie(key=services.settings.cookie_name, path=services.settings.base_path)
        return {"ok": True}

    @app.get(f"{api_prefix}/auth/session")
    async def session_status(session: dict[str, Any] = Depends(_require_session)) -> dict[str, Any]:
        return {"authenticated": True, "username": session["username"], "expires_at": session["expires_at"]}

    @app.get(f"{api_prefix}/tasks")
    async def list_tasks(
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        tasks = services.registry.describe_tasks()
        policies = services.state.list_task_policies()
        for task in tasks:
            policy = policies.get(task["task_id"], {"allow_dangerous": False, "updated_at": None})
            task["policy"] = policy
        return {"items": tasks}

    @app.get(f"{api_prefix}/policies")
    async def get_policies(
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        return {"policies": services.state.list_task_policies()}

    @app.put(f"{api_prefix}/policies")
    async def put_policies(
        payload: PoliciesUpdateRequest,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        for task_id, item in payload.policies.items():
            if task_id not in services.registry.task_ids:
                raise HTTPException(status_code=404, detail=f"Unknown task '{task_id}'.")
            services.state.set_task_policy(task_id, bool(item.allow_dangerous))
        return {"policies": services.state.list_task_policies()}

    @app.post(f"{api_prefix}/runs", status_code=202)
    async def create_run(
        payload: RunCreateRequest,
        session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        task_id = payload.task_id.strip()
        if task_id not in services.registry.task_ids:
            raise HTTPException(status_code=404, detail=f"Unknown task '{task_id}'.")
        options = dict(payload.options)
        _enforce_safety(services, task_id, options)
        return services.runner.enqueue(task_id=task_id, options=options, triggered_by=str(session["username"]))

    @app.get(f"{api_prefix}/runs")
    async def list_runs(
        limit: int = 100,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        value = min(max(limit, 1), 500)
        return {"items": services.state.list_runs(limit=value)}

    @app.get(f"{api_prefix}/runs/{{run_id}}")
    async def get_run(
        run_id: str,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        run = services.state.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return run

    @app.get(f"{api_prefix}/runs/{{run_id}}/log")
    async def get_run_log(
        run_id: str,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> PlainTextResponse:
        try:
            text = services.runner.read_log(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Run not found.")
        return PlainTextResponse(text)

    @app.post(f"{api_prefix}/runs/{{run_id}}/cancel")
    async def cancel_run(
        run_id: str,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        if not services.runner.cancel(run_id):
            raise HTTPException(status_code=409, detail="Run cannot be canceled.")
        run = services.state.get_run(run_id)
        return {"ok": True, "run": run}

    @app.get(f"{api_prefix}/schedules")
    async def list_schedules(
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        return {"items": services.scheduler.list_schedules()}

    @app.post(f"{api_prefix}/schedules", status_code=201)
    async def create_schedule(
        payload: ScheduleCreateRequest,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        if payload.task_id.strip() not in services.registry.task_ids:
            raise HTTPException(status_code=404, detail=f"Unknown task '{payload.task_id}'.")
        _enforce_safety(services, payload.task_id.strip(), dict(payload.options))
        schedule_payload = _schedule_payload_from_create(payload)
        return services.scheduler.create_schedule(schedule_payload)

    @app.patch(f"{api_prefix}/schedules/{{schedule_id}}")
    async def update_schedule(
        schedule_id: str,
        payload: ScheduleUpdateRequest,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        existing = services.state.get_schedule(schedule_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Schedule not found.")
        schedule_payload = _schedule_payload_from_update(existing, payload)
        if schedule_payload.task_id not in services.registry.task_ids:
            raise HTTPException(status_code=404, detail=f"Unknown task '{schedule_payload.task_id}'.")
        _enforce_safety(services, schedule_payload.task_id, dict(schedule_payload.options))
        updated = services.scheduler.update_schedule(schedule_id, schedule_payload)
        if updated is None:
            raise HTTPException(status_code=404, detail="Schedule not found.")
        return updated

    @app.delete(f"{api_prefix}/schedules/{{schedule_id}}")
    async def delete_schedule(
        schedule_id: str,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, bool]:
        if not services.scheduler.delete_schedule(schedule_id):
            raise HTTPException(status_code=404, detail="Schedule not found.")
        return {"ok": True}

    @app.get(f"{api_prefix}/settings")
    async def get_settings(
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        secret_keys = sorted(services.state.list_encrypted_secrets().keys())
        return {
            "settings": services.state.list_settings(),
            "secrets": {key: "********" for key in secret_keys},
            "env": _env_payload(services.state, services.cipher),
        }

    @app.put(f"{api_prefix}/settings")
    async def put_settings(
        payload: SettingsUpdateRequest,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        if payload.settings:
            services.state.set_settings(payload.settings)

        for key, value in payload.secrets.items():
            key_name = key.strip()
            if not key_name:
                continue
            if value is None or str(value) == "":
                services.state.delete_secret(key_name)
                continue
            services.state.set_secret(key_name, services.cipher.encrypt(str(value)))

        for key, value in payload.env.items():
            key_name = key.strip().upper()
            if not key_name:
                continue
            spec = ENV_SPEC_BY_KEY.get(key_name)
            if spec is None:
                raise HTTPException(status_code=422, detail=f"Unsupported environment key: {key_name}")
            if value is None or str(value).strip() == "":
                if spec.secret:
                    services.state.delete_secret(key_name)
                else:
                    services.state.delete_setting(key_name)
                continue
            if spec.secret:
                services.state.set_secret(key_name, services.cipher.encrypt(str(value)))
            else:
                services.state.set_settings({key_name: str(value)})

        return await get_settings(_session, services)

    @app.get(f"{api_prefix}/config/files")
    async def list_config_files(
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        return {"items": services.config_files.list_files()}

    @app.get(f"{api_prefix}/config/files/{{name}}")
    async def get_config_file(
        name: str,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        try:
            return services.config_files.read_file(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown config file.")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Config file not found.")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"Invalid JSON in file: {exc}")

    @app.put(f"{api_prefix}/config/files/{{name}}")
    async def put_config_file(
        name: str,
        payload: ConfigWriteRequest,
        _session: dict[str, Any] = Depends(_require_session),
        services: Services = Depends(_require_services),
    ) -> dict[str, Any]:
        try:
            return services.config_files.write_file(name, payload.content)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown config file.")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

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
