from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import (
    ROLE_OWNER,
    Services,
    normalize_username,
    require_owner_session,
    require_services,
    require_session,
)
from ..rate_limit import ActionRateLimiter
from ..schemas import UserCreateRequest, UserPasswordResetRequest, UserRoleUpdateRequest
from ..security import hash_password

router = APIRouter(tags=["users"])
_action_limiter = ActionRateLimiter(max_per_minute=20)


@router.get("/users")
async def list_users(
    _session: dict[str, Any] = Depends(require_owner_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    return {"items": services.state.list_users()}


@router.post("/users", status_code=201)
async def create_user(
    payload: UserCreateRequest,
    session: dict[str, Any] = Depends(require_owner_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    _action_limiter.check(session["username"])
    username = normalize_username(payload.username)
    created = services.state.create_user(
        username,
        hash_password(payload.password),
        force_reset=payload.force_reset,
        role=payload.role,
    )
    if not created:
        raise HTTPException(status_code=409, detail="Username already exists.")
    return {"ok": True, "username": username, "role": payload.role}


@router.post("/users/{username}/reset-password")
async def reset_user_password(
    username: str,
    payload: UserPasswordResetRequest,
    request: Request,
    session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    _action_limiter.check(session["username"])
    normalized = normalize_username(username)
    if normalized != str(session["username"]) and str(session.get("role")) != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Insufficient permissions.")
    updated = services.state.update_password(normalized, hash_password(payload.password))
    if not updated:
        raise HTTPException(status_code=404, detail="User not found.")
    if payload.force_reset:
        services.state.set_force_password_reset(normalized, True)
    current_token = ""
    if normalized == str(session["username"]):
        current_token = request.cookies.get(services.settings.cookie_name, "").strip()
    services.state.delete_sessions_for_user(normalized, except_token=current_token or None)
    return {"ok": True}


@router.patch("/users/{username}/role")
async def update_user_role(
    username: str,
    payload: UserRoleUpdateRequest,
    _session: dict[str, Any] = Depends(require_owner_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    normalized = normalize_username(username)
    try:
        updated = services.state.update_user_role_guarded(normalized, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"ok": True, "user": updated}


@router.delete("/users/{username}")
async def delete_user(
    username: str,
    session: dict[str, Any] = Depends(require_owner_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    normalized = normalize_username(username)
    current_username = str(session["username"])
    if normalized == current_username:
        raise HTTPException(status_code=409, detail="You cannot delete the active account.")
    try:
        deleted = services.state.delete_user_guarded(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if deleted is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"ok": True}
