from __future__ import annotations

import ipaddress
import os
import re
import shlex
import socket
import subprocess
import tempfile
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException

from ..deps import (
    Services,
    build_runtime_env,
    env_payload,
    resolve_runtime_value,
    require_services,
    require_session,
)
from ..env_catalog import ENV_SPEC_BY_KEY
from ..schemas import (
    DbDetectRequest,
    DredgerSiteCreateRequest,
    DredgerSitesSeedRequest,
    DredgerSitesValidateRequest,
    DredgerSiteUpdateRequest,
    ProviderConnectionTestRequest,
    SettingsUpdateRequest,
)

router = APIRouter(tags=["settings"])


def _validate_service_url(url: str, *, allow_private: bool = False) -> str:
    """Validate that a URL is safe for server-side requests (SSRF protection).

    Checks scheme, resolves DNS, and blocks private/link-local/loopback IPs
    unless *allow_private* is True (e.g. for user-configured Mealie/Ollama on LAN).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https.")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL must include a hostname.")

    # Block well-known cloud metadata hostnames
    _blocked_hosts = {"metadata.google.internal"}
    if host in _blocked_hosts:
        raise ValueError("Requests to cloud metadata endpoints are not allowed.")

    # Resolve hostname and check IP
    try:
        addr_info = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError(f"Could not resolve hostname: {host}")

    for family, _, _, _, sockaddr in addr_info:
        ip = ipaddress.ip_address(sockaddr[0])
        # Always block link-local (169.254.x.x / fe80::) — covers AWS/Azure metadata
        if ip.is_link_local:
            raise ValueError("Requests to link-local addresses are not allowed.")
        if not allow_private and (ip.is_private or ip.is_loopback or ip.is_reserved):
            raise ValueError("Requests to private/internal addresses are not allowed.")

    return url


def _safe_request_error(exc: requests.RequestException) -> str:
    """Return a user-friendly error without leaking stack traces."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is not None:
        return f"Request failed with HTTP {status}."
    return f"Connection failed: {type(exc).__name__}."


def _test_mealie_connection(url: str, api_key: str) -> tuple[bool, str]:
    base_url = _validate_service_url(url.rstrip("/"), allow_private=True)
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    try:
        response = requests.get(f"{base_url}/users/self", headers=headers, timeout=12)
        response.raise_for_status()
        return True, "Mealie connection validated."
    except requests.RequestException as exc:
        return False, _safe_request_error(exc)


def _test_openai_connection(api_key: str, model: str) -> tuple[bool, str]:
    if not api_key:
        return False, "OpenAI API key is required."
    endpoint = "https://api.openai.com/v1/chat/completions"
    body = {
        "model": model or "gpt-4o-mini",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(endpoint, headers=headers, json=body, timeout=15)
        response.raise_for_status()
        return True, "OpenAI API key validated."
    except requests.RequestException as exc:
        return False, _safe_request_error(exc)


def _test_anthropic_connection(api_key: str, model: str) -> tuple[bool, str]:
    if not api_key:
        return False, "Anthropic API key is required."
    endpoint = "https://api.anthropic.com/v1/messages"
    body = {
        "model": model or "claude-haiku-4-5-20251001",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(endpoint, headers=headers, json=body, timeout=15)
        response.raise_for_status()
        return True, "Anthropic API key validated."
    except requests.RequestException as exc:
        return False, _safe_request_error(exc)


def _test_ollama_connection(url: str, model: str) -> tuple[bool, str]:
    base_url = _validate_service_url(url.strip().rstrip("/"), allow_private=True)
    if not base_url:
        return False, "Ollama URL is required."

    if base_url.endswith("/api"):
        tags_url = f"{base_url}/tags"
    elif base_url.endswith("/api/tags"):
        tags_url = base_url
    else:
        tags_url = f"{base_url}/api/tags"

    try:
        # URL validated by _validate_service_url above (scheme + metadata block).
        response = requests.get(tags_url, timeout=12)  # nosec B113
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models") if isinstance(payload, dict) else None
        if isinstance(models, list) and model:
            found = any(str(item.get("name") or "").startswith(model) for item in models if isinstance(item, dict))
            if not found:
                return True, f"Connection OK, model '{model}' was not listed by Ollama."
        return True, "Ollama connection validated."
    except ValueError:
        return False, "Invalid response from Ollama server."
    except requests.RequestException as exc:
        return False, _safe_request_error(exc)


@router.get("/settings")
async def get_settings(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    secret_keys = sorted(services.state.list_encrypted_secrets().keys())
    return {
        "settings": services.state.list_settings(),
        "secrets": {key: "********" for key in secret_keys},
        "env": env_payload(services.state, services.cipher),
    }


def _payload_has_secret_values(payload: SettingsUpdateRequest) -> bool:
    """Return True if the payload contains any non-empty secret values to encrypt."""
    for value in payload.secrets.values():
        if value is not None and str(value) != "":
            return True
    for key, value in payload.env.items():
        if value is None or str(value).strip() == "":
            continue
        spec = ENV_SPEC_BY_KEY.get(key.strip().upper())
        if spec is not None and spec.secret:
            return True
    return False


@router.put("/settings")
async def put_settings(
    payload: SettingsUpdateRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    if services.settings.weak_master_key and _payload_has_secret_values(payload):
        raise HTTPException(
            status_code=400,
            detail="Cannot store secrets: MO_WEBUI_MASTER_KEY is set to a weak default. "
            "Set a strong key and restart.",
        )

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


# Recommended chat-capable models for recipe categorization tasks.
# Kept as an ordered list: best value first. The API response is
# cross-referenced so only models the key can actually access appear.
_OPENAI_RECOMMENDED = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-nano",
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-4-turbo",
    "o4-mini",
    "o3-mini",
    "gpt-3.5-turbo",
)

# Anthropic models suitable for recipe categorization, best value first.
_ANTHROPIC_RECOMMENDED = (
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250514",
    "claude-sonnet-4-20250514",
    "claude-3-5-haiku-20241022",
    "claude-3-5-sonnet-20241022",
)


def _list_openai_models(api_key: str) -> list[str]:
    if not api_key:
        return []
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = requests.get("https://api.openai.com/v1/models", headers=headers, timeout=12)
        response.raise_for_status()
        data = response.json()
        available = {str(m.get("id", "")) for m in (data.get("data") or []) if isinstance(m, dict)}
        return [m for m in _OPENAI_RECOMMENDED if m in available]
    except requests.RequestException:
        return []


def _list_ollama_models(url: str) -> list[str]:
    base_url = (url or "").strip().rstrip("/")
    if not base_url:
        return []
    try:
        _validate_service_url(base_url, allow_private=True)
    except ValueError:
        return []
    if base_url.endswith("/api"):
        tags_url = f"{base_url}/tags"
    elif base_url.endswith("/api/tags"):
        tags_url = base_url
    else:
        tags_url = f"{base_url}/api/tags"
    try:
        # URL validated by _validate_service_url above (scheme + metadata block).
        response = requests.get(tags_url, timeout=12)  # nosec B113
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return []
        return sorted(
            str(m.get("name", ""))
            for m in models
            if isinstance(m, dict) and m.get("name")
        )
    except requests.RequestException:
        return []


def _list_anthropic_models(api_key: str) -> list[str]:
    if not api_key:
        return []
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    try:
        response = requests.get("https://api.anthropic.com/v1/models", headers=headers, timeout=12)
        response.raise_for_status()
        data = response.json()
        available = {str(m.get("id", "")) for m in (data.get("data") or []) if isinstance(m, dict)}
        result = [m for m in _ANTHROPIC_RECOMMENDED if m in available]
        # Include any available models not in recommended list
        extras = sorted(mid for mid in available if mid.startswith("claude-") and mid not in result)
        return result + extras
    except requests.RequestException:
        # Fall back to recommended list without validation
        return list(_ANTHROPIC_RECOMMENDED)


@router.post("/settings/models/openai")
async def list_openai_models(
    payload: ProviderConnectionTestRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    runtime_env = build_runtime_env(services.state, services.cipher)
    api_key = resolve_runtime_value(runtime_env, "OPENAI_API_KEY", payload.openai_api_key)
    models = _list_openai_models(api_key)
    return {"ok": bool(models), "models": models}


@router.post("/settings/models/ollama")
async def list_ollama_models(
    payload: ProviderConnectionTestRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    runtime_env = build_runtime_env(services.state, services.cipher)
    ollama_url = resolve_runtime_value(runtime_env, "OLLAMA_URL", payload.ollama_url)
    models = _list_ollama_models(ollama_url)
    return {"ok": bool(models), "models": models}


@router.post("/settings/models/anthropic")
async def list_anthropic_models(
    payload: ProviderConnectionTestRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    runtime_env = build_runtime_env(services.state, services.cipher)
    api_key = resolve_runtime_value(runtime_env, "ANTHROPIC_API_KEY", payload.anthropic_api_key)
    models = _list_anthropic_models(api_key)
    return {"ok": bool(models), "models": models}


@router.post("/settings/test/mealie")
async def test_mealie_settings(
    payload: ProviderConnectionTestRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    runtime_env = build_runtime_env(services.state, services.cipher)
    mealie_url = resolve_runtime_value(runtime_env, "MEALIE_URL", payload.mealie_url).rstrip("/")
    mealie_api_key = resolve_runtime_value(runtime_env, "MEALIE_API_KEY", payload.mealie_api_key)
    if not mealie_url or not mealie_api_key:
        return {"ok": False, "detail": "Mealie URL and API key are required."}
    ok, detail = _test_mealie_connection(mealie_url, mealie_api_key)
    return {"ok": ok, "detail": detail}


@router.post("/settings/test/openai")
async def test_openai_settings(
    payload: ProviderConnectionTestRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    runtime_env = build_runtime_env(services.state, services.cipher)
    openai_api_key = resolve_runtime_value(runtime_env, "OPENAI_API_KEY", payload.openai_api_key)
    openai_model = resolve_runtime_value(runtime_env, "OPENAI_MODEL", payload.openai_model) or "gpt-4o-mini"
    ok, detail = _test_openai_connection(openai_api_key, openai_model)
    return {"ok": ok, "detail": detail, "model": openai_model}


@router.post("/settings/test/ollama")
async def test_ollama_settings(
    payload: ProviderConnectionTestRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    runtime_env = build_runtime_env(services.state, services.cipher)
    ollama_url = resolve_runtime_value(runtime_env, "OLLAMA_URL", payload.ollama_url)
    ollama_model = resolve_runtime_value(runtime_env, "OLLAMA_MODEL", payload.ollama_model)
    ok, detail = _test_ollama_connection(ollama_url, ollama_model)
    return {"ok": ok, "detail": detail, "model": ollama_model}


@router.post("/settings/test/anthropic")
async def test_anthropic_settings(
    payload: ProviderConnectionTestRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    runtime_env = build_runtime_env(services.state, services.cipher)
    anthropic_api_key = resolve_runtime_value(runtime_env, "ANTHROPIC_API_KEY", payload.anthropic_api_key)
    anthropic_model = resolve_runtime_value(runtime_env, "ANTHROPIC_MODEL", payload.anthropic_model) or "claude-haiku-4-5-20251001"
    ok, detail = _test_anthropic_connection(anthropic_api_key, anthropic_model)
    return {"ok": ok, "detail": detail, "model": anthropic_model}


_DB_ENV_KEYS = (
    "MEALIE_DB_TYPE",
    "MEALIE_PG_HOST",
    "MEALIE_PG_PORT",
    "MEALIE_PG_DB",
    "MEALIE_PG_USER",
    "MEALIE_PG_PASS",
    "MEALIE_DB_SSH_HOST",
    "MEALIE_DB_SSH_USER",
    "MEALIE_DB_SSH_KEY",
)


_ALLOWED_DB_TYPES = frozenset({"postgres", "sqlite"})


def _test_db_connection(runtime_env: dict[str, str]) -> tuple[bool, str]:
    db_type_val = runtime_env.get("MEALIE_DB_TYPE", "").strip().lower()
    if not db_type_val:
        return False, "MEALIE_DB_TYPE is not configured. Set it to 'postgres' or 'sqlite'."
    if db_type_val not in _ALLOWED_DB_TYPES:
        return False, f"Unsupported MEALIE_DB_TYPE '{db_type_val}'. Use 'postgres' or 'sqlite'."

    saved: dict[str, str | None] = {}
    try:
        for key in _DB_ENV_KEYS:
            saved[key] = os.environ.get(key)
            val = str(runtime_env.get(key, "")).strip()
            if "\x00" in val or "\n" in val:
                continue
            if val:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)

        from cookdex.db_client import MealieDBClient

        with MealieDBClient() as db:
            group_id = db.get_group_id()
        if group_id:
            return True, f"DB connection validated. Group: {group_id[:8]}\u2026"
        return True, "DB connection validated (no household found, but connection succeeded)."
    except Exception as exc:
        return False, f"DB connection failed: {type(exc).__name__}."
    finally:
        for key, val in saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


@router.post("/settings/test/db")
async def test_db_settings(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    runtime_env = build_runtime_env(services.state, services.cipher)
    ok, detail = _test_db_connection(runtime_env)
    return {"ok": ok, "detail": detail}


# ------------------------------------------------------------------
# DB auto-detect via SSH
# ------------------------------------------------------------------

# Mealie container env vars → CookDex env var names
_MEALIE_ENV_MAP: dict[str, str] = {
    "POSTGRES_USER": "MEALIE_PG_USER",
    "POSTGRES_PASSWORD": "MEALIE_PG_PASS",
    "POSTGRES_DB": "MEALIE_PG_DB",
    "POSTGRES_SERVER": "MEALIE_PG_HOST",
    "POSTGRES_PORT": "MEALIE_PG_PORT",
    "DB_ENGINE": "MEALIE_DB_TYPE",
}
_MEALIE_FILE_ENV_MAP: dict[str, str] = {
    "POSTGRES_USER_FILE": "MEALIE_PG_USER",
    "POSTGRES_PASSWORD_FILE": "MEALIE_PG_PASS",
    "POSTGRES_DB_FILE": "MEALIE_PG_DB",
    "POSTGRES_SERVER_FILE": "MEALIE_PG_HOST",
    "POSTGRES_PORT_FILE": "MEALIE_PG_PORT",
    "DB_ENGINE_FILE": "MEALIE_DB_TYPE",
    "POSTGRES_URL_OVERRIDE_FILE": "POSTGRES_URL_OVERRIDE",
}
_MEALIE_RAW_DB_KEYS = set(_MEALIE_ENV_MAP) | set(_MEALIE_FILE_ENV_MAP) | {"POSTGRES_URL_OVERRIDE"}


def _validated_ssh_host(value: str) -> str:
    """Validate an SSH hostname/IP to prevent argument injection."""
    clean = str(value or "").strip()
    m = re.fullmatch(r"[A-Za-z0-9._:%-]+", clean) if clean else None
    if not m:
        raise ValueError("Invalid SSH host.")
    return m.group()


def _validated_ssh_user(value: str) -> str:
    """Validate an SSH username to prevent argument injection."""
    clean = str(value or "").strip()
    m = re.fullmatch(r"[A-Za-z0-9._-]+", clean) if clean else None
    if not m:
        raise ValueError("Invalid SSH user.")
    return m.group()


def _validated_container_name(value: str) -> str:
    """Validate a Docker container name to prevent command injection."""
    clean = str(value or "").strip()
    m = re.fullmatch(r"[A-Za-z0-9._/-]+", clean) if clean else None
    if not m:
        raise ValueError("Invalid container name.")
    return m.group()


def _validated_ssh_key_path(raw_path: str) -> str:
    """Resolve a user-provided SSH key path safely within ``~/.ssh/``.

    Accepts a plain filename (e.g. ``cookdex_mealie``) or a path that
    includes ``~/.ssh/`` (e.g. ``~/.ssh/cookdex_mealie``).  The resolved
    file **must** reside directly inside ``~/.ssh/`` — paths that escape
    that directory are rejected to prevent path-traversal attacks.
    """
    candidate = str(raw_path or "").strip()
    if not candidate:
        raise ValueError("Invalid SSH key path.")

    ssh_dir = os.path.realpath(os.path.expanduser("~/.ssh"))

    # Extract just the filename; ignore any directory components the
    # caller may have supplied so the result is always inside ~/.ssh/.
    target_name = os.path.basename(os.path.expanduser(candidate))
    if not target_name or target_name.startswith("."):
        raise ValueError("Invalid SSH key filename.")

    # Verify the file exists by enumerating ~/.ssh/ entries rather than
    # passing user-derived data to filesystem APIs (prevents path-injection
    # taint flow).
    try:
        dir_entries = os.listdir(ssh_dir)
    except OSError:
        raise FileNotFoundError("SSH key not found.")

    # Match against the directory listing (untainted source) and build the
    # return path from the listing entry, breaking the taint chain.
    matched = next((e for e in dir_entries if e == target_name), None)
    if matched is None:
        raise FileNotFoundError("SSH key not found.")

    safe_path = os.path.realpath(os.path.join(ssh_dir, matched))

    # Belt-and-suspenders: ensure the resolved path is under ~/.ssh/.
    if not safe_path.startswith(ssh_dir + os.sep) and safe_path != ssh_dir:
        raise ValueError("SSH key path escapes ~/.ssh/.")

    if not os.path.isfile(safe_path):
        raise FileNotFoundError("SSH key not found.")

    return safe_path


def _subprocess_ssh(
    host: str, user: str, key_path: str, command: str, timeout: int,
) -> tuple[str, str, int]:
    """Run an SSH command via subprocess using a temporary config file.

    All user-derived values (host, user, key path) are written to a
    temporary SSH config file rather than passed as command-line arguments,
    preventing command-line injection.  The remote command is delivered via
    stdin to a remote ``sh`` process.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ssh_config", delete=False, prefix="cookdex_ssh_",
    ) as cfg:
        cfg.write(f"Host target\n")
        cfg.write(f"  Hostname {host}\n")
        cfg.write(f"  User {user}\n")
        cfg.write(f"  IdentityFile {key_path}\n")
        cfg.write(f"  BatchMode yes\n")
        cfg.write(f"  ConnectTimeout {max(3, timeout)}\n")
        cfg.write(f"  StrictHostKeyChecking accept-new\n")
        cfg.write(f"  PasswordAuthentication no\n")
        config_path = cfg.name

    try:
        completed = subprocess.run(
            ["ssh", "-F", config_path, "target", "sh"],
            input=command,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
            check=False,
        )
        return completed.stdout, completed.stderr, int(completed.returncode)
    finally:
        try:
            os.unlink(config_path)
        except OSError:
            pass


def _ssh_exec(
    host: str,
    user: str,
    key_path: str,
    command: str,
    *,
    timeout: int = 15,
) -> tuple[str, str, int]:
    """Run a single command over SSH and return (stdout, stderr, exit_code)."""
    host = _validated_ssh_host(host)
    user = _validated_ssh_user(user)
    resolved_key = _validated_ssh_key_path(key_path)

    # Prefer paramiko when available; fall back to native ssh binary.
    try:
        import paramiko
    except ModuleNotFoundError:
        paramiko = None  # type: ignore[assignment]

    if paramiko is None:
        return _subprocess_ssh(host, user, resolved_key, command, timeout)

    known_hosts = os.path.join(
        os.path.realpath(os.path.expanduser("~/.ssh")), "known_hosts",
    )

    class _TofuPolicy(paramiko.MissingHostKeyPolicy):
        """Trust-on-first-use: persist new host keys, reject changes."""

        def missing_host_key(
            self,
            client: paramiko.SSHClient,
            hostname: str,
            key: paramiko.PKey,
        ) -> None:
            host_keys = paramiko.HostKeys()
            if os.path.isfile(known_hosts):
                host_keys.load(known_hosts)
            entry = host_keys.lookup(hostname)
            if entry is not None:
                stored = entry.get(key.get_name())
                if stored is not None:
                    if stored == key:
                        return
                    raise paramiko.SSHException(
                        f"Host key for '{hostname}' has changed."
                    )
            host_keys.add(hostname, key.get_name(), key)
            os.makedirs(os.path.dirname(known_hosts), exist_ok=True)
            host_keys.save(known_hosts)

    client = paramiko.SSHClient()  # type: ignore[union-attr]
    client.set_missing_host_key_policy(_TofuPolicy())  # type: ignore[union-attr]
    try:
        try:
            client.connect(
                hostname=host,
                username=user,
                key_filename=resolved_key,
                timeout=timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            return (
                stdout.read().decode("utf-8", errors="replace"),
                stderr.read().decode("utf-8", errors="replace"),
                exit_code,
            )
        except Exception:
            return _subprocess_ssh(host, user, resolved_key, command, timeout)
    finally:
        client.close()


def _parse_mealie_env(text: str) -> dict[str, str]:
    """Parse Mealie DB env assignments and map to CookDex DB keys."""
    import re

    raw: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if line.lower().startswith("export "):
            line = line[7:].strip()

        key = ""
        value = ""
        if "=" in line:
            key, _, value = line.partition("=")
        elif ":" in line:
            key, _, value = line.partition(":")
            if " #" in value:
                value = value.split(" #", 1)[0].rstrip()
        else:
            continue

        key = key.strip().strip("'\"").upper()
        if not re.match(r"^[A-Z0-9_]+$", key):
            continue
        value = value.strip().strip("'\"")
        if key in _MEALIE_RAW_DB_KEYS and value:
            raw[key] = value

    result: dict[str, str] = {}
    for key, cookdex_key in _MEALIE_ENV_MAP.items():
        value = raw.get(key)
        if value:
            result[cookdex_key] = value

    # If *_FILE variants are set (Mealie docs: Docker secrets), they take precedence.
    for key, cookdex_key in _MEALIE_FILE_ENV_MAP.items():
        if cookdex_key == "POSTGRES_URL_OVERRIDE":
            continue
        value = raw.get(key)
        if not value:
            continue
        # Keep path around for later remote resolution.
        result[f"__FILE__:{cookdex_key}"] = value

    # POSTGRES_URL_OVERRIDE has priority over individual POSTGRES_* values.
    override = raw.get("POSTGRES_URL_OVERRIDE") or raw.get("POSTGRES_URL_OVERRIDE_FILE")
    if override:
        parsed = urlparse(override if "://" in override else f"postgresql://{override}")
        if parsed.hostname:
            result["MEALIE_PG_HOST"] = parsed.hostname
        if parsed.port:
            result["MEALIE_PG_PORT"] = str(parsed.port)
        if parsed.path and parsed.path.strip("/"):
            result["MEALIE_PG_DB"] = parsed.path.strip("/")
        if parsed.username:
            result["MEALIE_PG_USER"] = unquote(parsed.username)
        if parsed.password:
            result["MEALIE_PG_PASS"] = unquote(parsed.password)
        result["MEALIE_DB_TYPE"] = "postgres"

    # Infer DB type from presence of Postgres vars if DB_ENGINE not set
    if "MEALIE_DB_TYPE" not in result and (
        "MEALIE_PG_USER" in result or
        "MEALIE_PG_HOST" in result or
        "MEALIE_PG_DB" in result
    ):
        result["MEALIE_DB_TYPE"] = "postgres"

    # If POSTGRES_SERVER is a Docker service name, map to localhost (tunnel handles routing)
    pg_host = result.get("MEALIE_PG_HOST", "")
    if pg_host and not re.match(r"^(\d{1,3}\.){3}\d{1,3}$|^localhost$|^\[", pg_host):
        result["MEALIE_PG_HOST"] = "localhost"

    return result


def _parse_env_probe_blocks(text: str) -> list[tuple[str, str]]:
    marker = "__CFG_FILE__:"
    blocks: list[tuple[str, str]] = []
    current_path = ""
    current_lines: list[str] = []
    seen_paths: set[str] = set()

    for raw_line in text.splitlines():
        line = str(raw_line).strip()
        if line.startswith(marker):
            if current_path and current_path not in seen_paths:
                blocks.append((current_path, "\n".join(current_lines)))
                seen_paths.add(current_path)
            current_path = line[len(marker) :].strip()
            current_lines = []
            continue
        if current_path:
            current_lines.append(line)

    if current_path and current_path not in seen_paths:
        blocks.append((current_path, "\n".join(current_lines)))

    return blocks


def _detect_db_credentials_from_env_files(
    ssh_host: str, ssh_user: str, ssh_key: str,
) -> tuple[bool, str, dict[str, str]]:
    probe_cmd = r"""
set +e
emit() {
  p="$1"
  if [ -r "$p" ] && grep -q -E '(DB_ENGINE|POSTGRES_(USER|PASSWORD|DB|SERVER|PORT|URL_OVERRIDE)(_FILE)?|EnvironmentFile=.*mealie)' "$p" 2>/dev/null; then
    echo "__CFG_FILE__:$p"
    sed -n '1,260p' "$p" 2>/dev/null || true
  fi
}
for p in \
  /opt/mealie/mealie.env \
  /opt/mealie/.env \
  /opt/mealie/docker/docker-compose.yml \
  /opt/mealie/docker/docker-compose.yaml \
  /etc/mealie/mealie.env \
  /etc/mealie/.env \
  /etc/systemd/system/mealie.service \
  /srv/mealie/mealie.env \
  /srv/mealie/.env \
  /var/lib/mealie/mealie.env \
  /var/lib/mealie/.env \
  "$HOME/docker/mealie/docker-compose.yml" \
  "$HOME/docker/mealie/docker-compose.yaml" \
  "$HOME/mealie/docker-compose.yml" \
  "$HOME/mealie/docker-compose.yaml"
do
  emit "$p"
done
for p in $(find /opt /etc /srv /var/lib /home -maxdepth 6 -type f \
  \( -name 'mealie.env' -o -name '.env' -o -name '*mealie*.env' -o -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'compose.yml' -o -name 'compose.yaml' -o -name 'mealie.service' \) \
  2>/dev/null | head -n 140); do
  emit "$p"
done
"""
    try:
        out, _err, _code = _ssh_exec(ssh_host, ssh_user, ssh_key, probe_cmd, timeout=20)
    except Exception:
        return False, "Could not read Mealie env files over SSH.", {}

    blocks = _parse_env_probe_blocks(out)
    if not blocks:
        return (
            False,
            "No Mealie config with DB credentials found over SSH. "
            "Checked documented paths such as /opt/mealie/mealie.env and docker-compose files under /opt/mealie and ~/docker/mealie.",
            {},
        )

    cache: dict[str, str] = {}

    def _read_remote(path: str, base_path: str) -> str:
        raw_path = str(path or "").strip()
        if not raw_path:
            return ""
        candidates: list[str] = []
        if raw_path.startswith("/"):
            candidates.append(raw_path)
        else:
            candidates.append(os.path.normpath(os.path.join(os.path.dirname(base_path), raw_path)))
            candidates.append(raw_path)

        # Mealie docs use /run/secrets/* inside container; resolve to common host-side files.
        if raw_path.startswith("/run/secrets/"):
            secret_name = os.path.basename(raw_path)
            base_dir = os.path.dirname(base_path)
            candidates.extend(
                [
                    os.path.join(base_dir, "secrets", secret_name),
                    os.path.join(base_dir, "secrets", f"{secret_name}.txt"),
                    os.path.join(base_dir, "secrets", "sensitive", secret_name),
                    os.path.join(base_dir, "secrets", "sensitive", f"{secret_name}.txt"),
                ]
            )

        for candidate in candidates:
            if candidate in cache:
                text = cache[candidate]
            else:
                q_path = shlex.quote(candidate)
                cmd = f"p={q_path}; if [ -r \"$p\" ]; then sed -n '1,4p' \"$p\"; fi"
                out_text, _err_text, code = _ssh_exec(ssh_host, ssh_user, ssh_key, cmd, timeout=12)
                text = out_text if code == 0 else ""
                cache[candidate] = text
            if text.strip():
                return text
        return ""

    best_detected: dict[str, str] = {}
    best_path = ""
    for path, payload in blocks:
        detected = _parse_mealie_env(payload)
        # Resolve *_FILE secret indirections, when present.
        for key in list(detected):
            if not key.startswith("__FILE__:"):
                continue
            target_key = key.split(":", 1)[1]
            secret_path = str(detected.get(key) or "").strip()
            secret_value = _read_remote(secret_path, path).splitlines()[0].strip() if secret_path else ""
            if secret_value:
                detected[target_key] = secret_value.strip("'\"")
            detected.pop(key, None)

        # systemd unit may point at a separate env file
        for line in payload.splitlines():
            if "EnvironmentFile" not in line:
                continue
            _, _, env_path = line.partition("=")
            env_path = env_path.strip().lstrip("-").strip("'\"")
            if not env_path:
                continue
            env_payload = _read_remote(env_path, path)
            if not env_payload:
                continue
            from_env_file = _parse_mealie_env(env_payload)
            for env_key, env_val in from_env_file.items():
                if env_key not in detected and env_val:
                    detected[env_key] = env_val

        if not detected:
            continue
        if len(detected) > len(best_detected):
            best_detected = detected
            best_path = path

    if best_detected:
        db_type = best_detected.get("MEALIE_DB_TYPE", "postgres")
        return True, f"Detected {db_type} credentials from config '{best_path}'.", best_detected

    return False, "Found candidate config file(s), but no recognized DB credential keys were parsed.", {}


def _detect_db_credentials(
    ssh_host: str, ssh_user: str, ssh_key: str,
) -> tuple[bool, str, dict[str, str]]:
    """SSH into the Mealie host and auto-discover database credentials."""

    docker_hint = ""

    # Strategy 1: find mealie container via docker ps
    try:
        out, _err, code = _ssh_exec(ssh_host, ssh_user, ssh_key, "docker ps --format '{{.Names}}'")
    except (FileNotFoundError, ValueError):
        return (
            False,
            "Auto-detect uses SSH only: key not found or path not allowed. "
            "Set MEALIE_DB_SSH_KEY to a valid key filename/path, or skip auto-detect and use Test DB with manual credentials.",
            {},
        )
    except Exception:
        return False, "SSH connection failed. Check SSH host, user, and key settings.", {}

    if code == 0:
        # Find container with "mealie" in the name
        containers = [name.strip() for name in out.splitlines() if name.strip()]
        mealie_containers = [c for c in containers if "mealie" in c.lower() and "cookdex" not in c.lower()]

        if mealie_containers:
            container = _validated_container_name(mealie_containers[0])

            # Strategy 2: docker inspect
            try:
                inspect_cmd = shlex.join([
                    "docker", "inspect", "--format",
                    "{{range .Config.Env}}{{println .}}{{end}}",
                    container,
                ])
                out, _err, inspect_code = _ssh_exec(
                    ssh_host, ssh_user, ssh_key, inspect_cmd,
                )
                if inspect_code == 0 and out.strip():
                    detected = _parse_mealie_env(out)
                    if detected:
                        db_type = detected.get("MEALIE_DB_TYPE", "postgres")
                        return True, f"Detected {db_type} credentials from container '{container}'.", detected
            except Exception:
                pass

            # Strategy 3: docker exec env
            try:
                exec_cmd = shlex.join(["docker", "exec", container, "env"])
                out, _err, exec_code = _ssh_exec(
                    ssh_host, ssh_user, ssh_key, exec_cmd,
                )
                if exec_code == 0 and out.strip():
                    detected = _parse_mealie_env(out)
                    if detected:
                        db_type = detected.get("MEALIE_DB_TYPE", "postgres")
                        return True, f"Detected {db_type} credentials from container '{container}'.", detected
            except Exception:
                pass

            docker_hint = f"Docker container '{container}' found, but credential extraction failed."
        else:
            docker_hint = "No Mealie Docker container found."
    else:
        docker_hint = "Docker discovery unavailable on remote host."

    # Strategy 4: non-Docker fallback (documented env-file discovery)
    ok, detail, detected = _detect_db_credentials_from_env_files(ssh_host, ssh_user, ssh_key)
    if ok:
        return True, detail, detected

    if docker_hint:
        return False, f"{docker_hint} {detail}", {}
    return False, detail, {}


@router.post("/settings/detect/db")
async def detect_db_settings(
    payload: DbDetectRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    runtime_env = build_runtime_env(services.state, services.cipher)
    ssh_host = resolve_runtime_value(runtime_env, "MEALIE_DB_SSH_HOST", payload.ssh_host)
    ssh_user = resolve_runtime_value(runtime_env, "MEALIE_DB_SSH_USER", payload.ssh_user) or "root"
    ssh_key = resolve_runtime_value(runtime_env, "MEALIE_DB_SSH_KEY", payload.ssh_key) or "~/.ssh/cookdex_mealie"

    if not ssh_host:
        return {"ok": False, "detail": "SSH host is required. Configure it in the fields above.", "detected": {}}

    try:
        ok, detail, detected = _detect_db_credentials(ssh_host, ssh_user, ssh_key)
        return {"ok": ok, "detail": detail, "detected": detected}
    except Exception:
        return {"ok": False, "detail": "Detection failed unexpectedly.", "detected": {}}


# ------------------------------------------------------------------
# Dredger Sites CRUD
# ------------------------------------------------------------------

def _get_dredger_store():
    from cookdex.recipe_dredger.storage import DredgerStore
    return DredgerStore()


@router.get("/settings/dredger-sites")
async def list_dredger_sites(
    _session: dict[str, Any] = Depends(require_session),
    _services: Services = Depends(require_services),
) -> dict[str, Any]:
    store = _get_dredger_store()
    sites = store.get_all_sites()
    # Auto-seed defaults on first access if table is empty
    if not sites:
        from cookdex.recipe_dredger.sites import DEFAULT_SITES
        store.seed_defaults(DEFAULT_SITES)
        sites = store.get_all_sites()
    return {"sites": sites}


@router.post("/settings/dredger-sites")
async def add_dredger_site(
    payload: DredgerSiteCreateRequest,
    _session: dict[str, Any] = Depends(require_session),
    _services: Services = Depends(require_services),
) -> dict[str, Any]:
    import sqlite3 as _sqlite3

    url = payload.url.strip().rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=422, detail="URL must start with http:// or https://")

    # Validate URL is reachable
    validation = _validate_dredger_site_url(url)

    store = _get_dredger_store()
    try:
        site_id = store.add_site(url, label=payload.label, region=payload.region)
    except _sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="This site URL already exists.")

    return {
        "id": site_id,
        "url": url,
        "validation": validation,
    }


@router.put("/settings/dredger-sites/{site_id}")
async def update_dredger_site(
    site_id: int,
    payload: DredgerSiteUpdateRequest,
    _session: dict[str, Any] = Depends(require_session),
    _services: Services = Depends(require_services),
) -> dict[str, Any]:
    if payload.url is not None:
        url = payload.url.strip().rstrip("/")
        if not url.startswith("http://") and not url.startswith("https://"):
            raise HTTPException(status_code=422, detail="URL must start with http:// or https://")
        payload.url = url

    store = _get_dredger_store()
    updated = store.update_site(
        site_id,
        url=payload.url,
        label=payload.label,
        region=payload.region,
        enabled=payload.enabled,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Site not found.")
    return {"ok": True}


@router.delete("/settings/dredger-sites/{site_id}")
async def delete_dredger_site(
    site_id: int,
    _session: dict[str, Any] = Depends(require_session),
    _services: Services = Depends(require_services),
) -> dict[str, Any]:
    store = _get_dredger_store()
    deleted = store.delete_site(site_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Site not found.")
    return {"ok": True}


@router.post("/settings/dredger-sites/seed")
async def seed_dredger_sites(
    payload: DredgerSitesSeedRequest,
    _session: dict[str, Any] = Depends(require_session),
    _services: Services = Depends(require_services),
) -> dict[str, Any]:
    from cookdex.recipe_dredger.sites import DEFAULT_SITES
    store = _get_dredger_store()
    inserted = store.seed_defaults(DEFAULT_SITES, force=payload.force)
    return {"ok": True, "inserted": inserted}


def _validate_dredger_site_url(url: str) -> dict[str, Any]:
    """Check if a site URL is reachable and has a crawlable sitemap."""
    result: dict[str, Any] = {"reachable": False, "sitemap_found": False, "error": ""}
    try:
        _validate_service_url(url)
    except ValueError as exc:
        result["error"] = str(exc)
        return result

    try:
        resp = requests.head(url, timeout=10, allow_redirects=True)
        result["reachable"] = resp.status_code < 400
        if not result["reachable"]:
            result["error"] = f"HTTP {resp.status_code}"
            return result
    except requests.RequestException as exc:
        result["error"] = _safe_request_error(exc)
        return result

    # Check for sitemap
    sitemap_candidates = [
        f"{url}/sitemap.xml",
        f"{url}/sitemap_index.xml",
        f"{url}/wp-sitemap.xml",
    ]
    for sitemap_url in sitemap_candidates:
        try:
            resp = requests.head(sitemap_url, timeout=5, allow_redirects=True)
            if resp.status_code == 200:
                result["sitemap_found"] = True
                break
        except requests.RequestException:
            continue

    return result


@router.post("/settings/dredger-sites/validate")
async def validate_dredger_sites(
    payload: DredgerSitesValidateRequest,
    _session: dict[str, Any] = Depends(require_session),
    _services: Services = Depends(require_services),
) -> dict[str, Any]:
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    store = _get_dredger_store()
    all_sites = store.get_all_sites()

    if payload.site_ids:
        target_ids = set(payload.site_ids)
        sites_to_check = [s for s in all_sites if s["id"] in target_ids]
    else:
        sites_to_check = all_sites

    def _check_one(site: dict[str, Any]) -> dict[str, Any]:
        validation = _validate_dredger_site_url(site["url"])
        return {"id": site["id"], "url": site["url"], **validation}

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [loop.run_in_executor(pool, _check_one, s) for s in sites_to_check]
        results = await asyncio.gather(*futures)

    return {"results": list(results)}
