from __future__ import annotations

import json
import re
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
TAG_RULES_RELATIVE_PATH = "configs/taxonomy/tag_rules.json"
RULE_TARGET_FIELDS: dict[str, str] = {
    "ingredient_tags": "tag",
    "text_tags": "tag",
    "text_categories": "category",
    "ingredient_categories": "category",
    "tool_tags": "tool",
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


def _empty_rule_payload() -> dict[str, list[dict[str, Any]]]:
    return {section: [] for section in RULE_TARGET_FIELDS}


def _normalize_rules_payload(content: Any) -> dict[str, list[dict[str, Any]]]:
    payload = _empty_rule_payload()
    if not isinstance(content, dict):
        return payload
    for section in RULE_TARGET_FIELDS:
        raw_items = content.get(section, [])
        if not isinstance(raw_items, list):
            continue
        payload[section] = [dict(item) for item in raw_items if isinstance(item, dict)]
    return payload


def _rule_pattern_for_name(name: Any) -> str:
    """Create a conservative keyword pattern for a taxonomy name."""
    normalized = _normalize_name(name)
    tokens = re.findall(r"[A-Za-z0-9]+", normalized)
    if not tokens:
        escaped = re.escape(normalized)
        return rf"\y{escaped}\y" if escaped else ""
    core = r"[\s_-]+".join(re.escape(token) for token in tokens)
    return rf"\y{core}\y"


def _generate_default_rules_from_taxonomy(
    *,
    tags: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    def _sorted_names(items: list[dict[str, Any]]) -> list[str]:
        seen: set[str] = set()
        names: list[str] = []
        for item in items:
            name = _normalize_name(item.get("name"))
            key = _name_key(name)
            if not name or key in seen:
                continue
            seen.add(key)
            names.append(name)
        names.sort(key=lambda value: value.casefold())
        return names

    tag_names = _sorted_names(tags)
    category_names = _sorted_names(categories)
    tool_names = _sorted_names(tools)

    return {
        "ingredient_tags": [],
        "ingredient_categories": [],
        "text_tags": [{"tag": name, "pattern": _rule_pattern_for_name(name)} for name in tag_names],
        "text_categories": [{"category": name, "pattern": _rule_pattern_for_name(name)} for name in category_names],
        "tool_tags": [{"tool": name, "pattern": _rule_pattern_for_name(name)} for name in tool_names],
    }


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

    def sync_tag_rules_targets(self) -> dict[str, Any]:
        """Reconcile tag_rules targets against current taxonomy files.

        Rules that point to missing tags/categories/tools are removed to prevent
        re-introducing stale "golden image" terms after users adopt their own
        taxonomy baseline.
        """
        tags = self._read_file_array("tags")
        categories = self._read_file_array("categories")
        tools = self._read_file_array("tools")

        tags_by_key = {_name_key(item.get("name")): _normalize_name(item.get("name")) for item in tags}
        categories_by_key = {_name_key(item.get("name")): _normalize_name(item.get("name")) for item in categories}
        tools_by_key = {_name_key(item.get("name")): _normalize_name(item.get("name")) for item in tools}

        allowed_by_field: dict[str, dict[str, str]] = {
            "tag": tags_by_key,
            "category": categories_by_key,
            "tool": tools_by_key,
        }

        rules_path = (self.repo_root / TAG_RULES_RELATIVE_PATH).resolve()
        before_exists = rules_path.exists()
        try:
            existing_payload = json.loads(rules_path.read_text(encoding="utf-8")) if before_exists else _empty_rule_payload()
        except Exception:
            existing_payload = _empty_rule_payload()

        normalized = _normalize_rules_payload(existing_payload)
        generated_defaults = _generate_default_rules_from_taxonomy(
            tags=tags,
            categories=categories,
            tools=tools,
        )
        synced = _empty_rule_payload()

        removed_by_section: dict[str, int] = {}
        generated_by_section: dict[str, int] = {}
        canonicalized_total = 0
        generated_total = 0
        removed_examples: dict[str, list[str]] = {}

        for section, target_field in RULE_TARGET_FIELDS.items():
            allowed = allowed_by_field[target_field]
            removed_count = 0
            removed_names: list[str] = []
            kept: list[dict[str, Any]] = []
            seen_targets: set[str] = set()

            for rule in normalized.get(section, []):
                target = _normalize_name(rule.get(target_field))
                target_key = _name_key(target)
                canonical_target = allowed.get(target_key, "")
                if not canonical_target:
                    removed_count += 1
                    if target:
                        removed_names.append(target)
                    continue
                rule_copy = dict(rule)
                if canonical_target != target:
                    canonicalized_total += 1
                    rule_copy[target_field] = canonical_target
                kept.append(rule_copy)
                seen_targets.add(_name_key(canonical_target))

            generated_count = 0
            for default_rule in generated_defaults.get(section, []):
                target = _normalize_name(default_rule.get(target_field))
                target_key = _name_key(target)
                if not target_key or target_key in seen_targets:
                    continue
                kept.append(dict(default_rule))
                seen_targets.add(target_key)
                generated_count += 1

            if generated_count:
                generated_by_section[section] = generated_count
                generated_total += generated_count

            if removed_count:
                removed_by_section[section] = removed_count
                if removed_names:
                    removed_examples[section] = sorted(set(removed_names))[:8]
            synced[section] = kept

        changed = synced != normalized or not before_exists
        if changed:
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            rules_path.write_text(json.dumps(synced, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

        removed_total = sum(removed_by_section.values())
        kept_total = sum(len(synced.get(section, [])) for section in RULE_TARGET_FIELDS)
        result = {
            "file": TAG_RULES_RELATIVE_PATH,
            "updated": changed,
            "created": (not before_exists) and changed,
            "removed_total": removed_total,
            "generated_total": generated_total,
            "canonicalized_total": canonicalized_total,
            "kept_total": kept_total,
            "removed_by_section": removed_by_section,
            "generated_by_section": generated_by_section,
            "removed_examples": removed_examples,
        }
        changes: list[str] = []
        if generated_total:
            changes.append(f"generated {generated_total} default rule(s)")
        if removed_total:
            changes.append(f"removed {removed_total} stale rule(s)")
        if canonicalized_total:
            changes.append(f"normalized {canonicalized_total} target name(s)")

        if not changed:
            result["detail"] = "Tag rule targets already matched taxonomy."
        else:
            result["detail"] = (
                "Tag rules aligned to taxonomy."
                if not changes
                else "; ".join(changes).capitalize() + "."
            )
        return result

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
        rule_sync = None
        if any(name in {"categories", "tags", "tools"} for name in include_files):
            rule_sync = self.sync_tag_rules_targets()
        return {
            "source": source,
            "mode": mode,
            "files": include_files,
            "changes": changed,
            "rule_sync": rule_sync,
        }
