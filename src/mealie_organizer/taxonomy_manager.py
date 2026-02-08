import argparse
import json
import re
from pathlib import Path

import requests

from .config import REPO_ROOT, env_or_config, require_mealie_url, secret, resolve_repo_path, to_bool

DEFAULT_CATEGORIES_FILE = env_or_config(
    "TAXONOMY_CATEGORIES_FILE", "taxonomy.categories_file", "configs/taxonomy/categories.json"
)
DEFAULT_TAGS_FILE = env_or_config("TAXONOMY_TAGS_FILE", "taxonomy.tags_file", "configs/taxonomy/tags.json")


class MealieTaxonomyManager:
    def __init__(self, base_url, api_key, timeout=60, dry_run=False):
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

    def get_items(self, endpoint):
        response = self.session.get(
            f"{self.base_url}/organizers/{endpoint}?perPage=1000",
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("items", data)

    def get_recipes(self):
        response = self.session.get(f"{self.base_url}/recipes?perPage=999", timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        return data.get("items", data)

    def existing_lookup(self, endpoint):
        items = self.get_items(endpoint)
        return {
            str(item.get("name", "")).strip().lower(): item
            for item in items
            if item.get("name")
        }

    def delete_all(self, endpoint):
        existing = self.existing_lookup(endpoint)
        if not existing:
            print(f"[ok] No existing {endpoint} to delete.")
            return

        mode = "DRY-RUN" if self.dry_run else "APPLY"
        print(f"[start] Delete mode ({endpoint}): {mode}")
        print(f"[start] Deleting {len(existing)} existing {endpoint}...")
        for item in existing.values():
            item_id = item.get("id")
            name = item.get("name")
            if not item_id:
                print(f"  [warn] Skipping '{name}' (missing id)")
                continue

            if self.dry_run:
                print(f"  [plan] Delete: {name}")
                continue

            response = self.session.delete(
                f"{self.base_url}/organizers/{endpoint}/{item_id}",
                timeout=self.timeout,
            )
            if response.status_code == 200:
                print(f"  [ok] Deleted: {name}")
            else:
                print(f"  [warn] Failed delete: {name} ({response.status_code})")

    def import_items(self, endpoint, items, replace=False):
        if replace:
            self.delete_all(endpoint)

        if replace and self.dry_run:
            # Simulate empty endpoint after planned deletes so output reflects what apply mode would do.
            existing = {}
        else:
            existing = self.existing_lookup(endpoint)

        created = 0
        skipped = 0
        failed = 0

        for payload in items:
            name = payload["name"]
            key = name.strip().lower()
            if key in existing:
                skipped += 1
                print(f"[skip] Exists: {name}")
                continue

            if self.dry_run:
                created += 1
                existing[key] = {"name": name}
                print(f"[plan] Add: {name}")
                continue

            response = self.session.post(
                f"{self.base_url}/organizers/{endpoint}",
                json=payload,
                timeout=self.timeout,
            )
            if response.status_code in (200, 201):
                created += 1
                existing[key] = {"name": name}
                print(f"[ok] Added: {name}")
            elif response.status_code == 409:
                skipped += 1
                print(f"[skip] Conflict/exists: {name}")
            else:
                failed += 1
                print(f"[error] Failed: {name} -> {response.status_code} {response.text}")

        print(f"[done] endpoint={endpoint} created={created} skipped={skipped} failed={failed}")

    def cleanup_tags(self, apply=False, max_length=24, min_usage=1, delete_noisy=False, only_unused=False):
        recipes = self.get_recipes()
        tags = self.get_items("tags")

        usage = {(tag.get("name") or ""): 0 for tag in tags if tag.get("name")}
        tag_by_name = {(tag.get("name") or ""): tag for tag in tags if tag.get("name")}

        for recipe in recipes:
            for tag in recipe.get("tags") or []:
                name = tag.get("name")
                if name in usage:
                    usage[name] += 1

        candidates = []
        for name, count in sorted(usage.items(), key=lambda item: (item[1], item[0])):
            if only_unused and count != 0:
                continue

            is_low_usage = count < min_usage
            is_long = len(name) >= max_length
            is_noisy = delete_noisy and self.noisy_tag(name)

            if is_low_usage or is_long or is_noisy:
                tag = tag_by_name.get(name)
                if tag and tag.get("id"):
                    candidates.append({"id": tag["id"], "name": name, "usage": count})

        effective_apply = apply and not self.dry_run
        mode = "APPLY" if effective_apply else "DRY-RUN"
        print(f"[start] Tag cleanup mode: {mode}")
        if apply and self.dry_run:
            print("[info] runtime.dry_run=true, so cleanup deletes are planned only.")
        print(f"[start] Candidate tags: {len(candidates)}")

        if not candidates:
            print("[done] No tags matched cleanup criteria.")
            return

        for item in candidates:
            if effective_apply:
                response = self.session.delete(
                    f"{self.base_url}/organizers/tags/{item['id']}",
                    timeout=self.timeout,
                )
                if response.status_code == 200:
                    print(f"[ok] Deleted '{item['name']}' (usage={item['usage']})")
                else:
                    print(
                        f"[warn] Failed delete '{item['name']}' "
                        f"(usage={item['usage']}): {response.status_code}"
                    )
            else:
                print(f"[plan] Delete '{item['name']}' (usage={item['usage']})")

        print("[done] Tag cleanup complete.")

    @staticmethod
    def noisy_tag(name):
        patterns = [
            r"\brecipe\b",
            r"\bhow to make\b",
            r"\bfrom scratch\b",
            r"\bwithout drippings\b",
            r"\bfrom drippings\b",
        ]
        return any(re.search(pattern, name.lower()) for pattern in patterns)


def resolve_input_path(path_value):
    file_path = resolve_repo_path(path_value)
    if not file_path.exists():
        raise FileNotFoundError(f"Input JSON file not found: {file_path}")
    return file_path


def normalize_payload_items(raw_data):
    if not isinstance(raw_data, list):
        raise ValueError("JSON file must contain an array.")

    items = []
    for idx, entry in enumerate(raw_data, start=1):
        if isinstance(entry, str):
            name = entry.strip()
            if name:
                items.append({"name": name})
            continue

        if isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            if not name:
                raise ValueError(f"Item #{idx} is missing a non-empty 'name'.")
            payload = {"name": name}
            if "groupId" in entry:
                payload["groupId"] = entry["groupId"]
            items.append(payload)
            continue

        raise ValueError(f"Item #{idx} must be a string or object.")

    return items


def load_json_items(file_value):
    file_path = resolve_input_path(file_value)
    raw_data = json.loads(file_path.read_text(encoding="utf-8"))
    items = normalize_payload_items(raw_data)
    if not items:
        raise ValueError("No valid items found in input file.")
    return file_path, items


def build_parser():
    parser = argparse.ArgumentParser(description="Mealie taxonomy manager.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    reset_parser = subparsers.add_parser("reset", help="Reset and seed categories/tags.")
    reset_parser.add_argument("--categories-file", default=DEFAULT_CATEGORIES_FILE, help="Category JSON input file.")
    reset_parser.add_argument("--tags-file", default="", help="Tag JSON input file (optional).")
    reset_parser.add_argument("--skip-tags", action="store_true", help="Only reset categories, skip tags.")

    import_parser = subparsers.add_parser("import", help="Import categories or tags from JSON.")
    import_parser.add_argument(
        "--file",
        default=DEFAULT_CATEGORIES_FILE,
        help="Path to JSON file containing names or organizer objects.",
    )
    import_parser.add_argument(
        "--endpoint",
        choices=["categories", "tags"],
        default="categories",
        help="Organizer endpoint to import into.",
    )
    import_parser.add_argument("--replace", action="store_true", help="Delete all existing items first.")

    cleanup_parser = subparsers.add_parser("cleanup", help="Cleanup low-value tags.")
    cleanup_parser.add_argument("--apply", action="store_true", help="Apply deletions.")
    cleanup_parser.add_argument(
        "--max-length",
        type=int,
        default=env_or_config("CLEANUP_MAX_LENGTH", "taxonomy.cleanup.max_length", 24, int),
    )
    cleanup_parser.add_argument(
        "--min-usage",
        type=int,
        default=env_or_config("CLEANUP_MIN_USAGE", "taxonomy.cleanup.min_usage", 1, int),
    )
    cleanup_parser.add_argument("--delete-noisy", action="store_true")
    cleanup_parser.add_argument("--only-unused", action="store_true")

    refresh_parser = subparsers.add_parser(
        "refresh",
        help="Streamlined taxonomy lifecycle: reset/import + optional cleanup.",
    )
    refresh_parser.add_argument("--categories-file", default=DEFAULT_CATEGORIES_FILE, help="Category JSON input file.")
    refresh_parser.add_argument("--tags-file", default=DEFAULT_TAGS_FILE, help="Tag JSON input file (optional).")
    refresh_parser.add_argument(
        "--mode",
        choices=["merge", "replace"],
        default=env_or_config("TAXONOMY_REFRESH_MODE", "taxonomy.refresh.mode", "merge"),
        help="Refresh mode: 'merge' keeps existing taxonomy and adds missing items; 'replace' deletes existing items first.",
    )
    refresh_parser.add_argument(
        "--replace-categories",
        action="store_true",
        help="Delete existing categories before importing categories file.",
    )
    refresh_parser.add_argument(
        "--replace-tags",
        action="store_true",
        help="Delete existing tags before importing tags file.",
    )
    refresh_parser.add_argument("--cleanup", action="store_true", help="Run tag cleanup after import.")
    refresh_parser.add_argument("--cleanup-apply", action="store_true", help="Apply cleanup deletes.")
    refresh_parser.add_argument("--cleanup-max-length", type=int, default=24)
    refresh_parser.add_argument("--cleanup-min-usage", type=int, default=1)
    refresh_parser.add_argument("--cleanup-delete-noisy", action="store_true")
    refresh_parser.add_argument("--cleanup-only-unused", action="store_true")

    return parser


def resolve_refresh_replace_flags(mode, replace_categories, replace_tags):
    normalized = str(mode or "merge").strip().lower()
    if normalized == "replace":
        return True, True
    return bool(replace_categories), bool(replace_tags)


def main():
    args = build_parser().parse_args()

    mealie_url = require_mealie_url(env_or_config("MEALIE_URL", "mealie.url", "http://your.server.ip.address:9000/api"))
    mealie_api_key = secret("MEALIE_API_KEY")
    if not mealie_api_key:
        raise RuntimeError("MEALIE_API_KEY is empty. Set it in .env or the environment.")

    dry_run = env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool)
    if dry_run:
        print("[start] runtime.dry_run=true (no write operations will be sent to Mealie).")

    manager = MealieTaxonomyManager(mealie_url, mealie_api_key, timeout=args.timeout, dry_run=dry_run)

    if args.command == "import":
        file_path, items = load_json_items(args.file)
        print(f"[start] Importing {len(items)} item(s) into {args.endpoint} from {file_path.relative_to(REPO_ROOT)}")
        manager.import_items(args.endpoint, items, replace=args.replace)
        return

    if args.command == "cleanup":
        manager.cleanup_tags(
            apply=args.apply,
            max_length=args.max_length,
            min_usage=args.min_usage,
            delete_noisy=args.delete_noisy,
            only_unused=args.only_unused,
        )
        return

    if args.command == "reset":
        categories_file, categories = load_json_items(args.categories_file)
        print(f"[start] Reset categories using {categories_file.relative_to(REPO_ROOT)}")
        manager.import_items("categories", categories, replace=True)

        if args.skip_tags:
            print("[done] Categories reset complete (tags skipped).")
            return

        if args.tags_file:
            tags_file, tags = load_json_items(args.tags_file)
            print(f"[start] Reset tags using {tags_file.relative_to(REPO_ROOT)}")
            manager.import_items("tags", tags, replace=True)
        else:
            print("[warn] --tags-file not provided; tags were not reset.")

        print("[done] Reset complete.")
        return

    if args.command == "refresh":
        replace_categories, replace_tags = resolve_refresh_replace_flags(
            args.mode,
            args.replace_categories,
            args.replace_tags,
        )
        print(f"[start] Refresh mode: {args.mode}")

        categories_file, categories = load_json_items(args.categories_file)
        print(f"[start] Import categories from {categories_file.relative_to(REPO_ROOT)}")
        manager.import_items("categories", categories, replace=replace_categories)

        if args.tags_file:
            tags_file, tags = load_json_items(args.tags_file)
            print(f"[start] Import tags from {tags_file.relative_to(REPO_ROOT)}")
            manager.import_items("tags", tags, replace=replace_tags)
        else:
            print("[warn] No --tags-file provided; skipping tag import.")

        if args.cleanup:
            manager.cleanup_tags(
                apply=args.cleanup_apply,
                max_length=args.cleanup_max_length,
                min_usage=args.cleanup_min_usage,
                delete_noisy=args.cleanup_delete_noisy,
                only_unused=args.cleanup_only_unused,
            )

        print("[done] Refresh complete.")


if __name__ == "__main__":
    main()
