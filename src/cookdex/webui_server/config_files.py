from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ManagedConfigFile:
    name: str
    relative_path: str
    expected_type: str


MANAGED_CONFIG_FILES: tuple[ManagedConfigFile, ...] = (
    ManagedConfigFile("config", "configs/config.json", "object"),
    ManagedConfigFile("categories", "configs/taxonomy/categories.json", "array"),
    ManagedConfigFile("tags", "configs/taxonomy/tags.json", "array"),
    ManagedConfigFile("cookbooks", "configs/taxonomy/cookbooks.json", "array"),
    ManagedConfigFile("labels", "configs/taxonomy/labels.json", "array"),
    ManagedConfigFile("tools", "configs/taxonomy/tools.json", "array"),
    ManagedConfigFile("units_aliases", "configs/taxonomy/units_aliases.json", "array"),
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class ConfigFilesManager:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._index: dict[str, ManagedConfigFile] = {item.name: item for item in MANAGED_CONFIG_FILES}

    def list_files(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for item in MANAGED_CONFIG_FILES:
            path = (self.repo_root / item.relative_path).resolve()
            payload.append(
                {
                    "name": item.name,
                    "path": item.relative_path,
                    "exists": path.exists(),
                    "expected_type": item.expected_type,
                }
            )
        return payload

    def read_file(self, name: str) -> dict[str, Any]:
        item = self._resolve(name)
        path = (self.repo_root / item.relative_path).resolve()
        if not path.exists():
            raise FileNotFoundError(item.relative_path)
        content = json.loads(path.read_text(encoding="utf-8"))
        self._validate_type(item, content)
        return {"name": item.name, "path": item.relative_path, "content": content}

    def write_file(self, name: str, content: Any) -> dict[str, Any]:
        item = self._resolve(name)
        self._validate_type(item, content)

        path = (self.repo_root / item.relative_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        history_dir = (self.repo_root / "configs" / ".history").resolve()
        history_dir.mkdir(parents=True, exist_ok=True)

        if path.exists():
            backup_name = f"{item.name}.{_utc_stamp()}.json"
            backup_path = history_dir / backup_name
            backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

        temp_path = path.with_suffix(path.suffix + ".tmp")
        serialized = json.dumps(content, indent=2, ensure_ascii=True) + "\n"
        temp_path.write_text(serialized, encoding="utf-8")
        temp_path.replace(path)
        return {"name": item.name, "path": item.relative_path, "content": content}

    def _resolve(self, name: str) -> ManagedConfigFile:
        item = self._index.get(name)
        if item is None:
            raise KeyError(name)
        return item

    @staticmethod
    def _validate_type(item: ManagedConfigFile, content: Any) -> None:
        if item.expected_type == "object" and not isinstance(content, dict):
            raise ValueError(f"{item.name} requires a JSON object payload.")
        if item.expected_type == "array" and not isinstance(content, list):
            raise ValueError(f"{item.name} requires a JSON array payload.")
