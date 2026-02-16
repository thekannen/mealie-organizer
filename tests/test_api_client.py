import requests
import pytest

from mealie_organizer.api_client import MealieApiClient


def _http_404_error(message: str) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = 404
    return requests.HTTPError(message, response=response)


def test_list_tools_falls_back_to_organizers_route(monkeypatch):
    client = MealieApiClient(base_url="http://mealie.local/api", api_key="token")
    calls: list[str] = []

    def fake_get_paginated(path_or_url: str, *, per_page: int = 1000, timeout: int | None = None):
        calls.append(path_or_url)
        if path_or_url == "/tools":
            raise _http_404_error("missing /tools")
        if path_or_url == "/organizers/tools":
            return [{"id": "tool-1", "name": "Blender"}]
        raise AssertionError(f"Unexpected path: {path_or_url}")

    monkeypatch.setattr(client, "get_paginated", fake_get_paginated)
    result = client.list_tools()
    assert result == [{"id": "tool-1", "name": "Blender"}]
    assert calls == ["/tools", "/organizers/tools"]


def test_create_tool_falls_back_to_organizers_route(monkeypatch):
    client = MealieApiClient(base_url="http://mealie.local/api", api_key="token")

    def fake_request_json(method: str, path_or_url: str, **kwargs):
        if method == "POST" and path_or_url == "/tools":
            raise _http_404_error("missing /tools")
        raise AssertionError(f"Unexpected request: {method} {path_or_url}")

    monkeypatch.setattr(client, "request_json", fake_request_json)
    monkeypatch.setattr(client, "create_organizer_item", lambda endpoint, payload: {"id": "tool-2", "name": payload["name"]})

    created = client.create_tool("Dutch Oven")
    assert created == {"id": "tool-2", "name": "Dutch Oven"}


def test_merge_tool_raises_actionable_error_when_merge_route_missing(monkeypatch):
    client = MealieApiClient(base_url="http://mealie.local/api", api_key="token")
    monkeypatch.setattr(
        client,
        "_merge_entity",
        lambda route, source_id, target_id: (_ for _ in ()).throw(_http_404_error("missing /tools/merge")),
    )
    with pytest.raises(requests.HTTPError, match="Tool merge endpoint is unavailable"):
        client.merge_tool("source", "target")
