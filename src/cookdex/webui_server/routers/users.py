from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..deps import Services, normalize_username, require_services, require_session
from ..schemas import UserCreateRequest, UserPasswordResetRequest
from ..security import hash_password

router = APIRouter(tags=["users"])


@router.get("/users")
async def list_users(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    return {"items": services.state.list_users()}


@router.post("/users", status_code=201)
async def create_user(
    payload: UserCreateRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    username = normalize_username(payload.username)
    created = services.state.create_user(username, hash_password(payload.password))
    if not created:
        raise HTTPException(status_code=409, detail="Username already exists.")
    return {"ok": True, "username": username}


@router.post("/users/{username}/reset-password")
async def reset_user_password(
    username: str,
    payload: UserPasswordResetRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    normalized = normalize_username(username)
    updated = services.state.update_password(normalized, hash_password(payload.password))
    if not updated:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"ok": True}


@router.delete("/users/{username}")
async def delete_user(
    username: str,
    session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    normalized = normalize_username(username)
    current_username = str(session["username"])
    if normalized == current_username:
        raise HTTPException(status_code=409, detail="You cannot delete the active account.")
    if services.state.count_users() <= 1:
        raise HTTPException(status_code=409, detail="At least one account must remain.")
    deleted = services.state.delete_user(normalized)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"ok": True}
