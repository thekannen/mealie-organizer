from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _seed_config_root(root: Path) -> None:
    _taxonomy = {
        "categories": [{"name": "Dinner"}],
        "tags": [{"name": "Italian"}],
        "cookbooks": [],
        "labels": [],
        "tools": [],
        "units_aliases": [],
    }
    for name, data in _taxonomy.items():
        # Write to both configs/taxonomy/ (legacy) and taxonomy/ (for create_app() seeding).
        _write_json(root / "configs" / "taxonomy" / f"{name}.json", data)
        _write_json(root / "taxonomy" / f"{name}.json", data)


_CSRF = {"X-Requested-With": "XMLHttpRequest"}


def _login(client: TestClient) -> None:
    _login_as(client, "admin", "Secret-pass1")


def _login_as(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/cookdex/api/v1/auth/login",
        json={"username": username, "password": password},
        headers=_CSRF,
    )
    assert response.status_code == 200


def test_webui_auth_runs_settings_and_config(tmp_path: Path, monkeypatch):
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
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-openai-key")

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    with TestClient(app) as client:
        health = client.get("/cookdex/api/v1/health")
        assert health.status_code == 200

        bootstrap_status = client.get("/cookdex/api/v1/auth/bootstrap-status")
        assert bootstrap_status.status_code == 200
        assert bootstrap_status.json()["setup_required"] is False

        organizer_page = client.get("/cookdex")
        assert organizer_page.status_code == 200
        # Base path injected as <base> tag (dev/static template) or __BASE_PATH__ replacement (built dist)
        html = organizer_page.text
        assert '<base href="/cookdex/" />' in html or '"/cookdex"' in html

        _login(client)

        session = client.get("/cookdex/api/v1/auth/session")
        assert session.status_code == 200
        assert session.json()["authenticated"] is True
        assert session.json()["role"] == "owner"

        users_initial = client.get("/cookdex/api/v1/users")
        assert users_initial.status_code == 200
        assert any(item["username"] == "admin" for item in users_initial.json()["items"])

        create_user = client.post(
            "/cookdex/api/v1/users",
            json={"username": "kitchen-tablet", "password": "Tablet-pass01"},
            headers=_CSRF,
        )
        assert create_user.status_code == 201
        assert create_user.json()["username"] == "kitchen-tablet"
        assert create_user.json()["role"] == "editor"

        users_after_create = client.get("/cookdex/api/v1/users")
        assert users_after_create.status_code == 200
        assert any(item["username"] == "kitchen-tablet" for item in users_after_create.json()["items"])
        assert any(
            item["username"] == "kitchen-tablet" and item["role"] == "editor"
            for item in users_after_create.json()["items"]
        )

        reset_password = client.post(
            "/cookdex/api/v1/users/kitchen-tablet/reset-password",
            json={"password": "Tablet-pass02"},
            headers=_CSRF,
        )
        assert reset_password.status_code == 200

        delete_active_user = client.delete("/cookdex/api/v1/users/admin", headers=_CSRF)
        assert delete_active_user.status_code == 409

        delete_user = client.delete("/cookdex/api/v1/users/kitchen-tablet", headers=_CSRF)
        assert delete_user.status_code == 200

        tasks = client.get("/cookdex/api/v1/tasks")
        assert tasks.status_code == 200
        task_items = tasks.json()["items"]
        task_ids = [item["task_id"] for item in task_items]
        assert "ingredient-parse" in task_ids
        task_map = {item["task_id"]: item for item in task_items}
        for task_id in ("tag-categorize", "data-maintenance"):
            provider_option = next((opt for opt in task_map[task_id]["options"] if opt["key"] == "provider"), None)
            assert provider_option is not None
            provider_values = [str(choice["value"]) for choice in provider_option.get("choices") or []]
            assert "" in provider_values
            assert "chatgpt" in provider_values
            assert "none" not in provider_values

        blocked = client.post(
            "/cookdex/api/v1/runs",
            json={"task_id": "ingredient-parse", "options": {"dry_run": False}},
            headers=_CSRF,
        )
        assert blocked.status_code == 403

        policies = client.put(
            "/cookdex/api/v1/policies",
            json={"policies": {"ingredient-parse": {"allow_dangerous": True}}},
            headers=_CSRF,
        )
        assert policies.status_code == 200
        assert policies.json()["policies"]["ingredient-parse"]["allow_dangerous"] is True

        queued = client.post(
            "/cookdex/api/v1/runs",
            json={"task_id": "ingredient-parse", "options": {"dry_run": False, "max_recipes": 1}},
            headers=_CSRF,
        )
        assert queued.status_code == 202
        assert queued.json()["task_id"] == "ingredient-parse"

        schedule_create = client.post(
            "/cookdex/api/v1/schedules",
            json={
                "name": "Parser Interval",
                "task_id": "ingredient-parse",
                "kind": "interval",
                "seconds": 600,
                "options": {"dry_run": True},
                "enabled": True,
            },
            headers=_CSRF,
        )
        assert schedule_create.status_code == 201
        schedule_id = schedule_create.json()["schedule_id"]
        assert schedule_create.json()["schedule_data"]["run_if_missed"] is False

        schedule_list = client.get("/cookdex/api/v1/schedules")
        assert schedule_list.status_code == 200
        assert any(item["schedule_id"] == schedule_id for item in schedule_list.json()["items"])

        settings_put = client.put(
            "/cookdex/api/v1/settings",
            json={
                "env": {
                    "MEALIE_URL": "http://example/api",
                    "MEALIE_API_KEY": "abc123",
                    "MAX_RUN_DURATION_SECONDS": "43200",
                }
            },
            headers=_CSRF,
        )
        assert settings_put.status_code == 200
        settings_get = client.get("/cookdex/api/v1/settings")
        assert settings_get.status_code == 200
        payload = settings_get.json()
        assert payload["env"]["MEALIE_URL"]["value"] == "http://example/api"
        assert payload["env"]["MEALIE_URL"]["source"] == "ui_setting"
        assert payload["env"]["MAX_RUN_DURATION_SECONDS"]["value"] == "43200"
        assert payload["secrets"]["MEALIE_API_KEY"] == "********"
        assert payload["env"]["MEALIE_API_KEY"]["has_value"] is True

        excessive_run_duration = client.put(
            "/cookdex/api/v1/settings",
            json={"env": {"MAX_RUN_DURATION_SECONDS": "43201"}},
            headers=_CSRF,
        )
        assert excessive_run_duration.status_code == 422

        unsupported_env = client.put(
            "/cookdex/api/v1/settings",
            json={"env": {"NOT_ALLOWED_ENV": "x"}},
            headers=_CSRF,
        )
        assert unsupported_env.status_code == 422

        config_list = client.get("/cookdex/api/v1/config/files")
        assert config_list.status_code == 200
        assert any(item["name"] == "categories" for item in config_list.json()["items"])

        config_get = client.get("/cookdex/api/v1/config/files/categories")
        assert config_get.status_code == 200
        assert config_get.json()["content"][0]["name"] == "Dinner"

        config_put = client.put(
            "/cookdex/api/v1/config/files/categories",
            json={"content": [{"name": "Breakfast"}]},
            headers=_CSRF,
        )
        assert config_put.status_code == 200
        assert "rule_sync" in config_put.json()
        config_get_updated = client.get("/cookdex/api/v1/config/files/categories")
        assert config_get_updated.json()["content"][0]["name"] == "Breakfast"


def test_schedule_once_and_interval_validation(tmp_path: Path, monkeypatch):
    """Schedule creation: once type, interval validation, and rejected kinds."""
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

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    # Short datetime-local format: "YYYY-MM-DDTHH:MM" (no seconds)
    future_short = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    # Full ISO format with seconds
    future_full = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")

    with TestClient(app) as client:
        _login(client)

        # --- once: short format (datetime-local) should be accepted ---
        r = client.post(
            "/cookdex/api/v1/schedules",
            json={
                "name": "One-time run",
                "task_id": "taxonomy-refresh",
                "kind": "once",
                "run_at": future_short,
                "run_if_missed": True,
                "enabled": True,
            },
            headers=_CSRF,
        )
        assert r.status_code == 201, r.text
        once_id = r.json()["schedule_id"]
        assert r.json()["schedule_kind"] == "once"
        assert r.json()["schedule_data"]["run_at"] == future_short
        assert r.json()["schedule_data"]["run_if_missed"] is True

        # --- once: full ISO format should also be accepted ---
        r2 = client.post(
            "/cookdex/api/v1/schedules",
            json={
                "name": "One-time run full",
                "task_id": "taxonomy-refresh",
                "kind": "once",
                "run_at": future_full,
                "enabled": True,
            },
            headers=_CSRF,
        )
        assert r2.status_code == 201, r2.text

        # --- once: missing run_at should be rejected ---
        r3 = client.post(
            "/cookdex/api/v1/schedules",
            json={
                "name": "Bad once",
                "task_id": "taxonomy-refresh",
                "kind": "once",
                "enabled": True,
            },
            headers=_CSRF,
        )
        assert r3.status_code == 422, r3.text

        # --- interval: zero seconds should be rejected ---
        r4 = client.post(
            "/cookdex/api/v1/schedules",
            json={
                "name": "Bad interval",
                "task_id": "taxonomy-refresh",
                "kind": "interval",
                "seconds": 0,
                "enabled": True,
            },
            headers=_CSRF,
        )
        assert r4.status_code == 422, r4.text

        # --- cron kind should be rejected (deprecated/removed) ---
        r5 = client.post(
            "/cookdex/api/v1/schedules",
            json={
                "name": "Cron attempt",
                "task_id": "taxonomy-refresh",
                "kind": "cron",
                "enabled": True,
            },
            headers=_CSRF,
        )
        assert r5.status_code == 422, r5.text

        # --- delete the once schedule ---
        del_r = client.delete(f"/cookdex/api/v1/schedules/{once_id}", headers=_CSRF)
        assert del_r.status_code == 200

        # --- verify it's gone ---
        list_r = client.get("/cookdex/api/v1/schedules")
        assert list_r.status_code == 200
        ids = [item["schedule_id"] for item in list_r.json()["items"]]
        assert once_id not in ids


def test_schedule_update_supports_run_if_missed_and_task_options(tmp_path: Path, monkeypatch):
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

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    future_short = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

    with TestClient(app) as client:
        _login(client)

        created = client.post(
            "/cookdex/api/v1/schedules",
            json={
                "name": "Parser Interval",
                "task_id": "ingredient-parse",
                "kind": "interval",
                "seconds": 600,
                "run_if_missed": False,
                "options": {"dry_run": True},
                "enabled": True,
            },
            headers=_CSRF,
        )
        assert created.status_code == 201, created.text
        schedule_id = created.json()["schedule_id"]

        updated = client.patch(
            f"/cookdex/api/v1/schedules/{schedule_id}",
            json={
                "name": "Parser Once",
                "kind": "once",
                "run_at": future_short,
                "run_if_missed": True,
                "options": {"dry_run": True, "max_recipes": 3},
            },
            headers=_CSRF,
        )
        assert updated.status_code == 200, updated.text
        payload = updated.json()
        assert payload["name"] == "Parser Once"
        assert payload["schedule_kind"] == "once"
        assert payload["schedule_data"]["run_at"] == future_short
        assert payload["schedule_data"]["run_if_missed"] is True
        assert payload["options"]["max_recipes"] == 3


def test_session_cookie_includes_persistent_ttl(tmp_path: Path, monkeypatch):
    config_root = tmp_path / "repo"
    _seed_config_root(config_root)

    monkeypatch.setenv("MO_WEBUI_MASTER_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("WEB_BOOTSTRAP_PASSWORD", "Secret-pass1")
    monkeypatch.setenv("WEB_BOOTSTRAP_USER", "admin")
    monkeypatch.setenv("WEB_STATE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WEB_BASE_PATH", "/cookdex")
    monkeypatch.setenv("WEB_CONFIG_ROOT", str(config_root))
    monkeypatch.setenv("WEB_COOKIE_SECURE", "false")
    monkeypatch.setenv("WEB_SESSION_TTL_SECONDS", "3600")

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    with TestClient(app) as client:
        response = client.post(
            "/cookdex/api/v1/auth/login",
            json={"username": "admin", "password": "Secret-pass1"},
            headers=_CSRF,
        )
        assert response.status_code == 200
        cookie_header = response.headers["set-cookie"]
        assert "Max-Age=3600" in cookie_header
        assert "expires=" in cookie_header

        expires_segment = cookie_header.split("expires=", 1)[1].split(";", 1)[0]
        expires_at = parsedate_to_datetime(expires_segment)
        expected = datetime.now(timezone.utc) + timedelta(seconds=3600)
        assert abs((expires_at - expected).total_seconds()) < 10


def test_schedule_validation_rejects_bad_payloads_without_persisting(tmp_path: Path, monkeypatch):
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

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    past_run_at = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    future_run_at = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with TestClient(app) as client:
        _login(client)

        bad_once = client.post(
            "/cookdex/api/v1/schedules",
            json={
                "name": "Broken once",
                "task_id": "taxonomy-refresh",
                "kind": "once",
                "run_at": "not-a-date",
                "enabled": True,
            },
            headers=_CSRF,
        )
        assert bad_once.status_code == 422
        assert client.get("/cookdex/api/v1/schedules").json()["items"] == []

        past_once = client.post(
            "/cookdex/api/v1/schedules",
            json={
                "name": "Past once",
                "task_id": "taxonomy-refresh",
                "kind": "once",
                "run_at": past_run_at,
                "enabled": True,
            },
            headers=_CSRF,
        )
        assert past_once.status_code == 422
        assert client.get("/cookdex/api/v1/schedules").json()["items"] == []

        created = client.post(
            "/cookdex/api/v1/schedules",
            json={
                "name": "Valid once",
                "task_id": "taxonomy-refresh",
                "kind": "once",
                "run_at": future_run_at,
                "enabled": True,
            },
            headers=_CSRF,
        )
        assert created.status_code == 201, created.text
        schedule_id = created.json()["schedule_id"]

        invalid_update = client.patch(
            f"/cookdex/api/v1/schedules/{schedule_id}",
            json={
                "kind": "interval",
                "seconds": 600,
                "start_at": "2026-04-08T10:00:00Z",
                "end_at": "2026-04-08T09:00:00Z",
            },
            headers=_CSRF,
        )
        assert invalid_update.status_code == 422

        schedule_after = client.get("/cookdex/api/v1/schedules").json()["items"][0]
        assert schedule_after["schedule_id"] == schedule_id
        assert schedule_after["schedule_kind"] == "once"
        assert schedule_after["schedule_data"]["run_at"] == future_run_at


def test_legacy_invalid_schedule_surfaces_validation_error_and_clears_after_fix(tmp_path: Path, monkeypatch):
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

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    with TestClient(app) as client:
        _login(client)
        services = app.state.services
        services.state.create_schedule(
            schedule_id="legacy-bad",
            name="Legacy broken",
            task_id="taxonomy-refresh",
            schedule_kind="once",
            schedule_data={"run_at": "not-a-date"},
            options={"dry_run": True},
            enabled=True,
        )
        services.scheduler._restore_from_db()

        schedules = client.get("/cookdex/api/v1/schedules")
        assert schedules.status_code == 200
        legacy = next(item for item in schedules.json()["items"] if item["schedule_id"] == "legacy-bad")
        assert legacy["validation_error"] == "Invalid isoformat string: 'not-a-date'"
        assert legacy["next_run_at"] is None

        future_run_at = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        repaired = client.patch(
            "/cookdex/api/v1/schedules/legacy-bad",
            json={"run_at": future_run_at},
            headers=_CSRF,
        )
        assert repaired.status_code == 200, repaired.text
        assert repaired.json()["validation_error"] is None
        assert repaired.json()["next_run_at"] is not None


def test_owner_editor_rbac_and_role_changes_apply_on_next_request(tmp_path: Path, monkeypatch):
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

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    with TestClient(app) as client:
        cookie_name = app.state.services.settings.cookie_name
        _login(client)
        owner_token = client.cookies.get(cookie_name)

        create_editor = client.post(
            "/cookdex/api/v1/users",
            json={"username": "editor", "password": "Editor-pass01", "role": "editor"},
            headers=_CSRF,
        )
        assert create_editor.status_code == 201, create_editor.text

        _login_as(client, "editor", "Editor-pass01")
        editor_token = client.cookies.get(cookie_name)
        editor_session = client.get("/cookdex/api/v1/auth/session")
        assert editor_session.status_code == 200
        assert editor_session.json()["role"] == "editor"

        assert client.get("/cookdex/api/v1/tasks").status_code == 200
        assert client.get("/cookdex/api/v1/schedules").status_code == 200
        assert client.get("/cookdex/api/v1/users").status_code == 403
        assert client.get("/cookdex/api/v1/settings").status_code == 403
        assert client.put(
            "/cookdex/api/v1/policies",
            json={"policies": {"ingredient-parse": {"allow_dangerous": True}}},
            headers=_CSRF,
        ).status_code == 403
        assert client.get("/cookdex/api/v1/debug-log").status_code == 403

        client.cookies.set(cookie_name, owner_token, path="/cookdex")

        promote = client.patch(
            "/cookdex/api/v1/users/editor/role",
            json={"role": "owner"},
            headers=_CSRF,
        )
        assert promote.status_code == 200, promote.text
        assert promote.json()["user"]["role"] == "owner"
        client.cookies.set(cookie_name, editor_token, path="/cookdex")
        assert client.get("/cookdex/api/v1/auth/session").json()["role"] == "owner"
        assert client.get("/cookdex/api/v1/users").status_code == 200

        client.cookies.set(cookie_name, owner_token, path="/cookdex")
        demote = client.patch(
            "/cookdex/api/v1/users/editor/role",
            json={"role": "editor"},
            headers=_CSRF,
        )
        assert demote.status_code == 200, demote.text
        client.cookies.set(cookie_name, editor_token, path="/cookdex")
        assert client.get("/cookdex/api/v1/auth/session").json()["role"] == "editor"
        assert client.get("/cookdex/api/v1/users").status_code == 403

        client.cookies.set(cookie_name, owner_token, path="/cookdex")
        self_demote = client.patch(
            "/cookdex/api/v1/users/admin/role",
            json={"role": "editor"},
            headers=_CSRF,
        )
        assert self_demote.status_code == 409


def test_master_key_auto_generated(tmp_path: Path, monkeypatch):
    """When MO_WEBUI_MASTER_KEY is unset, a key file is auto-generated next to the state DB."""
    config_root = tmp_path / "repo"
    _seed_config_root(config_root)

    db_path = tmp_path / "db" / "state.db"
    monkeypatch.delenv("MO_WEBUI_MASTER_KEY", raising=False)
    monkeypatch.delenv("MO_WEBUI_MASTER_KEY_FILE", raising=False)
    monkeypatch.delenv("WEB_BOOTSTRAP_PASSWORD", raising=False)
    monkeypatch.setenv("WEB_STATE_DB_PATH", str(db_path))
    monkeypatch.setenv("WEB_BASE_PATH", "/cookdex")
    monkeypatch.setenv("WEB_CONFIG_ROOT", str(config_root))
    monkeypatch.setenv("WEB_COOKIE_SECURE", "false")

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    key_file = db_path.parent / ".secrets" / ".master_key"
    assert key_file.exists(), "Auto-generated key file should exist"
    first_key = key_file.read_text(encoding="utf-8").strip()
    assert len(first_key) > 0

    # Second startup reuses the same key
    importlib.reload(app_module)
    app2 = app_module.create_app()
    assert key_file.read_text(encoding="utf-8").strip() == first_key

    with TestClient(app) as client:
        health = client.get("/cookdex/api/v1/health")
        assert health.status_code == 200

        # Registration still works (no bootstrap password = setup required)
        bootstrap = client.get("/cookdex/api/v1/auth/bootstrap-status")
        assert bootstrap.json()["setup_required"] is True


def test_webui_first_time_registration_without_bootstrap_password(tmp_path: Path, monkeypatch):
    config_root = tmp_path / "repo"
    _seed_config_root(config_root)

    monkeypatch.setenv("MO_WEBUI_MASTER_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.delenv("WEB_BOOTSTRAP_PASSWORD", raising=False)
    monkeypatch.setenv("WEB_BOOTSTRAP_USER", "admin")
    monkeypatch.setenv("WEB_STATE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WEB_BASE_PATH", "/cookdex")
    monkeypatch.setenv("WEB_CONFIG_ROOT", str(config_root))
    monkeypatch.setenv("WEB_COOKIE_SECURE", "false")

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    with TestClient(app) as client:
        bootstrap_status = client.get("/cookdex/api/v1/auth/bootstrap-status")
        assert bootstrap_status.status_code == 200
        assert bootstrap_status.json()["setup_required"] is True

        blocked_login = client.post(
            "/cookdex/api/v1/auth/login",
            json={"username": "admin", "password": "secret-pass"},
            headers=_CSRF,
        )
        assert blocked_login.status_code == 409

        register = client.post(
            "/cookdex/api/v1/auth/register",
            json={"username": "admin", "password": "Secret-pass1"},
            headers=_CSRF,
        )
        assert register.status_code == 200
        assert register.json()["username"] == "admin"
        assert register.json()["role"] == "owner"

        users = client.get("/cookdex/api/v1/users")
        assert users.status_code == 200
        assert any(item["username"] == "admin" for item in users.json()["items"])


def test_csrf_middleware_rejects_missing_header(tmp_path: Path, monkeypatch):
    config_root = tmp_path / "repo"
    _seed_config_root(config_root)

    monkeypatch.setenv("MO_WEBUI_MASTER_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("WEB_BOOTSTRAP_PASSWORD", "Secret-pass1")
    monkeypatch.setenv("WEB_BOOTSTRAP_USER", "admin")
    monkeypatch.setenv("WEB_STATE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WEB_BASE_PATH", "/cookdex")
    monkeypatch.setenv("WEB_CONFIG_ROOT", str(config_root))
    monkeypatch.setenv("WEB_COOKIE_SECURE", "false")

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    with TestClient(app) as client:
        # POST without CSRF header should be rejected
        response = client.post(
            "/cookdex/api/v1/auth/login",
            json={"username": "admin", "password": "Secret-pass1"},
        )
        assert response.status_code == 403
        assert "CSRF" in response.json().get("detail", "")

        # GET requests should still work without the header
        health = client.get("/cookdex/api/v1/health")
        assert health.status_code == 200


def test_weak_master_key_blocks_secret_storage(tmp_path: Path, monkeypatch):
    config_root = tmp_path / "repo"
    _seed_config_root(config_root)

    monkeypatch.setenv("MO_WEBUI_MASTER_KEY", "changeme")
    monkeypatch.setenv("WEB_BOOTSTRAP_PASSWORD", "Secret-pass1")
    monkeypatch.setenv("WEB_BOOTSTRAP_USER", "admin")
    monkeypatch.setenv("WEB_STATE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WEB_BASE_PATH", "/cookdex")
    monkeypatch.setenv("WEB_CONFIG_ROOT", str(config_root))
    monkeypatch.setenv("WEB_COOKIE_SECURE", "false")
    monkeypatch.setenv("MEALIE_URL", "http://127.0.0.1:9000/api")
    monkeypatch.setenv("MEALIE_API_KEY", "placeholder")

    app_module = importlib.import_module("cookdex.webui_server.app")
    importlib.reload(app_module)
    app = app_module.create_app()

    with TestClient(app) as client:
        _login(client)

        # Saving a secret should be blocked
        result = client.put(
            "/cookdex/api/v1/settings",
            json={"env": {}, "secrets": {"OPENAI_API_KEY": "sk-test"}},
            headers=_CSRF,
        )
        assert result.status_code == 400
        assert "weak" in result.json()["detail"].lower()

        # Saving non-secret env vars should still work
        result2 = client.put(
            "/cookdex/api/v1/settings",
            json={"env": {"MEALIE_URL": "http://example/api"}},
            headers=_CSRF,
        )
        assert result2.status_code == 200
