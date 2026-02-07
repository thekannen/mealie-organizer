import argparse
import os

import requests

from categorizer_core import REPO_ROOT, load_env_file, MealieCategorizer

load_env_file(REPO_ROOT / ".env")

MEALIE_URL = os.environ.get("MEALIE_URL", "http://your.server.ip.address:9000/api")
MEALIE_API_KEY = os.environ.get("MEALIE_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "2"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "3"))
CACHE_FILE = os.environ.get("CACHE_FILE", str(REPO_ROOT / "cache" / "results_chatgpt.json"))
TAG_MAX_NAME_LENGTH = int(os.environ.get("TAG_MAX_NAME_LENGTH", "24"))
TAG_MIN_USAGE = int(os.environ.get("TAG_MIN_USAGE", "0"))


def parse_args():
    parser = argparse.ArgumentParser(description="Categorize Mealie recipes using ChatGPT.")
    parser.add_argument("--recat", action="store_true", help="Re-categorize all recipes.")
    parser.add_argument(
        "--missing-tags",
        action="store_true",
        help="Only process recipes missing tags.",
    )
    parser.add_argument(
        "--missing-categories",
        action="store_true",
        help="Only process recipes missing categories.",
    )
    return parser.parse_args()


def derive_target_mode(args):
    if args.missing_tags and args.missing_categories:
        return "missing-either"
    if args.missing_tags:
        return "missing-tags"
    if args.missing_categories:
        return "missing-categories"
    return "missing-either"


def query_chatgpt(prompt_text):
    payload = {
        "model": OPENAI_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "You are a precise JSON-only assistant."},
            {"role": "user", "content": prompt_text + "\n\nRespond only with valid JSON."},
        ],
    }
    try:
        response = requests.post(
            f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        print(f"ChatGPT request error: {exc}")
        return None


def main():
    args = parse_args()
    if not MEALIE_API_KEY:
        raise RuntimeError("MEALIE_API_KEY is empty. Set it in .env or the environment.")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is empty. Set it in .env or the environment.")

    categorizer = MealieCategorizer(
        mealie_url=MEALIE_URL,
        mealie_api_key=MEALIE_API_KEY,
        batch_size=BATCH_SIZE,
        max_workers=MAX_WORKERS,
        replace_existing=args.recat,
        cache_file=CACHE_FILE,
        query_text=query_chatgpt,
        provider_name=f"ChatGPT ({OPENAI_MODEL})",
        target_mode=derive_target_mode(args),
        tag_max_name_length=TAG_MAX_NAME_LENGTH,
        tag_min_usage=TAG_MIN_USAGE,
    )
    categorizer.run()


if __name__ == "__main__":
    main()
