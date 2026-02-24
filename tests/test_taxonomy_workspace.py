from __future__ import annotations

import importlib
import json
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from cookdex.webui_server.config_files import ConfigFilesManager
from cookdex.webui_server.taxonomy_workspace import TaxonomyWorkspaceService


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _seed_config_root(root: Path) -> None:
    _write_json(root / "configs" / "config.json", {"providers": {}, "parser": {}})
    _write_json(root / "configs" / "taxonomy" / "categories.json", [{"name": "Existing Category"}])
    _write_json(root / "configs" / "taxonomy" / "tags.json", [{"name": "Existing Tag"}])
    _write_json(root / "configs" / "taxonomy" / "cookbooks.json", [{"name": "Existing", "description": "", "queryFilterString": "", "public": False, "position": 1}])
    _write_json(root / "configs" / "taxonomy" / "labels.json", [{"name": "Existing Label", "color": "#111111"}])
    _write_json(root / "configs" / "taxonomy" / "tools.json", [{"name": "Existing Tool", "onHand": False}])
    _write_json(
        root / "configs" / "taxonomy" / "units_aliases.json",
        [{"name": "Cup", "abbreviation": "c", "aliases": ["cups"], "fraction": True, "useAbbreviation": True}],
    )
    _write_json(
        root / "configs" / "taxonomy" / "tag_rules.json",
        {
            "ingredient_tags": [
                {"tag": "Existing Tag", "pattern": "existing"},
                {"tag": "Ghost Tag", "pattern": "ghost"},
            ],
            "text_tags": [],
            "text_categories": [
                {"category": "Existing Category", "pattern": "existing"},
                {"category": "Ghost Category", "pattern": "ghost"},
            ],
            "ingredient_categories": [],
            "tool_tags": [
                {"tool": "Existing Tool", "pattern": "existing"},
                {"tool": "Ghost Tool", "pattern": "ghost"},
            ],
        },
    )


def _login(client: TestClient) -> None:
    response = client.post(
        "/cookdex/api/v1/auth/login",
        json={"username": "admin", "password": "Secret-pass1"},
    )
    assert response.status_code == 200


class _FakeMealieClient:
    def get_organizer_items(self, endpoint: str, *, per_page: int = 1000):
        if endpoint == "categories":
            return [{"name": "Dinner"}, {"name": "Lunch"}]
        if endpoint == "tags":
            return [{"name": "Quick"}, {"name": "Italian"}]
        return []

    def list_labels(self, *, per_page: int = 1000):
        return [{"name": "Meal Prep", "color": "#f39c12"}]

    def list_tools(self, *, per_page: int = 1000):
        return [{"name": "Air Fryer", "onHand": True}]

    def list_units(self, *, per_page: int = 1000):
        return [
            {"name": "Teaspoon", "abbreviation": "tsp", "pluralName": "Teaspoons", "pluralAbbreviation": "tsps"},
        ]

    def request_json(self, method: str, path: str, *, timeout: int | None = None):
        if method == "GET" and path == "/households/cookbooks":
            return [{"name": "Weeknight", "description": "Fast dinners", "queryFilterString": "", "public": False, "position": 1}]
        return []


def test_taxonomy_workspace_initialize_from_mealie_replace(tmp_path: Path) -> None:
    config_root = tmp_path / "repo"
    _seed_config_root(config_root)
    manager = ConfigFilesManager(config_root)
    workspace = TaxonomyWorkspaceService(repo_root=config_root, config_files=manager)

    payload = workspace.initialize_from_mealie(
        mealie_url="http://example/api",
        mealie_api_key="token",
        mode="replace",
        client=_FakeMealieClient(),
    )

    assert payload["mode"] == "replace"
    assert payload["rule_sync"]["updated"] is True
    assert payload["rule_sync"]["removed_total"] >= 1
    categories = manager.read_file("categories")["content"]
    assert categories == [{"name": "Dinner"}, {"name": "Lunch"}]
    tools = manager.read_file("tools")["content"]
    assert tools == [{"name": "Air Fryer", "onHand": True}]
    synced_rules = json.loads((config_root / "configs" / "taxonomy" / "tag_rules.json").read_text(encoding="utf-8"))
    rule_targets = [rule.get("tag") for rule in synced_rules.get("ingredient_tags", [])]
    assert "Ghost Tag" not in rule_targets
    assert "Existing Tag" not in rule_targets


def test_taxonomy_workspace_import_starter_pack_merge(tmp_path: Path) -> None:
    config_root = tmp_path / "repo"
    _seed_config_root(config_root)
    manager = ConfigFilesManager(config_root)
    workspace = TaxonomyWorkspaceService(repo_root=config_root, config_files=manager)

    def fake_fetcher(url: str):
        if url.endswith("/categories.json"):
            return [{"name": "Existing Category"}, {"name": "Starter Category"}]
        if url.endswith("/tools.json"):
            return [{"name": "Existing Tool", "onHand": True}, {"name": "Cast Iron Pan", "onHand": False}]
        if url.endswith("/units_aliases.json"):
            return [{"name": "Cup", "aliases": ["cup."]}, {"name": "Tablespoon", "abbreviation": "tbsp"}]
        if url.endswith("/tags.json"):
            return [{"name": "Starter Tag"}]
        if url.endswith("/labels.json"):
            return [{"name": "Starter Label", "color": "#ff9900"}]
        if url.endswith("/cookbooks.json"):
            return [{"name": "Starter Cookbook", "description": "", "queryFilterString": "", "public": False, "position": 2}]
        return []

    payload = workspace.import_starter_pack(mode="merge", base_url="https://example.test/pack", fetcher=fake_fetcher)
    assert payload["mode"] == "merge"
    assert payload["rule_sync"]["updated"] is True
    assert payload["rule_sync"]["removed_total"] >= 1

    categories = manager.read_file("categories")["content"]
    assert {"name": "Existing Category"} in categories
    assert {"name": "Starter Category"} in categories

    tools = manager.read_file("tools")["content"]
    assert {"name": "Existing Tool", "onHand": True} in tools
    assert {"name": "Cast Iron Pan", "onHand": False} in tools

    units = manager.read_file("units_aliases")["content"]
    cup = next(item for item in units if item.get("name") == "Cup")
    assert "cups" in cup.get("aliases", [])
    assert "cup." in cup.get("aliases", [])

    synced_rules = json.loads((config_root / "configs" / "taxonomy" / "tag_rules.json").read_text(encoding="utf-8"))
    assert all(rule.get("tag") != "Ghost Tag" for rule in synced_rules.get("ingredient_tags", []))
    assert any(rule.get("tag") == "Existing Tag" for rule in synced_rules.get("ingredient_tags", []))


def test_taxonomy_workspace_endpoints(tmp_path: Path, monkeypatch) -> None:
    config_root = tmp_path / "repo"
    _seed_config_root(config_root)

    monkeypatch.setenv("MO_WEBUI_MASTER_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("WEB_BOOTSTRAP_PASSWORD", "Secret-pass1")
    monkeypatch.setenv("WEB_BOOTSTRAP_USER", "admin")
    monkeypatch.setenv("WEB_STATE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WEB_BASE_PATH", "/cookdex")
    monkeypatch.setenv("WEB_CONFIG_ROOT", str(config_root))
    monkeypatch.setenv("WEB_COOKIE_SECURE", "false")
    monkeypatch.setenv("MEALIE_URL", "http://127.0.0.1:9000/api")
    monkeypatch.setenv("MEALIE_API_KEY", "placeholder")

    workspace_module = importlib.import_module("cookdex.webui_server.taxonomy_workspace")
    monkeypatch.setattr(workspace_module, "MealieApiClient", lambda base_url, api_key: _FakeMealieClient())
    monkeypatch.setattr(
        workspace_module.TaxonomyWorkspaceService,
        "_fetch_json_url",
        staticmethod(lambda url: [{"name": f"starter-{Path(url).name.replace('.json', '')}"}]),
    )

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    with TestClient(app) as client:
        _login(client)

        from_mealie = client.post(
            "/cookdex/api/v1/config/taxonomy/initialize-from-mealie",
            json={"mode": "replace"},
        )
        assert from_mealie.status_code == 200, from_mealie.text
        assert from_mealie.json()["source"] == "mealie"
        assert "rule_sync" in from_mealie.json()
        categories = client.get("/cookdex/api/v1/config/files/categories").json()["content"]
        assert {"name": "Dinner"} in categories

        starter = client.post(
            "/cookdex/api/v1/config/taxonomy/import-starter-pack",
            json={"mode": "merge", "base_url": "https://example.invalid/pack"},
        )
        assert starter.status_code == 200, starter.text
        assert starter.json()["source"] == "starter-pack"
        assert "rule_sync" in starter.json()
