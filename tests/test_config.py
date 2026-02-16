import importlib

import pytest

import mealie_organizer.config as config_module
from mealie_organizer.config import (
    env_or_config,
    require_mealie_url,
    resolve_mealie_api_key,
    resolve_mealie_url,
    to_bool,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        ("FALSE", False),
        ("yes", True),
        ("off", False),
    ],
)
def test_to_bool_valid_values(value, expected):
    assert to_bool(value) is expected


def test_to_bool_invalid_value():
    with pytest.raises(ValueError):
        to_bool("maybe")


def test_env_or_config_prefers_env(monkeypatch):
    monkeypatch.setenv("UNIT_TEST_INT", "7")
    assert env_or_config("UNIT_TEST_INT", "no.such.path", 3, int) == 7


def test_env_or_config_empty_env_falls_back(monkeypatch):
    monkeypatch.setenv("UNIT_TEST_EMPTY", "")
    assert env_or_config("UNIT_TEST_EMPTY", "no.such.path", 5, int) == 5


def test_env_or_config_bool_from_env(monkeypatch):
    monkeypatch.setenv("UNIT_TEST_BOOL", "true")
    assert env_or_config("UNIT_TEST_BOOL", "no.such.path", False, to_bool) is True


def test_require_mealie_url_normalizes_trailing_slash():
    assert require_mealie_url("http://localhost:9000/api/") == "http://localhost:9000/api"


def test_require_mealie_url_rejects_placeholder():
    with pytest.raises(RuntimeError):
        require_mealie_url("http://your.server.ip.address:9000/api")


def test_require_mealie_url_rejects_non_string():
    with pytest.raises(RuntimeError):
        require_mealie_url({"url": "http://localhost:9000/api"})


def test_resolve_mealie_url_prefers_primary(monkeypatch):
    monkeypatch.setenv("MEALIE_URL", "http://primary.local:9000/api")
    monkeypatch.setenv("MEALIE_BASE_URL", "http://legacy.local:9000/api")
    assert resolve_mealie_url() == "http://primary.local:9000/api"


def test_resolve_mealie_url_uses_legacy_alias(monkeypatch):
    monkeypatch.delenv("MEALIE_URL", raising=False)
    monkeypatch.setenv("MEALIE_BASE_URL", "http://legacy.local:9000/api")
    assert resolve_mealie_url() == "http://legacy.local:9000/api"


def test_resolve_mealie_api_key_prefers_primary(monkeypatch):
    monkeypatch.setenv("MEALIE_API_KEY", "primary-token")
    monkeypatch.setenv("MEALIE_API_TOKEN", "legacy-token")
    assert resolve_mealie_api_key(required=True) == "primary-token"


def test_resolve_mealie_api_key_uses_legacy_alias(monkeypatch):
    monkeypatch.delenv("MEALIE_API_KEY", raising=False)
    monkeypatch.setenv("MEALIE_API_TOKEN", "legacy-token")
    assert resolve_mealie_api_key(required=True) == "legacy-token"


def test_repo_root_uses_env_override(monkeypatch, tmp_path):
    custom_root = tmp_path / "custom-root"
    (custom_root / "configs" / "taxonomy").mkdir(parents=True)
    (custom_root / "configs" / "config.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("MEALIE_ORGANIZER_ROOT", str(custom_root))
    reloaded = importlib.reload(config_module)
    try:
        assert reloaded.REPO_ROOT == custom_root.resolve()
        assert reloaded.resolve_repo_path("configs/taxonomy") == custom_root.resolve() / "configs" / "taxonomy"
    finally:
        monkeypatch.delenv("MEALIE_ORGANIZER_ROOT", raising=False)
        importlib.reload(config_module)
