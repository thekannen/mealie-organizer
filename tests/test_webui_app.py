from __future__ import annotations

import importlib
import json
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _seed_config_root(root: Path) -> None:
    _write_json(root / "configs" / "config.json", {"providers": {}, "parser": {}})
    _write_json(root / "configs" / "taxonomy" / "categories.json", [{"name": "Dinner"}])
    _write_json(root / "configs" / "taxonomy" / "tags.json", [{"name": "Italian"}])
    _write_json(root / "configs" / "taxonomy" / "cookbooks.json", [])
    _write_json(root / "configs" / "taxonomy" / "labels.json", [])
    _write_json(root / "configs" / "taxonomy" / "tools.json", [])
    _write_json(root / "configs" / "taxonomy" / "units_aliases.json", [])


def _login(client: TestClient) -> None:
    response = client.post(
        "/organizer/api/v1/auth/login",
        json={"username": "admin", "password": "secret-pass"},
    )
    assert response.status_code == 200


def test_webui_auth_runs_settings_and_config(tmp_path: Path, monkeypatch):
    config_root = tmp_path / "repo"
    _seed_config_root(config_root)

    monkeypatch.setenv("MO_WEBUI_MASTER_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("WEB_BOOTSTRAP_PASSWORD", "secret-pass")
    monkeypatch.setenv("WEB_BOOTSTRAP_USER", "admin")
    monkeypatch.setenv("WEB_STATE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WEB_BASE_PATH", "/organizer")
    monkeypatch.setenv("WEB_CONFIG_ROOT", str(config_root))
    monkeypatch.setenv("MEALIE_URL", "http://127.0.0.1:9000/api")
    monkeypatch.setenv("MEALIE_API_KEY", "placeholder")

    app_module = importlib.import_module("mealie_organizer.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    with TestClient(app) as client:
        health = client.get("/organizer/api/v1/health")
        assert health.status_code == 200

        _login(client)

        session = client.get("/organizer/api/v1/auth/session")
        assert session.status_code == 200
        assert session.json()["authenticated"] is True

        tasks = client.get("/organizer/api/v1/tasks")
        assert tasks.status_code == 200
        task_ids = [item["task_id"] for item in tasks.json()["items"]]
        assert "ingredient-parse" in task_ids

        blocked = client.post(
            "/organizer/api/v1/runs",
            json={"task_id": "ingredient-parse", "options": {"dry_run": False}},
        )
        assert blocked.status_code == 403

        policies = client.put(
            "/organizer/api/v1/policies",
            json={"policies": {"ingredient-parse": {"allow_dangerous": True}}},
        )
        assert policies.status_code == 200
        assert policies.json()["policies"]["ingredient-parse"]["allow_dangerous"] is True

        queued = client.post(
            "/organizer/api/v1/runs",
            json={"task_id": "ingredient-parse", "options": {"dry_run": False, "max_recipes": 1}},
        )
        assert queued.status_code == 202
        assert queued.json()["task_id"] == "ingredient-parse"

        schedule_create = client.post(
            "/organizer/api/v1/schedules",
            json={
                "name": "Parser Interval",
                "task_id": "ingredient-parse",
                "kind": "interval",
                "seconds": 600,
                "options": {"dry_run": True},
                "enabled": True,
            },
        )
        assert schedule_create.status_code == 201
        schedule_id = schedule_create.json()["schedule_id"]

        schedule_list = client.get("/organizer/api/v1/schedules")
        assert schedule_list.status_code == 200
        assert any(item["schedule_id"] == schedule_id for item in schedule_list.json()["items"])

        settings_put = client.put(
            "/organizer/api/v1/settings",
            json={"env": {"MEALIE_URL": "http://example/api", "MEALIE_API_KEY": "abc123"}},
        )
        assert settings_put.status_code == 200
        settings_get = client.get("/organizer/api/v1/settings")
        assert settings_get.status_code == 200
        payload = settings_get.json()
        assert payload["env"]["MEALIE_URL"]["value"] == "http://example/api"
        assert payload["env"]["MEALIE_URL"]["source"] == "ui_setting"
        assert payload["secrets"]["MEALIE_API_KEY"] == "********"
        assert payload["env"]["MEALIE_API_KEY"]["has_value"] is True

        unsupported_env = client.put(
            "/organizer/api/v1/settings",
            json={"env": {"NOT_ALLOWED_ENV": "x"}},
        )
        assert unsupported_env.status_code == 422

        config_list = client.get("/organizer/api/v1/config/files")
        assert config_list.status_code == 200
        assert any(item["name"] == "categories" for item in config_list.json()["items"])

        config_get = client.get("/organizer/api/v1/config/files/categories")
        assert config_get.status_code == 200
        assert config_get.json()["content"][0]["name"] == "Dinner"

        config_put = client.put(
            "/organizer/api/v1/config/files/categories",
            json={"content": [{"name": "Breakfast"}]},
        )
        assert config_put.status_code == 200
        config_get_updated = client.get("/organizer/api/v1/config/files/categories")
        assert config_get_updated.json()["content"][0]["name"] == "Breakfast"
