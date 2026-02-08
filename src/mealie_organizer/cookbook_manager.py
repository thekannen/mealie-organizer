from __future__ import annotations

import argparse
from pathlib import Path

import json
import re
import requests

from .config import REPO_ROOT, env_or_config, require_mealie_url, resolve_repo_path, secret, to_bool

DEFAULT_COOKBOOKS_FILE = env_or_config("COOKBOOKS_FILE", "taxonomy.cookbooks_file", "configs/taxonomy/cookbooks.json")


def require_str(value: object, field: str) -> str:
    if isinstance(value, str):
        return value
    raise ValueError(f"Invalid value for '{field}': expected string, got {type(value).__name__}")


def require_bool(value: object, field: str) -> bool:
    try:
        return bool(to_bool(value))
    except Exception as exc:
        raise ValueError(f"Invalid value for '{field}': expected boolean-like, got {value!r}") from exc


def require_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value.strip())
    raise ValueError(f"Invalid value for '{field}': expected integer-like, got {type(value).__name__}")


def normalize_query_filter_string(value: str) -> str:
    normalized = re.sub(r"\bCONTAINS[_ ]ANY\b", "IN", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", normalized).strip()


class MealieCookbookManager:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30, dry_run: bool = False):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.dry_run = dry_run
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    def get_cookbooks(self) -> list[dict]:
        response = self.session.get(f"{self.base_url}/households/cookbooks", timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            items = data.get("items", data.get("data", []))
            if isinstance(items, list):
                return items
            return []
        if isinstance(data, list):
            return data
        return []

    def create_cookbook(self, payload: dict) -> bool:
        if self.dry_run:
            print(f"[plan] Create cookbook: {payload.get('name')}")
            return True

        response = self.session.post(f"{self.base_url}/households/cookbooks", json=payload, timeout=self.timeout)
        if response.status_code in (200, 201):
            print(f"[ok] Created cookbook: {payload.get('name')}")
            return True

        print(f"[error] Create failed for '{payload.get('name')}': {response.status_code} {response.text}")
        return False

    def update_cookbook(self, cookbook_id: str, payload: dict) -> bool:
        if self.dry_run:
            print(f"[plan] Update cookbook: {payload.get('name')}")
            return True

        response = self.session.put(
            f"{self.base_url}/households/cookbooks/{cookbook_id}",
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code in (200, 201):
            print(f"[ok] Updated cookbook: {payload.get('name')}")
            return True

        print(f"[error] Update failed for '{payload.get('name')}': {response.status_code} {response.text}")
        return False

    def delete_cookbook(self, cookbook_id: str, name: str) -> bool:
        if self.dry_run:
            print(f"[plan] Delete cookbook: {name}")
            return True

        response = self.session.delete(f"{self.base_url}/households/cookbooks/{cookbook_id}", timeout=self.timeout)
        if response.status_code in (200, 204):
            print(f"[ok] Deleted cookbook: {name}")
            return True

        print(f"[error] Delete failed for '{name}': {response.status_code} {response.text}")
        return False

    def get_items(self, endpoint: str) -> list[dict]:
        response = self.session.get(f"{self.base_url}/organizers/{endpoint}?perPage=1000", timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            items = data.get("items", data.get("data", []))
            return items if isinstance(items, list) else []
        if isinstance(data, list):
            return data
        return []

    def build_name_id_maps(self) -> tuple[dict[str, str], dict[str, str]]:
        categories = self.get_items("categories")
        tags = self.get_items("tags")

        category_ids_by_name = {
            str(item.get("name", "")).strip().lower(): str(item.get("id"))
            for item in categories
            if item.get("name") and item.get("id")
        }
        tag_ids_by_name = {
            str(item.get("name", "")).strip().lower(): str(item.get("id"))
            for item in tags
            if item.get("name") and item.get("id")
        }
        return category_ids_by_name, tag_ids_by_name

    @staticmethod
    def parse_filter_values(raw_values: str) -> list[str] | None:
        try:
            parsed = json.loads(f"[{raw_values}]")
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed, list):
            return None

        values: list[str] = []
        for value in parsed:
            text = str(value).strip()
            if text:
                values.append(text)
        return values

    def replace_name_filter_with_ids(
        self,
        query_filter: str,
        pattern: str,
        target_attribute: str,
        id_lookup: dict[str, str],
        entity_name: str,
    ) -> str:
        def _repl(match: re.Match[str]) -> str:
            operator = " ".join(match.group("op").upper().split())
            raw_values = match.group("vals")
            names = self.parse_filter_values(raw_values)
            if names is None:
                print(f"[warn] Could not parse {entity_name} name list in query filter: {match.group(0)}")
                return match.group(0)

            ids: list[str] = []
            missing: list[str] = []
            for name in names:
                found_id = id_lookup.get(name.strip().lower())
                if found_id:
                    ids.append(found_id)
                else:
                    missing.append(name)

            if missing or not ids:
                print(
                    f"[warn] Could not resolve {entity_name} names in query filter: "
                    f"{', '.join(missing or names)}; keeping original filter."
                )
                return match.group(0)

            id_list = ",".join(f'"{value}"' for value in ids)
            return f"{target_attribute} {operator} [{id_list}]"

        return re.sub(pattern, _repl, query_filter, flags=re.IGNORECASE)

    def compile_query_filter_for_editor(
        self,
        query_filter: str,
        category_ids_by_name: dict[str, str],
        tag_ids_by_name: dict[str, str],
    ) -> str:
        compiled = normalize_query_filter_string(query_filter)
        compiled = self.replace_name_filter_with_ids(
            compiled,
            r"\b(?:recipe_category|recipeCategory)\.name\s+(?P<op>IN|CONTAINS\s+ALL)\s*\[(?P<vals>[^\]]*)\]",
            "recipe_category.id",
            category_ids_by_name,
            "category",
        )
        compiled = self.replace_name_filter_with_ids(
            compiled,
            r"\btags\.name\s+(?P<op>IN|CONTAINS\s+ALL)\s*\[(?P<vals>[^\]]*)\]",
            "tags.id",
            tag_ids_by_name,
            "tag",
        )
        compiled = re.sub(r"\brecipeCategory\.id\b", "recipe_category.id", compiled, flags=re.IGNORECASE)
        return normalize_query_filter_string(compiled)

    def prepare_cookbook_payload(
        self,
        item: dict,
        category_ids_by_name: dict[str, str],
        tag_ids_by_name: dict[str, str],
    ) -> dict:
        payload = dict(item)
        query_filter = str(payload.get("queryFilterString", ""))
        payload["queryFilterString"] = self.compile_query_filter_for_editor(
            query_filter,
            category_ids_by_name,
            tag_ids_by_name,
        )
        return payload

    @staticmethod
    def has_changes(existing: dict, desired: dict) -> bool:
        return (
            (existing.get("name") or "") != desired.get("name")
            or (existing.get("description") or "") != desired.get("description")
            or bool(existing.get("public", False)) != bool(desired.get("public", False))
            or int(existing.get("position") or 0) != int(desired.get("position") or 0)
            or (existing.get("queryFilterString") or "") != desired.get("queryFilterString")
        )

    def sync_cookbooks(self, desired: list[dict], replace: bool = False) -> tuple[int, int, int, int, int]:
        category_ids_by_name: dict[str, str] = {}
        tag_ids_by_name: dict[str, str] = {}
        try:
            category_ids_by_name, tag_ids_by_name = self.build_name_id_maps()
        except Exception as exc:
            print(f"[warn] Could not build organizer id maps for cookbook filters: {exc}")

        prepared_desired = [
            self.prepare_cookbook_payload(item, category_ids_by_name, tag_ids_by_name)
            for item in desired
        ]

        existing = self.get_cookbooks()
        existing_by_name = {
            str(cb.get("name", "")).strip().lower(): cb for cb in existing if str(cb.get("name", "")).strip()
        }

        created = 0
        updated = 0
        deleted = 0
        skipped = 0
        failed = 0

        for item in prepared_desired:
            name = item["name"]
            key = name.strip().lower()
            match = existing_by_name.get(key)

            if not match:
                if self.create_cookbook(item):
                    created += 1
                else:
                    failed += 1
                continue

            if self.has_changes(match, item):
                cookbook_id = match.get("id")
                if not cookbook_id:
                    print(f"[warn] Missing id for existing cookbook '{name}', skipping update.")
                    failed += 1
                    continue
                update_payload = dict(item)
                update_payload["id"] = str(cookbook_id)
                if match.get("groupId"):
                    update_payload["groupId"] = str(match.get("groupId"))
                if match.get("householdId"):
                    update_payload["householdId"] = str(match.get("householdId"))

                if self.update_cookbook(str(cookbook_id), update_payload):
                    updated += 1
                else:
                    failed += 1
            else:
                skipped += 1
                print(f"[skip] Cookbook unchanged: {name}")

        if replace:
            desired_names = {item["name"].strip().lower() for item in prepared_desired}
            for key, cb in existing_by_name.items():
                if key in desired_names:
                    continue
                cookbook_id = cb.get("id")
                name = cb.get("name", "(unnamed)")
                if not cookbook_id:
                    print(f"[warn] Missing id for existing cookbook '{name}', skipping delete.")
                    failed += 1
                    continue
                if self.delete_cookbook(str(cookbook_id), str(name)):
                    deleted += 1
                else:
                    failed += 1

        return created, updated, deleted, skipped, failed


def normalize_cookbook_items(raw_data: object) -> list[dict]:
    if not isinstance(raw_data, list):
        raise ValueError("Cookbook file must be a JSON array.")

    normalized: list[dict] = []
    for idx, entry in enumerate(raw_data, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Cookbook #{idx} must be an object.")

        name = require_str(entry.get("name", ""), f"cookbooks[{idx}].name").strip()
        if not name:
            raise ValueError(f"Cookbook #{idx} must include a non-empty 'name'.")

        description = require_str(entry.get("description", ""), f"cookbooks[{idx}].description")
        query_filter = normalize_query_filter_string(
            require_str(entry.get("queryFilterString", ""), f"cookbooks[{idx}].queryFilterString")
        )
        public = require_bool(entry.get("public", False), f"cookbooks[{idx}].public")
        position = require_int(entry.get("position", idx), f"cookbooks[{idx}].position")

        normalized.append(
            {
                "name": name,
                "description": description,
                "queryFilterString": query_filter,
                "public": public,
                "position": position,
            }
        )

    return normalized


def load_cookbook_items(path_value: str) -> tuple[Path, list[dict]]:
    path = resolve_repo_path(path_value)
    if not path.exists():
        raise FileNotFoundError(f"Cookbook JSON file not found: {path}")

    raw_data = json.loads(path.read_text(encoding="utf-8"))
    items = normalize_cookbook_items(raw_data)
    return path, items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mealie cookbook manager.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="Create/update cookbooks from JSON file.")
    sync_parser.add_argument(
        "--file",
        default=DEFAULT_COOKBOOKS_FILE,
        help="Path to cookbooks JSON file.",
    )
    sync_parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete cookbooks not present in the JSON file.",
    )

    return parser


def main() -> None:
    args = build_parser().parse_args()

    mealie_url = require_mealie_url(env_or_config("MEALIE_URL", "mealie.url", "http://your.server.ip.address:9000/api"))
    mealie_api_key = secret("MEALIE_API_KEY")
    if not mealie_api_key:
        raise RuntimeError("MEALIE_API_KEY is empty. Set it in .env or the environment.")

    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    if dry_run:
        print("[start] runtime.dry_run=true (cookbook writes are planned only).")

    manager = MealieCookbookManager(mealie_url, mealie_api_key, timeout=args.timeout, dry_run=dry_run)

    if args.command == "sync":
        file_path, items = load_cookbook_items(args.file)
        print(f"[start] Syncing {len(items)} cookbook(s) from {file_path.relative_to(REPO_ROOT)}")
        created, updated, deleted, skipped, failed = manager.sync_cookbooks(items, replace=args.replace)
        print(f"[done] cookbooks created={created} updated={updated} deleted={deleted} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
