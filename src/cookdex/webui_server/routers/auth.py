from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..deps import Services, normalize_username, require_services, require_session
from ..rate_limit import LoginRateLimiter
from ..schemas import LoginRequest, RegisterRequest
from ..security import hash_password, new_session_token, verify_password

router = APIRouter(tags=["auth"])
_limiter = LoginRateLimiter(max_attempts=5, window_seconds=300)


def _set_session_cookie(response: Response, services: Services, token: str) -> None:
    response.set_cookie(
        key=services.settings.cookie_name,
        value=token,
        httponly=True,
        secure=services.settings.cookie_secure,
        samesite="lax",
        path=services.settings.base_path,
    )


def _create_session(services: Services, username: str) -> tuple[str, str]:
    token = new_session_token()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=services.settings.session_ttl_seconds)
    ).isoformat().replace("+00:00", "Z")
    services.state.create_session(token=token, username=username, expires_at=expires_at)
    return token, expires_at


@router.get("/auth/bootstrap-status")
async def bootstrap_status(services: Services = Depends(require_services)) -> dict[str, Any]:
    return {"setup_required": not services.state.has_users()}


@router.post("/auth/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    if not services.state.has_users():
        raise HTTPException(status_code=409, detail="No users found. Complete first-time setup.")

    client_ip = request.client.host if request.client else "unknown"
    _limiter.check(client_ip)

    username = normalize_username(payload.username)
    password_hash = services.state.get_password_hash(username)
    if password_hash is None or not verify_password(payload.password, password_hash):
        _limiter.record_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    _limiter.clear(client_ip)
    token, expires_at = _create_session(services, username)
    _set_session_cookie(response, services, token)
    return {"ok": True, "username": username, "expires_at": expires_at}


@router.post("/auth/register")
async def register_first_user(
    payload: RegisterRequest,
    response: Response,
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    if services.state.has_users():
        raise HTTPException(status_code=409, detail="Setup already completed.")
    username = normalize_username(payload.username)
    created = services.state.create_user(username, hash_password(payload.password))
    if not created:
        raise HTTPException(status_code=409, detail="Username already exists.")

    token, expires_at = _create_session(services, username)
    _set_session_cookie(response, services, token)
    return {"ok": True, "username": username, "expires_at": expires_at}


@router.post("/auth/logout")
async def logout(
    request: Request,
    response: Response,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, bool]:
    token = request.cookies.get(services.settings.cookie_name, "").strip()
    if token:
        services.state.delete_session(token)
    response.delete_cookie(key=services.settings.cookie_name, path=services.settings.base_path)
    return {"ok": True}


@router.get("/auth/session")
async def session_status(session: dict[str, Any] = Depends(require_session)) -> dict[str, Any]:
    return {"authenticated": True, "username": session["username"], "expires_at": session["expires_at"]}
