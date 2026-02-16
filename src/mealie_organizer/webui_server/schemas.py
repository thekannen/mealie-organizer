from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RunCreateRequest(BaseModel):
    task_id: str = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


class PolicyUpdateItem(BaseModel):
    allow_dangerous: bool = False


class PoliciesUpdateRequest(BaseModel):
    policies: dict[str, PolicyUpdateItem] = Field(default_factory=dict)


class ScheduleCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    kind: str = Field(pattern="^(interval|cron)$")
    options: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    seconds: int | None = None
    cron: str | None = None


class ScheduleUpdateRequest(BaseModel):
    name: str | None = None
    task_id: str | None = None
    kind: str | None = Field(default=None, pattern="^(interval|cron)$")
    options: dict[str, Any] | None = None
    enabled: bool | None = None
    seconds: int | None = None
    cron: str | None = None


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str | None] = Field(default_factory=dict)


class ConfigWriteRequest(BaseModel):
    content: Any
