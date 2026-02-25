from __future__ import annotations

import json
from pathlib import Path

from cookdex.webui_server.config_files import ConfigFilesManager


def test_write_file_creates_backup(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "configs" / "taxonomy").mkdir(parents=True)
    cats = root / "configs" / "taxonomy" / "categories.json"
    cats.write_text(json.dumps([{"name": "Original"}]), encoding="utf-8")

    mgr = ConfigFilesManager(root)
    mgr.write_file("categories", [{"name": "Updated"}])

    history = root / "configs" / ".history"
    assert history.exists()
    backups = list(history.glob("categories.*.json"))
    assert len(backups) == 1
    backup_content = json.loads(backups[0].read_text(encoding="utf-8"))
    assert backup_content == [{"name": "Original"}]


def test_write_file_rotates_old_backups(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "configs" / "taxonomy").mkdir(parents=True)
    cats = root / "configs" / "taxonomy" / "categories.json"
    cats.write_text(json.dumps([{"name": "v0"}]), encoding="utf-8")

    history = root / "configs" / ".history"
    history.mkdir(parents=True)

    # Create 25 fake backups
    for i in range(25):
        fake = history / f"categories.2026{i:04d}T000000Z.json"
        fake.write_text(json.dumps([{"name": f"v{i}"}]), encoding="utf-8")

    mgr = ConfigFilesManager(root)
    mgr.write_file("categories", [{"name": "Latest"}])

    remaining = sorted(history.glob("categories.*.json"))
    # 25 old + 1 new = 26, rotated to keep 20
    assert len(remaining) == 20


def test_read_file_returns_content(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "configs" / "taxonomy").mkdir(parents=True)
    cats = root / "configs" / "taxonomy" / "categories.json"
    cats.write_text(json.dumps([{"name": "Dinner"}]), encoding="utf-8")

    mgr = ConfigFilesManager(root)
    result = mgr.read_file("categories")
    assert result["content"] == [{"name": "Dinner"}]
