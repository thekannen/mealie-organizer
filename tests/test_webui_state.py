import sqlite3
from pathlib import Path

from cookdex.webui_server.state import StateStore


def test_state_initializes_task_policies(tmp_path: Path):
    store = StateStore(tmp_path / "state.db")
    store.initialize(["ingredient-parse", "cleanup-duplicates"])
    policies = store.list_task_policies()
    assert sorted(policies.keys()) == ["cleanup-duplicates", "ingredient-parse"]
    assert policies["ingredient-parse"]["allow_dangerous"] is False


def test_state_user_and_session_roundtrip(tmp_path: Path):
    store = StateStore(tmp_path / "state.db")
    store.initialize([])
    store.upsert_user("admin", "hash-value")
    assert store.get_password_hash("admin") == "hash-value"
    assert store.get_user("admin")["role"] == "owner"

    token = "token-1"
    expires_at = "2099-01-01T00:00:00Z"
    store.create_session(token=token, username="admin", expires_at=expires_at)
    session = store.get_session(token)
    assert session is not None
    assert session["username"] == "admin"
    assert session["expires_at"] == expires_at


def test_state_migrates_existing_users_to_owner_and_editor(tmp_path: Path):
    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE users (
              username TEXT PRIMARY KEY,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              force_password_reset INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        conn.execute(
            "INSERT INTO users(username, password_hash, created_at, force_password_reset) VALUES(?, ?, ?, ?);",
            ("admin", "hash-1", "2026-01-01T00:00:00Z", 0),
        )
        conn.execute(
            "INSERT INTO users(username, password_hash, created_at, force_password_reset) VALUES(?, ?, ?, ?);",
            ("editor", "hash-2", "2026-01-02T00:00:00Z", 0),
        )
        conn.commit()
    finally:
        conn.close()

    store = StateStore(db_path)
    store.initialize([])

    users = {item["username"]: item for item in store.list_users()}
    assert users["admin"]["role"] == "owner"
    assert users["editor"]["role"] == "editor"
