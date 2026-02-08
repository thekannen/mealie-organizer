import pytest

from mealie_organizer.config import env_or_config, to_bool


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
