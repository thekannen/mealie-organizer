import argparse
import json
import os
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"


def load_env_file(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Import Mealie categories or tags from a JSON file."
    )
    parser.add_argument(
        "--file",
        default="scripts/python/mealie/categories.json",
        help="Path to JSON file containing names or organizer objects.",
    )
    parser.add_argument(
        "--endpoint",
        choices=["categories", "tags"],
        default="categories",
        help="Organizer endpoint to import into.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete all existing items in endpoint before importing.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds.",
    )
    return parser.parse_args()


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


def get_existing(base_url, endpoint, headers, timeout):
    response = requests.get(
        f"{base_url}/organizers/{endpoint}?perPage=1000",
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    existing = data.get("items", data)
    return {str(item.get("name", "")).strip().lower(): item for item in existing if item.get("name")}


def delete_existing(base_url, endpoint, headers, timeout):
    existing = get_existing(base_url, endpoint, headers, timeout)
    if not existing:
        print(f"[ok] No existing {endpoint} to delete.")
        return

    print(f"[start] Deleting {len(existing)} existing {endpoint}...")
    for item in existing.values():
        item_id = item.get("id")
        name = item.get("name")
        if not item_id:
            print(f"  [warn] Skipping '{name}' (missing id)")
            continue
        response = requests.delete(
            f"{base_url}/organizers/{endpoint}/{item_id}",
            headers=headers,
            timeout=timeout,
        )
        if response.status_code == 200:
            print(f"  [ok] Deleted: {name}")
        else:
            print(f"  [warn] Failed delete: {name} ({response.status_code})")


def import_items(base_url, endpoint, headers, timeout, items):
    existing = get_existing(base_url, endpoint, headers, timeout)
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

        response = requests.post(
            f"{base_url}/organizers/{endpoint}",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        if response.status_code in (200, 201):
            created += 1
            print(f"[ok] Added: {name}")
            existing[key] = {"name": name}
        elif response.status_code == 409:
            skipped += 1
            print(f"[skip] Conflict/exists: {name}")
        else:
            failed += 1
            print(f"[error] Failed: {name} -> {response.status_code} {response.text}")

    print(f"\n[done] endpoint={endpoint} created={created} skipped={skipped} failed={failed}")


def main():
    args = parse_args()
    load_env_file(ENV_FILE)

    mealie_url = os.environ.get("MEALIE_URL", "http://your.server.ip.address:9000/api")
    api_key = os.environ.get("MEALIE_API_KEY", "")

    if not api_key:
        raise RuntimeError("MEALIE_API_KEY is empty. Set it in .env or the environment.")

    file_path = Path(args.file)
    if not file_path.is_absolute():
        file_path = REPO_ROOT / file_path
    if not file_path.exists():
        raise FileNotFoundError(f"Input JSON file not found: {file_path}")

    raw_data = json.loads(file_path.read_text(encoding="utf-8"))
    items = normalize_payload_items(raw_data)
    if not items:
        print("[warn] No valid items found in input file.")
        return

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print(
        f"[start] Importing {len(items)} item(s) into {args.endpoint} "
        f"from {file_path.relative_to(REPO_ROOT)}"
    )

    if args.replace:
        delete_existing(mealie_url, args.endpoint, headers, args.timeout)

    import_items(mealie_url, args.endpoint, headers, args.timeout, items)


if __name__ == "__main__":
    main()
