from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request

from .config_files import ConfigFilesManager
from .env_catalog import ENV_SPEC_BY_KEY, EnvVarSpec
from .runner import RunQueueManager
from .scheduler import SchedulerService
from .security import SecretCipher
from .settings import WebUISettings
from .state import StateStore
from .tasks import TaskRegistry

_ENV_KEY_RE = re.compile(r"^[A-Z0-9_]+$")
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,64}$")


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
    except (ValueError, TypeError):
        return True
    return dt <= datetime.now(timezone.utc)


def require_services(request: Request) -> Services:
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise RuntimeError("Web UI services are not initialized.")
    return services


def require_session(request: Request, services: Services = Depends(require_services)) -> dict[str, Any]:
    from .state import utc_now_iso

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


def normalize_username(raw: str) -> str:
    username = raw.strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(
            status_code=422,
            detail="Username must be 3-64 characters and use letters, numbers, underscore, dot, or dash.",
        )
    return username


def build_runtime_env(state: StateStore, cipher: SecretCipher) -> dict[str, str]:
    from .env_catalog import ENV_VAR_SPECS

    # Start with os.environ values for known env-catalog keys
    env: dict[str, str] = {}
    for spec in ENV_VAR_SPECS:
        raw = os.environ.get(spec.key, "").strip()
        if raw:
            env[spec.key] = raw

    # UI-saved settings override os.environ
    for key, value in state.list_settings().items():
        if _ENV_KEY_RE.match(key):
            env[key] = str(value)

    # UI-saved encrypted secrets override everything
    encrypted = state.list_encrypted_secrets()
    for key, encrypted_value in encrypted.items():
        if not _ENV_KEY_RE.match(key):
            continue
        try:
            env[key] = cipher.decrypt(encrypted_value)
        except ValueError:
            continue
    return env


def enforce_safety(services: Services, task_id: str, options: dict[str, Any]) -> None:
    execution = services.registry.build_execution(task_id, options)
    policies = services.state.list_task_policies()
    task_policy = policies.get(task_id, {"allow_dangerous": False})
    if execution.dangerous_requested and not bool(task_policy.get("allow_dangerous")):
        raise HTTPException(
            status_code=403,
            detail=f"Dangerous options are blocked for task '{task_id}'. Update /policies to allow.",
        )


def resolve_runtime_value(runtime_env: dict[str, str], key: str, override: str | None = None) -> str:
    if override is not None:
        return str(override).strip()
    return str(runtime_env.get(key, "")).strip()


def value_from_runtime(
    spec: EnvVarSpec,
    settings: dict[str, Any],
    secrets: dict[str, str],
    cipher: SecretCipher,
) -> tuple[str, str, bool]:
    if spec.secret:
        if spec.key in secrets:
            encrypted = secrets[spec.key]
            try:
                cipher.decrypt(encrypted)
                return "********", "ui_secret", True
            except ValueError:
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


def env_payload(state: StateStore, cipher: SecretCipher) -> dict[str, Any]:
    from .env_catalog import ENV_VAR_SPECS

    settings = state.list_settings()
    secrets = state.list_encrypted_secrets()
    payload: dict[str, Any] = {}
    for spec in ENV_VAR_SPECS:
        value, source, has_value = value_from_runtime(spec, settings, secrets, cipher)
        payload[spec.key] = {
            "key": spec.key,
            "label": spec.label,
            "group": spec.group,
            "value": value,
            "source": source,
            "secret": spec.secret,
            "has_value": has_value,
            "default": spec.default,
            "description": spec.description,
            "choices": list(spec.choices),
        }
    return payload
