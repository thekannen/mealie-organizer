from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

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
    return {"ok": True}


@router.patch("/users/{username}/role")
async def update_user_role(
    username: str,
    payload: UserRoleUpdateRequest,
    _session: dict[str, Any] = Depends(require_owner_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    normalized = normalize_username(username)
    existing = services.state.get_user(normalized)
    if existing is None:
        raise HTTPException(status_code=404, detail="User not found.")
    current_role = str(existing.get("role") or "")
    if current_role == ROLE_OWNER and payload.role != ROLE_OWNER and services.state.count_users_by_role(ROLE_OWNER) <= 1:
        raise HTTPException(status_code=409, detail="At least one owner account must remain.")
    services.state.update_user_role(normalized, payload.role)
    updated = services.state.get_user(normalized)
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
    existing = services.state.get_user(normalized)
    if existing is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if str(existing.get("role") or "") == ROLE_OWNER and services.state.count_users_by_role(ROLE_OWNER) <= 1:
        raise HTTPException(status_code=409, detail="At least one owner account must remain.")
    if services.state.count_users() <= 1:
        raise HTTPException(status_code=409, detail="At least one account must remain.")
    deleted = services.state.delete_user(normalized)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"ok": True}
