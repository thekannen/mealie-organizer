from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

_PASSWORD_MIN_LENGTH = 8
_PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$"
)
_PASSWORD_HELP = (
    "Password must be at least 8 characters with at least one uppercase letter, "
    "one lowercase letter, and one digit."
)


def _validate_password_strength(value: str) -> str:
    if not _PASSWORD_PATTERN.match(value):
        raise ValueError(_PASSWORD_HELP)
    return value


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=_PASSWORD_MIN_LENGTH)

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=_PASSWORD_MIN_LENGTH)
    force_reset: bool = False

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class UserPasswordResetRequest(BaseModel):
    password: str = Field(min_length=_PASSWORD_MIN_LENGTH)
    force_reset: bool = False

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


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
    kind: str = Field(pattern="^(interval|once)$")
    options: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    run_if_missed: bool = False
    seconds: int | None = None
    run_at: str | None = None
    start_at: str | None = None
    end_at: str | None = None


class ScheduleUpdateRequest(BaseModel):
    name: str | None = None
    task_id: str | None = None
    kind: str | None = Field(default=None, pattern="^(interval|once)$")
    options: dict[str, Any] | None = None
    enabled: bool | None = None
    run_if_missed: bool | None = None
    seconds: int | None = None
    run_at: str | None = None
    start_at: str | None = None
    end_at: str | None = None


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str | None] = Field(default_factory=dict)
    env: dict[str, str | None] = Field(default_factory=dict)


class ProviderConnectionTestRequest(BaseModel):
    openai_api_key: str | None = None
    openai_model: str | None = None
    ollama_url: str | None = None
    ollama_model: str | None = None
    mealie_url: str | None = None
    mealie_api_key: str | None = None


class DbDetectRequest(BaseModel):
    ssh_host: str | None = None
    ssh_user: str | None = None
    ssh_key: str | None = None


class ConfigWriteRequest(BaseModel):
    content: Any
