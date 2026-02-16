from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

from ..config import REPO_ROOT

DEFAULT_BASE_PATH = "/organizer"
DEFAULT_DB_PATH = "cache/webui/state.db"
DEFAULT_BIND_HOST = "0.0.0.0"
DEFAULT_BIND_PORT = 4820
DEFAULT_SESSION_TTL_SECONDS = 43_200
DEFAULT_BOOTSTRAP_USER = "admin"
DEFAULT_COOKIE_NAME = "mo_webui_session"


@dataclass(frozen=True)
class WebUISettings:
    bind_host: str
    bind_port: int
    base_path: str
    state_db_path: Path
    session_ttl_seconds: int
    bootstrap_user: str
    bootstrap_password: str
    fernet_key: str
    cookie_name: str
    static_dir: Path
    web_dist_dir: Path
    logs_dir: Path
    config_root: Path


def _normalize_base_path(raw: str) -> str:
    base = raw.strip() or DEFAULT_BASE_PATH
    if not base.startswith("/"):
        base = f"/{base}"
    return base.rstrip("/") or DEFAULT_BASE_PATH


def _normalize_fernet_key(raw: str) -> str:
    candidate = raw.strip()
    if not candidate:
        raise RuntimeError("MO_WEBUI_MASTER_KEY is required for Web UI secrets encryption.")
    try:
        Fernet(candidate.encode("utf-8"))
        return candidate
    except Exception:
        digest = hashlib.sha256(candidate.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8")


def _load_master_key() -> str:
    value = os.environ.get("MO_WEBUI_MASTER_KEY", "").strip()
    if value:
        return _normalize_fernet_key(value)

    key_file = os.environ.get("MO_WEBUI_MASTER_KEY_FILE", "").strip()
    if key_file:
        path = Path(key_file).expanduser().resolve()
        if not path.exists():
            raise RuntimeError(f"MO_WEBUI_MASTER_KEY_FILE does not exist: {path}")
        return _normalize_fernet_key(path.read_text(encoding="utf-8").strip())

    raise RuntimeError(
        "Missing encryption key. Set MO_WEBUI_MASTER_KEY or MO_WEBUI_MASTER_KEY_FILE."
    )


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


def load_webui_settings() -> WebUISettings:
    bind_host = os.environ.get("WEB_BIND_HOST", DEFAULT_BIND_HOST).strip() or DEFAULT_BIND_HOST
    bind_port = _int_env("WEB_BIND_PORT", DEFAULT_BIND_PORT)
    base_path = _normalize_base_path(os.environ.get("WEB_BASE_PATH", DEFAULT_BASE_PATH))
    db_raw = os.environ.get("WEB_STATE_DB_PATH", DEFAULT_DB_PATH).strip() or DEFAULT_DB_PATH
    state_db_path = Path(db_raw)
    if not state_db_path.is_absolute():
        state_db_path = REPO_ROOT / state_db_path
    state_db_path = state_db_path.resolve()

    logs_dir = REPO_ROOT / "logs" / "webui" / "runs"
    static_dir = Path(__file__).resolve().parent / "static"
    web_dist_dir = (REPO_ROOT / "web" / "dist").resolve()
    config_root_raw = os.environ.get("WEB_CONFIG_ROOT", "").strip()
    if config_root_raw:
        config_root = Path(config_root_raw)
        if not config_root.is_absolute():
            config_root = (REPO_ROOT / config_root).resolve()
    else:
        config_root = REPO_ROOT

    session_ttl = _int_env("WEB_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS)
    bootstrap_user = os.environ.get("WEB_BOOTSTRAP_USER", DEFAULT_BOOTSTRAP_USER).strip() or DEFAULT_BOOTSTRAP_USER
    bootstrap_password = os.environ.get("WEB_BOOTSTRAP_PASSWORD", "").strip()
    cookie_name = os.environ.get("WEB_SESSION_COOKIE_NAME", DEFAULT_COOKIE_NAME).strip() or DEFAULT_COOKIE_NAME

    return WebUISettings(
        bind_host=bind_host,
        bind_port=bind_port,
        base_path=base_path,
        state_db_path=state_db_path,
        session_ttl_seconds=session_ttl,
        bootstrap_user=bootstrap_user,
        bootstrap_password=bootstrap_password,
        fernet_key=_load_master_key(),
        cookie_name=cookie_name,
        static_dir=static_dir,
        web_dist_dir=web_dist_dir,
        logs_dir=logs_dir,
        config_root=config_root,
    )
