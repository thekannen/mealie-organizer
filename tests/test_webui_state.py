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

    token = "token-1"
    expires_at = "2099-01-01T00:00:00Z"
    store.create_session(token=token, username="admin", expires_at=expires_at)
    session = store.get_session(token)
    assert session is not None
    assert session["username"] == "admin"
    assert session["expires_at"] == expires_at
