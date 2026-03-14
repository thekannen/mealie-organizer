from __future__ import annotations

import json
from pathlib import Path

from cookdex.webui_server.config_files import ConfigFilesManager
from cookdex.webui_server.state import StateStore


def _make_state(tmp_path: Path) -> StateStore:
    state = StateStore(tmp_path / "state.db")
    state.initialize(task_ids=[])
    return state


def test_write_and_read_via_state(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    state = _make_state(tmp_path)

    mgr = ConfigFilesManager(root, state=state)
    mgr.write_file("categories", [{"name": "Updated"}])

    result = mgr.read_file("categories")
    assert result["content"] == [{"name": "Updated"}]


def test_write_replaces_collection(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    state = _make_state(tmp_path)

    mgr = ConfigFilesManager(root, state=state)
    mgr.write_file("categories", [{"name": "v1"}])
    mgr.write_file("categories", [{"name": "v2"}, {"name": "v3"}])

    result = mgr.read_file("categories")
    assert result["content"] == [{"name": "v2"}, {"name": "v3"}]


def test_read_file_returns_content(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    state = _make_state(tmp_path)

    state.taxonomy_set("categories", [{"name": "Dinner"}])
    mgr = ConfigFilesManager(root, state=state)
    result = mgr.read_file("categories")
    assert result["content"] == [{"name": "Dinner"}]


def test_list_files_shows_existence(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    state = _make_state(tmp_path)

    mgr = ConfigFilesManager(root, state=state)
    files = mgr.list_files()
    assert all(f["exists"] is False for f in files)

    state.taxonomy_set("categories", [{"name": "Test"}])
    files = mgr.list_files()
    cats = next(f for f in files if f["name"] == "categories")
    assert cats["exists"] is True


def test_write_requires_state(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    mgr = ConfigFilesManager(root)
    try:
        mgr.write_file("categories", [{"name": "x"}])
        assert False, "Expected RuntimeError"
    except RuntimeError:
        pass
