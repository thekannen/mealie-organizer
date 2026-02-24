from __future__ import annotations

from cookdex.webui_server.routers import settings_api


def test_parse_mealie_env_accepts_export_lines() -> None:
    payload = """
    export POSTGRES_USER=mealie__user
    export POSTGRES_PASSWORD=super-secret
    POSTGRES_DB=mealie_db
    POSTGRES_SERVER=localhost
    POSTGRES_PORT=5432
    """
    parsed = settings_api._parse_mealie_env(payload)
    assert parsed["MEALIE_PG_USER"] == "mealie__user"
    assert parsed["MEALIE_PG_PASS"] == "super-secret"
    assert parsed["MEALIE_PG_DB"] == "mealie_db"
    assert parsed["MEALIE_PG_HOST"] == "localhost"
    assert parsed["MEALIE_PG_PORT"] == "5432"
    assert parsed["MEALIE_DB_TYPE"] == "postgres"


def test_parse_mealie_env_accepts_compose_mapping_syntax() -> None:
    payload = """
    DB_ENGINE: postgres
    POSTGRES_USER: mealie_yaml
    POSTGRES_PASSWORD: yaml-secret
    POSTGRES_DB: mealie_yaml_db
    POSTGRES_SERVER: 192.168.1.10
    POSTGRES_PORT: 5433
    """
    parsed = settings_api._parse_mealie_env(payload)
    assert parsed["MEALIE_DB_TYPE"] == "postgres"
    assert parsed["MEALIE_PG_USER"] == "mealie_yaml"
    assert parsed["MEALIE_PG_PASS"] == "yaml-secret"
    assert parsed["MEALIE_PG_DB"] == "mealie_yaml_db"
    assert parsed["MEALIE_PG_HOST"] == "192.168.1.10"
    assert parsed["MEALIE_PG_PORT"] == "5433"


def test_parse_mealie_env_url_override_takes_precedence() -> None:
    payload = """
    DB_ENGINE=postgres
    POSTGRES_USER=ignored_user
    POSTGRES_URL_OVERRIDE=postgresql://real_user:real_pass@db.example.com:5544/real_db
    """
    parsed = settings_api._parse_mealie_env(payload)
    assert parsed["MEALIE_PG_USER"] == "real_user"
    assert parsed["MEALIE_PG_PASS"] == "real_pass"
    assert parsed["MEALIE_PG_HOST"] == "localhost"
    assert parsed["MEALIE_PG_PORT"] == "5544"
    assert parsed["MEALIE_PG_DB"] == "real_db"
    assert parsed["MEALIE_DB_TYPE"] == "postgres"


def test_detect_db_credentials_falls_back_to_env_files(monkeypatch) -> None:
    def fake_ssh_exec(host: str, user: str, key: str, command: str, *, timeout: int = 15):
        if "docker ps --format" in command:
            return "", "docker: command not found", 127
        if "__CFG_FILE__:" in command:
            return (
                "__CFG_FILE__:/opt/mealie/mealie.env\n"
                "POSTGRES_USER=detected_user\n"
                "POSTGRES_PASSWORD=detected_pass\n"
                "POSTGRES_DB=detected_db\n"
                "POSTGRES_SERVER=localhost\n"
                "POSTGRES_PORT=5432\n",
                "",
                0,
            )
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(settings_api, "_ssh_exec", fake_ssh_exec)
    ok, detail, detected = settings_api._detect_db_credentials("host", "user", "key")
    assert ok is True
    assert "config" in detail.lower()
    assert detected["MEALIE_PG_USER"] == "detected_user"
    assert detected["MEALIE_PG_PASS"] == "detected_pass"
    assert detected["MEALIE_PG_DB"] == "detected_db"


def test_detect_db_credentials_reports_both_sources_when_not_found(monkeypatch) -> None:
    def fake_ssh_exec(host: str, user: str, key: str, command: str, *, timeout: int = 15):
        if "docker ps --format" in command:
            return "", "docker: command not found", 127
        if "__CFG_FILE__:" in command:
            return "", "", 0
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(settings_api, "_ssh_exec", fake_ssh_exec)
    ok, detail, detected = settings_api._detect_db_credentials("host", "user", "key")
    assert ok is False
    assert detected == {}
    assert "docker discovery unavailable" in detail.lower()
    assert "no mealie config" in detail.lower()
