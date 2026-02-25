from __future__ import annotations

from cookdex.webui_server.settings import _int_env


def test_int_env_clamps_below_minimum(monkeypatch):
    monkeypatch.setenv("WEB_BIND_PORT", "0")
    result = _int_env("WEB_BIND_PORT", 4820, min_val=1, max_val=65535)
    assert result == 1


def test_int_env_clamps_above_maximum(monkeypatch):
    monkeypatch.setenv("WEB_BIND_PORT", "99999")
    result = _int_env("WEB_BIND_PORT", 4820, min_val=1, max_val=65535)
    assert result == 65535


def test_int_env_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("WEB_BIND_PORT", raising=False)
    result = _int_env("WEB_BIND_PORT", 4820, min_val=1, max_val=65535)
    assert result == 4820


def test_int_env_accepts_valid_value(monkeypatch):
    monkeypatch.setenv("WEB_BIND_PORT", "8080")
    result = _int_env("WEB_BIND_PORT", 4820, min_val=1, max_val=65535)
    assert result == 8080
