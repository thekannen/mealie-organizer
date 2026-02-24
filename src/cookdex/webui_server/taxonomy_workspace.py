from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import requests

from ..api_client import MealieApiClient
from .config_files import ConfigFilesManager

TAXONOMY_FILE_NAMES: tuple[str, ...] = (
    "categories",
    "tags",
    "cookbooks",
    "labels",
    "tools",
    "units_aliases",
)
STARTER_PACK_DEFAULT_BASE_URL = "https://raw.githubusercontent.com/thekannen/cookdex/main/configs/taxonomy"
STARTER_PACK_FILES: dict[str, str] = {
    "categories": "categories.json",
    "tags": "tags.json",
    "cookbooks": "cookbooks.json",
    "labels": "labels.json",
    "tools": "tools.json",
    "units_aliases": "units_aliases.json",
}


def _normalize_name(value: Any) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())


def _name_key(value: Any) -> str:
    return _normalize_name(value).casefold()


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    return default


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str):
        raw = [part.strip() for part in value.split(",")]
    else:
        raw = []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = _normalize_name(item)
        key = _name_key(name)
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _normalize_named_entries(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            name = _normalize_name(item.get("name"))
        else:
            name = _normalize_name(item)
        key = _name_key(name)
        if not name or key in seen:
            continue
        seen.add(key)
        out.append({"name": name})
    return out


def _normalize_label_entries(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            name = _normalize_name(item.get("name"))
            color = _normalize_name(item.get("color")) or "#959595"
        else:
            name = _normalize_name(item)
            color = "#959595"
        key = _name_key(name)
        if not name or key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "color": color})
    return out


def _normalize_tool_entries(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            name = _normalize_name(item.get("name"))
            on_hand = _bool_value(item.get("onHand"), default=False)
        else:
            name = _normalize_name(item)
            on_hand = False
        key = _name_key(name)
        if not name or key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "onHand": on_hand})
    return out


def _normalize_cookbook_entries(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = _normalize_name(item.get("name"))
        key = _name_key(name)
        if not name or key in seen:
            continue
        seen.add(key)
        position_raw = item.get("position", index + 1)
        try:
            position = int(position_raw)
        except Exception:
            position = index + 1
        if position <= 0:
            position = index + 1
        out.append(
            {
                "name": name,
                "description": _normalize_name(item.get("description")),
                "queryFilterString": _normalize_name(item.get("queryFilterString")),
                "public": _bool_value(item.get("public"), default=False),
                "position": position,
            }
        )
    return out


def _normalize_unit_entries(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _normalize_name(item.get("name") or item.get("canonical"))
        key = _name_key(name)
        if not name or key in seen:
            continue
        seen.add(key)

        entry: dict[str, Any] = {
            "name": name,
            "fraction": _bool_value(item.get("fraction"), default=True),
            "useAbbreviation": _bool_value(item.get("useAbbreviation"), default=False),
            "aliases": _string_list(item.get("aliases")),
        }

        for field in ("pluralName", "abbreviation", "pluralAbbreviation", "description"):
            value = _normalize_name(item.get(field))
            if value:
                entry[field] = value

        for field in ("abbreviation", "pluralAbbreviation"):
            value = _normalize_name(item.get(field))
            if value and _name_key(value) != key:
                entry["aliases"] = _string_list([*entry["aliases"], value])

        out.append(entry)
    return out


def _normalize_payload(file_name: str, content: Any) -> list[dict[str, Any]]:
    if file_name in {"categories", "tags"}:
        return _normalize_named_entries(content)
    if file_name == "labels":
        return _normalize_label_entries(content)
    if file_name == "tools":
        return _normalize_tool_entries(content)
    if file_name == "cookbooks":
        return _normalize_cookbook_entries(content)
    if file_name == "units_aliases":
        return _normalize_unit_entries(content)
    return []


def _merge_units(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged["aliases"] = _string_list([*(existing.get("aliases") or []), *(incoming.get("aliases") or [])])
    for field in ("pluralName", "abbreviation", "pluralAbbreviation", "description"):
        if not _normalize_name(merged.get(field)) and _normalize_name(incoming.get(field)):
            merged[field] = _normalize_name(incoming.get(field))
    merged["fraction"] = _bool_value(existing.get("fraction"), default=True)
    merged["useAbbreviation"] = _bool_value(existing.get("useAbbreviation"), default=False) or _bool_value(
        incoming.get("useAbbreviation"), default=False
    )
    return merged


def _merge_items(file_name: str, existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [dict(item) for item in existing]
    index_by_key = {_name_key(item.get("name")): idx for idx, item in enumerate(out) if _normalize_name(item.get("name"))}

    for incoming_item in incoming:
        key = _name_key(incoming_item.get("name"))
        if not key:
            continue
        idx = index_by_key.get(key)
        if idx is None:
            index_by_key[key] = len(out)
            out.append(dict(incoming_item))
            continue
        if file_name == "units_aliases":
            out[idx] = _merge_units(out[idx], incoming_item)
        elif file_name == "tools":
            out[idx]["onHand"] = _bool_value(out[idx].get("onHand"), False) or _bool_value(
                incoming_item.get("onHand"), False
            )
        elif file_name == "labels":
            if not _normalize_name(out[idx].get("color")) and _normalize_name(incoming_item.get("color")):
                out[idx]["color"] = _normalize_name(incoming_item.get("color"))

    return out


def _extract_list_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("items", data.get("data"))
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


class TaxonomyWorkspaceService:
    def __init__(self, *, repo_root: Path, config_files: ConfigFilesManager) -> None:
        self.repo_root = repo_root
        self.config_files = config_files

    def starter_pack_info(self) -> dict[str, Any]:
        return {
            "default_base_url": STARTER_PACK_DEFAULT_BASE_URL,
            "files": dict(STARTER_PACK_FILES),
        }

    def initialize_from_mealie(
        self,
        *,
        mealie_url: str,
        mealie_api_key: str,
        mode: str = "replace",
        include_files: list[str] | None = None,
        client: MealieApiClient | None = None,
    ) -> dict[str, Any]:
        mode = self._normalize_mode(mode)
        selected = self._normalize_file_list(include_files)
        api_client = client or MealieApiClient(base_url=mealie_url, api_key=mealie_api_key)

        incoming: dict[str, list[dict[str, Any]]] = {
            "categories": _normalize_named_entries(api_client.get_organizer_items("categories")),
            "tags": _normalize_named_entries(api_client.get_organizer_items("tags")),
            "labels": _normalize_label_entries(api_client.list_labels()),
            "tools": _normalize_tool_entries(api_client.list_tools()),
            "units_aliases": _normalize_unit_entries(api_client.list_units()),
            "cookbooks": _normalize_cookbook_entries(
                _extract_list_payload(api_client.request_json("GET", "/households/cookbooks", timeout=60))
            ),
        }
        return self._apply_payloads(payloads=incoming, mode=mode, include_files=selected, source="mealie")

    def import_starter_pack(
        self,
        *,
        mode: str = "merge",
        include_files: list[str] | None = None,
        base_url: str | None = None,
        fetcher: Callable[[str], Any] | None = None,
    ) -> dict[str, Any]:
        mode = self._normalize_mode(mode)
        selected = self._normalize_file_list(include_files)
        root = (base_url or STARTER_PACK_DEFAULT_BASE_URL).strip().rstrip("/")
        if not root:
            raise ValueError("Starter pack URL is required.")

        fetch = fetcher or self._fetch_json_url
        incoming: dict[str, list[dict[str, Any]]] = {}
        cache_dir = (self.repo_root / "cache" / "starter-pack").resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)

        for file_name in selected:
            remote_name = STARTER_PACK_FILES[file_name]
            url = f"{root}/{remote_name}"
            payload = fetch(url)
            normalized = _normalize_payload(file_name, payload)
            incoming[file_name] = normalized
            cache_path = cache_dir / remote_name
            cache_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

        return self._apply_payloads(payloads=incoming, mode=mode, include_files=selected, source="starter-pack")

    @staticmethod
    def _fetch_json_url(url: str) -> Any:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError(f"Starter pack URL returned invalid JSON: {url}") from exc

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        normalized = str(mode or "merge").strip().lower()
        if normalized not in {"merge", "replace"}:
            raise ValueError("mode must be 'merge' or 'replace'.")
        return normalized

    @staticmethod
    def _normalize_file_list(include_files: list[str] | None) -> list[str]:
        if include_files is None:
            return list(TAXONOMY_FILE_NAMES)
        seen: set[str] = set()
        selected: list[str] = []
        for raw in include_files:
            name = str(raw or "").strip()
            if not name:
                continue
            if name not in TAXONOMY_FILE_NAMES:
                raise ValueError(f"Unsupported taxonomy file '{name}'.")
            if name in seen:
                continue
            seen.add(name)
            selected.append(name)
        if not selected:
            raise ValueError("At least one taxonomy file must be selected.")
        return selected

    def _read_file_array(self, file_name: str) -> list[dict[str, Any]]:
        try:
            payload = self.config_files.read_file(file_name)
        except FileNotFoundError:
            return []
        content = payload.get("content")
        return _normalize_payload(file_name, content)

    def _apply_payloads(
        self,
        *,
        payloads: dict[str, list[dict[str, Any]]],
        mode: str,
        include_files: list[str],
        source: str,
    ) -> dict[str, Any]:
        changed: dict[str, dict[str, Any]] = {}
        for file_name in include_files:
            incoming = _normalize_payload(file_name, payloads.get(file_name, []))
            existing = self._read_file_array(file_name)
            merged = incoming if mode == "replace" else _merge_items(file_name, existing, incoming)
            self.config_files.write_file(file_name, merged)
            changed[file_name] = {
                "existing_count": len(existing),
                "incoming_count": len(incoming),
                "result_count": len(merged),
            }
        return {
            "source": source,
            "mode": mode,
            "files": include_files,
            "changes": changed,
        }
