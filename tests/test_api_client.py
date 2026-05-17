from __future__ import annotations

import requests
import pytest

from cookdex.api_client import MealieApiClient


def _http_404_error(message: str) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = 404
    return requests.HTTPError(message, response=response)


def _http_422_error(message: str) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = 422
    return requests.HTTPError(message, response=response)


def test_create_food_uses_current_schema_before_legacy_group_id(monkeypatch):
    client = MealieApiClient(base_url="http://mealie.local/api", api_key="token")
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(method: str, path_or_url: str, **kwargs):
        calls.append((method, path_or_url, kwargs.get("json")))
        if method == "POST" and path_or_url == "/foods":
            return {"id": "food-1", "name": kwargs["json"]["name"]}
        raise AssertionError(f"Unexpected request: {method} {path_or_url}")

    monkeypatch.setattr(client, "request_json", fake_request_json)

    created = client.create_food("Apple", group_id="legacy-group")
    assert created == {"id": "food-1", "name": "Apple"}
    assert calls == [("POST", "/foods", {"name": "Apple"})]


def test_create_food_falls_back_to_legacy_group_id_on_validation_error(monkeypatch):
    client = MealieApiClient(base_url="http://mealie.local/api", api_key="token")
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(method: str, path_or_url: str, **kwargs):
        calls.append((method, path_or_url, kwargs.get("json")))
        if method == "POST" and path_or_url == "/foods":
            payload = kwargs["json"]
            if payload == {"name": "Apple"}:
                raise _http_422_error("groupId required")
            if payload == {"name": "Apple", "groupId": "legacy-group"}:
                return {"id": "food-1", "name": "Apple", "groupId": "legacy-group"}
        raise AssertionError(f"Unexpected request: {method} {path_or_url}")

    monkeypatch.setattr(client, "request_json", fake_request_json)

    created = client.create_food("Apple", group_id="legacy-group")
    assert created == {"id": "food-1", "name": "Apple", "groupId": "legacy-group"}
    assert calls == [
        ("POST", "/foods", {"name": "Apple"}),
        ("POST", "/foods", {"name": "Apple", "groupId": "legacy-group"}),
    ]


def test_merge_food_uses_current_payload_without_legacy_probes(monkeypatch):
    client = MealieApiClient(base_url="http://mealie.local/api", api_key="token")
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(method: str, path_or_url: str, **kwargs):
        calls.append((method, path_or_url, kwargs.get("json")))
        return {"message": "merged", "error": False}

    monkeypatch.setattr(client, "request_json", fake_request_json)

    result = client.merge_food("source-food", "target-food")
    assert result == {"message": "merged", "error": False}
    assert calls == [
        ("PUT", "/foods/merge", {"fromFood": "source-food", "toFood": "target-food"})
    ]


def test_merge_unit_uses_current_payload_without_legacy_probes(monkeypatch):
    client = MealieApiClient(base_url="http://mealie.local/api", api_key="token")
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(method: str, path_or_url: str, **kwargs):
        calls.append((method, path_or_url, kwargs.get("json")))
        return {"message": "merged", "error": False}

    monkeypatch.setattr(client, "request_json", fake_request_json)

    result = client.merge_unit("source-unit", "target-unit")
    assert result == {"message": "merged", "error": False}
    assert calls == [
        ("PUT", "/units/merge", {"fromUnit": "source-unit", "toUnit": "target-unit"})
    ]


def test_list_tools_falls_back_to_organizers_route(monkeypatch):
    client = MealieApiClient(base_url="http://mealie.local/api", api_key="token")
    calls: list[str] = []

    def fake_get_paginated(path_or_url: str, *, per_page: int = 1000, timeout: int | None = None):
        calls.append(path_or_url)
        if path_or_url == "/organizers/tools":
            raise _http_404_error("missing /organizers/tools")
        if path_or_url == "/tools":
            return [{"id": "tool-1", "name": "Blender"}]
        raise AssertionError(f"Unexpected path: {path_or_url}")

    monkeypatch.setattr(client, "get_paginated", fake_get_paginated)
    result = client.list_tools()
    assert result == [{"id": "tool-1", "name": "Blender"}]
    assert calls == ["/organizers/tools", "/tools"]


def test_create_tool_falls_back_to_organizers_route(monkeypatch):
    client = MealieApiClient(base_url="http://mealie.local/api", api_key="token")
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(method: str, path_or_url: str, **kwargs):
        calls.append((method, path_or_url, kwargs.get("json")))
        if method == "POST" and path_or_url == "/organizers/tools":
            raise _http_404_error("missing /organizers/tools")
        if method == "POST" and path_or_url == "/tools":
            return {"id": "tool-2", "name": kwargs["json"]["name"]}
        raise AssertionError(f"Unexpected request: {method} {path_or_url}")

    monkeypatch.setattr(client, "request_json", fake_request_json)

    created = client.create_tool("Dutch Oven")
    assert created == {"id": "tool-2", "name": "Dutch Oven"}
    assert calls == [
        ("POST", "/organizers/tools", {"name": "Dutch Oven", "householdsWithTool": []}),
        ("POST", "/tools", {"name": "Dutch Oven"}),
    ]


def test_merge_tool_raises_actionable_error_when_merge_route_missing(monkeypatch):
    client = MealieApiClient(base_url="http://mealie.local/api", api_key="token")
    calls: list[str] = []

    def fake_merge_entity(route, source_id, target_id):
        calls.append(route)
        raise _http_404_error(f"missing {route}")

    monkeypatch.setattr(client, "_merge_entity", fake_merge_entity)
    with pytest.raises(requests.HTTPError, match="Tool merge endpoint is unavailable"):
        client.merge_tool("source", "target")
    assert calls == ["/organizers/tools/merge", "/tools/merge"]
