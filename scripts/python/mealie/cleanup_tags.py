import argparse
import os
import re
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
    parser = argparse.ArgumentParser(description="Cleanup low-value Mealie tags.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete tags. Without this, runs in dry-run mode.",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=24,
        help="Treat tags this long or longer as long-name tags.",
    )
    parser.add_argument(
        "--min-usage",
        type=int,
        default=1,
        help="Delete tags used fewer times than this threshold.",
    )
    parser.add_argument(
        "--delete-noisy",
        action="store_true",
        help="Include recipe-title/noisy tags in delete candidates.",
    )
    parser.add_argument(
        "--only-unused",
        action="store_true",
        help="Only delete tags with zero usage.",
    )
    return parser.parse_args()


def get_items(session, url):
    response = session.get(url, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data.get("items", data)


def noisy_tag(name):
    patterns = [
        r"\brecipe\b",
        r"\bhow to make\b",
        r"\bfrom scratch\b",
        r"\bwithout drippings\b",
        r"\bfrom drippings\b",
    ]
    return any(re.search(pattern, name.lower()) for pattern in patterns)


def main():
    args = parse_args()
    load_env_file(ENV_FILE)

    mealie_url = os.environ.get("MEALIE_URL", "").rstrip("/")
    mealie_api_key = os.environ.get("MEALIE_API_KEY", "")
    if not mealie_url or not mealie_api_key:
        raise RuntimeError("MEALIE_URL and MEALIE_API_KEY are required in environment or .env")

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {mealie_api_key}",
            "Content-Type": "application/json",
        }
    )

    recipes = get_items(session, f"{mealie_url}/recipes?perPage=999")
    tags = get_items(session, f"{mealie_url}/organizers/tags?perPage=999")

    usage = {(tag.get("name") or ""): 0 for tag in tags if tag.get("name")}
    tag_by_name = {(tag.get("name") or ""): tag for tag in tags if tag.get("name")}

    for recipe in recipes:
        for tag in recipe.get("tags") or []:
            name = tag.get("name")
            if name in usage:
                usage[name] += 1

    candidates = []
    for name, count in sorted(usage.items(), key=lambda item: (item[1], item[0])):
        if args.only_unused and count != 0:
            continue

        is_low_usage = count < args.min_usage
        is_long = len(name) >= args.max_length
        is_noisy = args.delete_noisy and noisy_tag(name)

        if is_low_usage or is_long or is_noisy:
            tag = tag_by_name.get(name)
            if tag and tag.get("id"):
                candidates.append({"id": tag["id"], "name": name, "usage": count})

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[start] Tag cleanup mode: {mode}")
    print(f"[start] Candidate tags: {len(candidates)}")

    if not candidates:
        print("[done] No tags matched cleanup criteria.")
        return

    for item in candidates:
        if args.apply:
            response = session.delete(
                f"{mealie_url}/organizers/tags/{item['id']}",
                timeout=60,
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


if __name__ == "__main__":
    main()
