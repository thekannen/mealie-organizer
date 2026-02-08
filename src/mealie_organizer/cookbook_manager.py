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
        existing = self.get_cookbooks()
        existing_by_name = {
            str(cb.get("name", "")).strip().lower(): cb for cb in existing if str(cb.get("name", "")).strip()
        }

        created = 0
        updated = 0
        deleted = 0
        skipped = 0
        failed = 0

        for item in desired:
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
                if self.update_cookbook(str(cookbook_id), item):
                    updated += 1
                else:
                    failed += 1
            else:
                skipped += 1
                print(f"[skip] Cookbook unchanged: {name}")

        if replace:
            desired_names = {item["name"].strip().lower() for item in desired}
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
