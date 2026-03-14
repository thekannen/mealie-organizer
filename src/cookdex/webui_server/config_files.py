from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .state import StateStore


@dataclass(frozen=True)
class ManagedConfigFile:
    name: str
    relative_path: str
    expected_type: str


# Taxonomy collections — stored in state.db, not JSON files.
# The relative_path is retained for backward compatibility in API responses.
MANAGED_CONFIG_FILES: tuple[ManagedConfigFile, ...] = (
    ManagedConfigFile("categories", "configs/taxonomy/categories.json", "array"),
    ManagedConfigFile("tags", "configs/taxonomy/tags.json", "array"),
    ManagedConfigFile("cookbooks", "configs/taxonomy/cookbooks.json", "array"),
    ManagedConfigFile("labels", "configs/taxonomy/labels.json", "array"),
    ManagedConfigFile("tools", "configs/taxonomy/tools.json", "array"),
    ManagedConfigFile("units_aliases", "configs/taxonomy/units_aliases.json", "array"),
)


class ConfigFilesManager:
    def __init__(self, repo_root: Path, state: StateStore | None = None):
        self.repo_root = repo_root
        self._state = state
        self._index: dict[str, ManagedConfigFile] = {item.name: item for item in MANAGED_CONFIG_FILES}

    def _require_state(self) -> StateStore:
        if self._state is None:
            raise RuntimeError("StateStore not configured")
        return self._state

    def list_files(self) -> list[dict[str, Any]]:
        state = self._require_state()
        return [
            {
                "name": item.name,
                "path": item.relative_path,
                "exists": not state.taxonomy_is_empty(item.name),
                "expected_type": item.expected_type,
            }
            for item in MANAGED_CONFIG_FILES
        ]

    def read_file(self, name: str) -> dict[str, Any]:
        item = self._resolve(name)
        state = self._require_state()
        content = state.taxonomy_get(item.name)
        return {"name": item.name, "path": item.relative_path, "content": content}

    def write_file(self, name: str, content: Any) -> dict[str, Any]:
        item = self._resolve(name)
        if not isinstance(content, list):
            raise ValueError(f"{item.name} requires a JSON array payload.")
        state = self._require_state()
        state.taxonomy_set(item.name, content)
        return {"name": item.name, "path": item.relative_path, "content": content}

    def _resolve(self, name: str) -> ManagedConfigFile:
        item = self._index.get(name)
        if item is None:
            raise KeyError(name)
        return item
