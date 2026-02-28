from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
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
WORKSPACE_DRAFT_RELATIVE_PATH = "configs/.drafts/taxonomy-workspace.json"
WORKSPACE_RESOURCE_NAMES: tuple[str, ...] = TAXONOMY_FILE_NAMES
WORKSPACE_CLAUSE_FIELD_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("categories", re.compile(r"^\s*(?:recipe_?[Cc]ategory|recipeCategory)\.name\s+", re.IGNORECASE), "recipeCategory.name"),
    ("tags", re.compile(r"^\s*tags\.name\s+", re.IGNORECASE), "tags.name"),
    ("tools", re.compile(r"^\s*tools\.name\s+", re.IGNORECASE), "tools.name"),
    (
        "foods",
        re.compile(r"^\s*(?:recipe_?[Ii]ngredient|recipeIngredient)\.food\.name\s+", re.IGNORECASE),
        "recipeIngredient.food.name",
    ),
)
WORKSPACE_FILTER_OPERATORS: tuple[str, ...] = ("IN", "NOT IN", "CONTAINS ALL")


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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _build_workspace_version(draft: dict[str, list[dict[str, Any]]], updated_at: str) -> str:
    digest = hashlib.sha256(_stable_json_dumps(draft).encode("utf-8")).hexdigest()[:16]
    return f"{digest}:{updated_at}"


def _normalize_workspace_draft(raw: Any) -> dict[str, list[dict[str, Any]]]:
    source = raw if isinstance(raw, dict) else {}
    normalized: dict[str, list[dict[str, Any]]] = {}
    for resource_name in WORKSPACE_RESOURCE_NAMES:
        normalized[resource_name] = _normalize_payload(resource_name, source.get(resource_name, []))
    return normalized


def _normalize_workspace_meta(raw: Any, now_iso: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    created_at = str(raw.get("created_at") or now_iso)
    updated_at = str(raw.get("updated_at") or now_iso)
    meta: dict[str, Any] = {
        "created_at": created_at,
        "updated_at": updated_at,
        "last_published_at": raw.get("last_published_at"),
        "last_published_by": raw.get("last_published_by"),
        "last_validation": raw.get("last_validation") if isinstance(raw.get("last_validation"), dict) else None,
    }
    return meta


def _parse_filter_value_list(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(f"[{text}]")
        if isinstance(parsed, list):
            out: list[str] = []
            for item in parsed:
                if not isinstance(item, str):
                    continue
                value = _normalize_name(item)
                if value:
                    out.append(value)
            return out
    except Exception:
        pass
    values: list[str] = []
    for part in text.split(","):
        value = _normalize_name(part.strip().strip("\"'"))
        if value:
            values.append(value)
    return values


def _normalize_filter_operator(raw: str) -> str:
    upper = _normalize_name(raw).upper()
    if upper in WORKSPACE_FILTER_OPERATORS:
        return upper
    return ""


def _resource_key(item: dict[str, Any], index: int) -> str:
    name = _normalize_name(item.get("name"))
    if name:
        return _name_key(name)
    return f"index:{index}"


class WorkspaceVersionConflictError(ValueError):
    def __init__(self, *, expected: str, actual: str) -> None:
        super().__init__("Workspace draft version mismatch.")
        self.expected = expected
        self.actual = actual


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

        Rules are now derived at runtime by the rule tagger, so this method
        only operates on an existing tag_rules.json if the user has one
        (e.g. custom overrides).  When the file doesn't exist it returns a
        no-op result — the runtime deriver handles everything automatically.
        """
        rules_path = (self.repo_root / TAG_RULES_RELATIVE_PATH).resolve()
        if not rules_path.exists():
            return {
                "file": TAG_RULES_RELATIVE_PATH,
                "updated": False,
                "created": False,
                "removed_total": 0,
                "generated_total": 0,
                "canonicalized_total": 0,
                "kept_total": 0,
                "removed_by_section": {},
                "generated_by_section": {},
                "removed_examples": {},
                "detail": "No tag_rules.json — rules are derived at runtime from taxonomy.",
            }

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

        try:
            existing_payload = json.loads(rules_path.read_text(encoding="utf-8"))
        except Exception:
            existing_payload = _empty_rule_payload()

        normalized = _normalize_rules_payload(existing_payload)
        synced = _empty_rule_payload()

        removed_by_section: dict[str, int] = {}
        canonicalized_total = 0
        removed_examples: dict[str, list[str]] = {}

        for section, target_field in RULE_TARGET_FIELDS.items():
            allowed = allowed_by_field[target_field]
            removed_count = 0
            removed_names: list[str] = []
            kept: list[dict[str, Any]] = []

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

            if removed_count:
                removed_by_section[section] = removed_count
                if removed_names:
                    removed_examples[section] = sorted(set(removed_names))[:8]
            synced[section] = kept

        changed = synced != normalized
        if changed:
            rules_path.write_text(json.dumps(synced, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

        removed_total = sum(removed_by_section.values())
        kept_total = sum(len(synced.get(section, [])) for section in RULE_TARGET_FIELDS)
        result: dict[str, Any] = {
            "file": TAG_RULES_RELATIVE_PATH,
            "updated": changed,
            "created": False,
            "removed_total": removed_total,
            "generated_total": 0,
            "canonicalized_total": canonicalized_total,
            "kept_total": kept_total,
            "removed_by_section": removed_by_section,
            "generated_by_section": {},
            "removed_examples": removed_examples,
        }
        changes: list[str] = []
        if removed_total:
            changes.append(f"removed {removed_total} stale rule(s)")
        if canonicalized_total:
            changes.append(f"normalized {canonicalized_total} target name(s)")

        if not changed:
            result["detail"] = "Tag rule targets already matched taxonomy."
        else:
            result["detail"] = (
                "User rule overrides aligned to taxonomy."
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


class TaxonomyWorkspaceDraftService:
    def __init__(self, *, repo_root: Path, config_files: ConfigFilesManager) -> None:
        self.repo_root = repo_root
        self.config_files = config_files
        self.workspace = TaxonomyWorkspaceService(repo_root=repo_root, config_files=config_files)

    @property
    def draft_path(self) -> Path:
        return (self.repo_root / WORKSPACE_DRAFT_RELATIVE_PATH).resolve()

    def get_draft(self) -> dict[str, Any]:
        state = self._load_state()
        return self._build_snapshot(state)

    def update_draft(
        self,
        *,
        expected_version: str,
        draft_patch: dict[str, Any],
        replace: bool = False,
    ) -> dict[str, Any]:
        state = self._load_state()
        snapshot = self._build_snapshot(state)
        self._require_version(expected=expected_version, actual=snapshot["version"])

        if not isinstance(draft_patch, dict):
            raise ValueError("draft must be an object keyed by taxonomy resource.")

        if replace:
            next_draft = self._coerce_patch(draft_patch, allow_missing=True)
        else:
            next_draft = {name: [dict(item) for item in state["draft"].get(name, [])] for name in WORKSPACE_RESOURCE_NAMES}
            patch = self._coerce_patch(draft_patch, allow_missing=False)
            for resource_name, items in patch.items():
                next_draft[resource_name] = items

        now_iso = _utc_now_iso()
        state["draft"] = next_draft
        state["meta"]["updated_at"] = now_iso
        state["meta"]["last_validation"] = None
        self._write_state(state)
        return self._build_snapshot(state)

    def validate_draft(self, *, expected_version: str) -> dict[str, Any]:
        state = self._load_state()
        snapshot = self._build_snapshot(state)
        self._require_version(expected=expected_version, actual=snapshot["version"])

        errors, warnings = self._validate_draft(snapshot["draft"])
        can_publish = len(errors) == 0
        validated_at = _utc_now_iso()
        result = {
            "version": snapshot["version"],
            "validated_at": validated_at,
            "can_publish": can_publish,
            "errors": errors,
            "warnings": warnings,
            "summary": {"blocking_errors": len(errors), "warnings": len(warnings)},
        }
        state["meta"]["last_validation"] = {
            "version": snapshot["version"],
            "validated_at": validated_at,
            "can_publish": can_publish,
            "blocking_errors": len(errors),
            "warnings": len(warnings),
        }
        self._write_state(state)
        return result

    def publish_draft(self, *, expected_version: str, published_by: str | None = None) -> dict[str, Any]:
        state = self._load_state()
        snapshot = self._build_snapshot(state)
        self._require_version(expected=expected_version, actual=snapshot["version"])

        validation = state["meta"].get("last_validation") or {}
        if validation.get("version") != snapshot["version"]:
            raise ValueError("Run validation for the current draft version before publishing.")
        if not validation.get("can_publish"):
            raise ValueError("Validation contains blocking errors. Resolve them before publishing.")

        managed = snapshot["managed"]
        draft = snapshot["draft"]
        file_diffs: dict[str, dict[str, Any]] = {}
        changed_resources: list[str] = []
        for resource_name in WORKSPACE_RESOURCE_NAMES:
            before_items = managed.get(resource_name, [])
            after_items = draft.get(resource_name, [])
            diff = self._resource_diff(before_items, after_items)
            file_diffs[resource_name] = diff
            if not diff["changed"]:
                continue
            self.config_files.write_file(resource_name, after_items)
            changed_resources.append(resource_name)

        rule_sync = None
        if any(name in {"categories", "tags", "tools"} for name in changed_resources):
            rule_sync = self.workspace.sync_tag_rules_targets()

        published_at = _utc_now_iso()
        state["meta"]["updated_at"] = published_at
        state["meta"]["last_published_at"] = published_at
        state["meta"]["last_published_by"] = _normalize_name(published_by)
        state["meta"]["last_validation"] = None
        self._write_state(state)

        result: dict[str, Any] = {
            "version": self._build_snapshot(state)["version"],
            "published_at": published_at,
            "published_by": state["meta"]["last_published_by"] or None,
            "files": file_diffs,
            "changed_resources": changed_resources,
            "rule_sync": rule_sync,
            "next_tasks": [
                {
                    "task_id": "taxonomy-refresh",
                    "label": "Open Tasks with taxonomy-refresh preselected",
                    "reason": "Push published taxonomy resources into Mealie.",
                },
                {
                    "task_id": "cookbook-sync",
                    "label": "Open Tasks with cookbook-sync preselected",
                    "reason": "Apply cookbook rule updates in Mealie.",
                },
            ],
        }
        return result

    def _coerce_patch(self, patch: dict[str, Any], *, allow_missing: bool) -> dict[str, list[dict[str, Any]]]:
        if not patch and not allow_missing:
            raise ValueError("At least one draft resource is required.")

        unknown = sorted(set(patch) - set(WORKSPACE_RESOURCE_NAMES))
        if unknown:
            names = ", ".join(unknown)
            raise ValueError(f"Unsupported draft resource(s): {names}.")

        out: dict[str, list[dict[str, Any]]] = {}
        target_names = WORKSPACE_RESOURCE_NAMES if allow_missing else tuple(patch.keys())
        for resource_name in target_names:
            raw = patch.get(resource_name, []) if allow_missing else patch[resource_name]
            if not isinstance(raw, list):
                raise ValueError(f"{resource_name} must be an array.")
            out[resource_name] = _normalize_payload(resource_name, raw)
        return out

    def _read_managed(self) -> dict[str, list[dict[str, Any]]]:
        payload: dict[str, list[dict[str, Any]]] = {}
        for resource_name in WORKSPACE_RESOURCE_NAMES:
            try:
                file_payload = self.config_files.read_file(resource_name)
            except FileNotFoundError:
                payload[resource_name] = []
                continue
            payload[resource_name] = _normalize_payload(resource_name, file_payload.get("content"))
        return payload

    def _initialize_state(self) -> dict[str, Any]:
        now_iso = _utc_now_iso()
        managed = self._read_managed()
        return {
            "draft": managed,
            "meta": _normalize_workspace_meta(
                {
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "last_published_at": None,
                    "last_published_by": None,
                    "last_validation": None,
                },
                now_iso,
            ),
        }

    def _load_state(self) -> dict[str, Any]:
        path = self.draft_path
        if not path.exists():
            state = self._initialize_state()
            self._write_state(state)
            return state

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            state = self._initialize_state()
            self._write_state(state)
            return state

        now_iso = _utc_now_iso()
        if isinstance(raw, dict) and "draft" in raw:
            draft_raw = raw.get("draft")
            meta_raw = raw.get("meta")
        else:
            draft_raw = raw if isinstance(raw, dict) else {}
            meta_raw = {}

        draft = _normalize_workspace_draft(draft_raw)
        meta = _normalize_workspace_meta(meta_raw, now_iso)
        state = {"draft": draft, "meta": meta}
        self._write_state(state)
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        path = self.draft_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "draft": _normalize_workspace_draft(state.get("draft")),
            "meta": _normalize_workspace_meta(state.get("meta"), _utc_now_iso()),
        }
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        tmp_path.replace(path)

    def _build_snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        draft = _normalize_workspace_draft(state.get("draft"))
        meta = _normalize_workspace_meta(state.get("meta"), _utc_now_iso())
        managed = self._read_managed()
        version = _build_workspace_version(draft, str(meta.get("updated_at")))

        draft_counts = {name: len(draft.get(name, [])) for name in WORKSPACE_RESOURCE_NAMES}
        managed_counts = {name: len(managed.get(name, [])) for name in WORKSPACE_RESOURCE_NAMES}
        changed_counts: dict[str, int] = {}
        for name in WORKSPACE_RESOURCE_NAMES:
            changed_counts[name] = self._resource_diff(managed.get(name, []), draft.get(name, []))["change_count"]

        return {
            "version": version,
            "draft": draft,
            "managed": managed,
            "meta": {
                **meta,
                "draft_counts": draft_counts,
                "managed_counts": managed_counts,
                "changed_counts": changed_counts,
            },
        }

    @staticmethod
    def _require_version(*, expected: str, actual: str) -> None:
        if str(expected or "").strip() != str(actual or "").strip():
            raise WorkspaceVersionConflictError(expected=str(expected or ""), actual=str(actual or ""))

    @staticmethod
    def _resource_diff(before_items: list[dict[str, Any]], after_items: list[dict[str, Any]]) -> dict[str, Any]:
        before_by_key = {_resource_key(item, idx): item for idx, item in enumerate(before_items)}
        after_by_key = {_resource_key(item, idx): item for idx, item in enumerate(after_items)}

        before_keys = set(before_by_key)
        after_keys = set(after_by_key)
        added_keys = sorted(after_keys - before_keys)
        removed_keys = sorted(before_keys - after_keys)
        shared_keys = before_keys & after_keys

        updated_keys: list[str] = []
        for key in sorted(shared_keys):
            if _stable_json_dumps(before_by_key[key]) != _stable_json_dumps(after_by_key[key]):
                updated_keys.append(key)

        change_count = len(added_keys) + len(removed_keys) + len(updated_keys)
        order_changed = [*before_by_key.keys()] != [*after_by_key.keys()]
        changed = change_count > 0 or order_changed

        def _label(item_map: dict[str, dict[str, Any]], key: str) -> str:
            item = item_map.get(key, {})
            return _normalize_name(item.get("name")) or key

        return {
            "changed": changed,
            "existing_count": len(before_items),
            "result_count": len(after_items),
            "added": len(added_keys),
            "removed": len(removed_keys),
            "updated": len(updated_keys),
            "change_count": change_count + (1 if order_changed else 0),
            "order_changed": order_changed,
            "samples": {
                "added": [_label(after_by_key, key) for key in added_keys[:8]],
                "removed": [_label(before_by_key, key) for key in removed_keys[:8]],
                "updated": [_label(after_by_key, key) for key in updated_keys[:8]],
            },
        }

    def _validate_draft(self, draft: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        for resource_name in WORKSPACE_RESOURCE_NAMES:
            items = draft.get(resource_name, [])
            if not items:
                warnings.append(
                    {
                        "code": "empty_resource",
                        "resource": resource_name,
                        "severity": "warning",
                        "path": resource_name,
                        "message": f"{resource_name} is empty.",
                    }
                )
                continue

            seen: dict[str, int] = {}
            for index, item in enumerate(items):
                name = _normalize_name(item.get("name"))
                if not name:
                    errors.append(
                        {
                            "code": "missing_name",
                            "resource": resource_name,
                            "severity": "error",
                            "path": f"{resource_name}[{index}].name",
                            "message": "Name is required.",
                        }
                    )
                    continue
                key = _name_key(name)
                first_seen = seen.get(key)
                if first_seen is not None:
                    errors.append(
                        {
                            "code": "duplicate_name",
                            "resource": resource_name,
                            "severity": "error",
                            "path": f"{resource_name}[{index}].name",
                            "message": f"Duplicate name '{name}' also appears at index {first_seen}.",
                        }
                    )
                    continue
                seen[key] = index

        self._validate_cookbooks(draft, errors, warnings)
        return errors, warnings

    def _validate_cookbooks(
        self,
        draft: dict[str, list[dict[str, Any]]],
        errors: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> None:
        cookbooks = draft.get("cookbooks", [])
        categories = {_name_key(item.get("name")) for item in draft.get("categories", [])}
        tags = {_name_key(item.get("name")) for item in draft.get("tags", [])}
        tools = {_name_key(item.get("name")) for item in draft.get("tools", [])}

        allowed_by_field = {
            "categories": categories,
            "tags": tags,
            "tools": tools,
        }

        for index, cookbook in enumerate(cookbooks):
            query = _normalize_name(cookbook.get("queryFilterString"))
            path_root = f"cookbooks[{index}]"
            if not query:
                warnings.append(
                    {
                        "code": "cookbook_empty_rules",
                        "resource": "cookbooks",
                        "severity": "warning",
                        "path": f"{path_root}.queryFilterString",
                        "message": f"Cookbook '{_normalize_name(cookbook.get('name')) or index}' has no query rules.",
                    }
                )
                continue

            clauses = [item.strip() for item in re.split(r"\s+AND\s+", query, flags=re.IGNORECASE) if item.strip()]
            if not clauses:
                errors.append(
                    {
                        "code": "cookbook_invalid_filter",
                        "resource": "cookbooks",
                        "severity": "error",
                        "path": f"{path_root}.queryFilterString",
                        "message": "Cookbook query filter is invalid.",
                    }
                )
                continue

            for clause_index, clause in enumerate(clauses):
                clause_path = f"{path_root}.queryFilterString[{clause_index}]"
                field_key: str | None = None
                field_match: re.Match[str] | None = None
                for candidate_key, pattern, _attr in WORKSPACE_CLAUSE_FIELD_PATTERNS:
                    match = pattern.match(clause)
                    if match:
                        field_key = candidate_key
                        field_match = match
                        break

                if field_key is None or field_match is None:
                    errors.append(
                        {
                            "code": "cookbook_invalid_field",
                            "resource": "cookbooks",
                            "severity": "error",
                            "path": clause_path,
                            "message": f"Unsupported query field in clause: '{clause}'.",
                        }
                    )
                    continue

                remainder = clause[field_match.end() :].strip()
                op_match = re.match(r"^(NOT\s+IN|CONTAINS\s+ALL|IN)\s*\[([^\]]*)\]\s*$", remainder, flags=re.IGNORECASE)
                if not op_match:
                    errors.append(
                        {
                            "code": "cookbook_invalid_operator",
                            "resource": "cookbooks",
                            "severity": "error",
                            "path": clause_path,
                            "message": f"Invalid operator or list syntax in clause: '{clause}'.",
                        }
                    )
                    continue

                operator = _normalize_filter_operator(op_match.group(1))
                if not operator:
                    errors.append(
                        {
                            "code": "cookbook_invalid_operator",
                            "resource": "cookbooks",
                            "severity": "error",
                            "path": clause_path,
                            "message": f"Unsupported operator '{op_match.group(1)}'.",
                        }
                    )
                    continue

                values = _parse_filter_value_list(op_match.group(2))
                if not values:
                    errors.append(
                        {
                            "code": "cookbook_empty_values",
                            "resource": "cookbooks",
                            "severity": "error",
                            "path": clause_path,
                            "message": "Filter clause must include at least one value.",
                        }
                    )
                    continue

                if field_key not in allowed_by_field:
                    continue

                allowed = allowed_by_field[field_key]
                unknown = sorted({value for value in values if _name_key(value) not in allowed})
                if unknown:
                    warnings.append(
                        {
                            "code": "cookbook_unknown_reference",
                            "resource": "cookbooks",
                            "severity": "warning",
                            "path": clause_path,
                            "message": f"Values not found in {field_key}: {', '.join(unknown[:8])}.",
                        }
                    )
