import pytest

from mealie_organizer.plugin_server import (
    ensure_api_base_url,
    token_from_auth_header,
    token_from_cookie_header,
)


def test_ensure_api_base_url_keeps_existing_api_path():
    assert ensure_api_base_url("http://localhost:9000/api") == "http://localhost:9000/api"


def test_ensure_api_base_url_adds_api_suffix_when_missing():
    assert ensure_api_base_url("http://localhost:9000") == "http://localhost:9000/api"
    assert ensure_api_base_url("https://example.com/mealie") == "https://example.com/mealie/api"


def test_ensure_api_base_url_rejects_invalid_url():
    with pytest.raises(ValueError):
        ensure_api_base_url("localhost-no-scheme")


def test_token_from_auth_header():
    assert token_from_auth_header("Bearer abc") == "abc"
    assert token_from_auth_header("bearer xyz") == "xyz"
    assert token_from_auth_header("Token nope") == ""
    assert token_from_auth_header("") == ""


def test_token_from_cookie_header_prefers_first_configured_name():
    cookie_header = "mealie.access_token=abc123; session=s1; access_token=xyz"
    token = token_from_cookie_header(cookie_header, ("mealie.access_token", "access_token"))
    assert token == "abc123"


def test_token_from_cookie_header_fallback_cookie_name():
    cookie_header = "session=s1; access_token=xyz"
    token = token_from_cookie_header(cookie_header, ("mealie.access_token", "access_token"))
    assert token == "xyz"

