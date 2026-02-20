from __future__ import annotations

from typing import Any

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
from ..schemas import ProviderConnectionTestRequest, SettingsUpdateRequest

router = APIRouter(tags=["settings"])


def _test_mealie_connection(url: str, api_key: str) -> tuple[bool, str]:
    base_url = url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    try:
        response = requests.get(f"{base_url}/users/self", headers=headers, timeout=12)
        response.raise_for_status()
        return True, "Mealie connection validated."
    except requests.RequestException as exc:
        return False, str(exc)


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
        return False, str(exc)


def _test_ollama_connection(url: str, model: str) -> tuple[bool, str]:
    base_url = url.strip().rstrip("/")
    if not base_url:
        return False, "Ollama URL is required."

    if base_url.endswith("/api"):
        tags_url = f"{base_url}/tags"
    elif base_url.endswith("/api/tags"):
        tags_url = base_url
    else:
        tags_url = f"{base_url}/api/tags"

    try:
        response = requests.get(tags_url, timeout=12)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models") if isinstance(payload, dict) else None
        if isinstance(models, list) and model:
            found = any(str(item.get("name") or "").startswith(model) for item in models if isinstance(item, dict))
            if not found:
                return True, f"Connection OK, model '{model}' was not listed by Ollama."
        return True, "Ollama connection validated."
    except requests.RequestException as exc:
        return False, str(exc)


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


@router.put("/settings")
async def put_settings(
    payload: SettingsUpdateRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
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
