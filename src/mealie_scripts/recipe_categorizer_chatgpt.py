import argparse
import random
import time

import requests

from .categorizer_core import MealieCategorizer
from .config import env_or_config, secret

MEALIE_URL = env_or_config("MEALIE_URL", "mealie.url", "http://your.server.ip.address:9000/api")
MEALIE_API_KEY = secret("MEALIE_API_KEY")
OPENAI_API_KEY = secret("OPENAI_API_KEY")
OPENAI_BASE_URL = env_or_config("OPENAI_BASE_URL", "providers.chatgpt.base_url", "https://api.openai.com/v1")
OPENAI_MODEL = env_or_config("OPENAI_MODEL", "providers.chatgpt.model", "gpt-4o-mini")
BATCH_SIZE = env_or_config("BATCH_SIZE", "categorizer.batch_size", 2, int)
MAX_WORKERS = env_or_config("MAX_WORKERS", "categorizer.max_workers", 3, int)
CACHE_FILE = env_or_config("CACHE_FILE", "categorizer.cache_files.chatgpt", "cache/results_chatgpt.json")
TAG_MAX_NAME_LENGTH = env_or_config("TAG_MAX_NAME_LENGTH", "categorizer.tag_max_name_length", 24, int)
TAG_MIN_USAGE = env_or_config("TAG_MIN_USAGE", "categorizer.tag_min_usage", 0, int)
OPENAI_REQUEST_TIMEOUT = env_or_config("OPENAI_REQUEST_TIMEOUT", "providers.chatgpt.request_timeout", 120, int)
OPENAI_HTTP_RETRIES = max(1, env_or_config("OPENAI_HTTP_RETRIES", "providers.chatgpt.http_retries", 3, int))


def parse_args():
    parser = argparse.ArgumentParser(description="Categorize Mealie recipes using ChatGPT.")
    parser.add_argument("--recat", action="store_true", help="Re-categorize all recipes.")
    parser.add_argument("--missing-tags", action="store_true", help="Only process recipes missing tags.")
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
    url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    last_error = None

    for attempt in range(OPENAI_HTTP_RETRIES):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=OPENAI_REQUEST_TIMEOUT)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                retry_after = response.headers.get("Retry-After")
                wait_for = float(retry_after) if retry_after and retry_after.isdigit() else (1.5 * (2**attempt))
                wait_for += random.uniform(0, 0.5)
                print(
                    f"[warn] ChatGPT transient HTTP {response.status_code} "
                    f"(attempt {attempt + 1}/{OPENAI_HTTP_RETRIES}), sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
                continue

            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < OPENAI_HTTP_RETRIES - 1:
                wait_for = (1.5 * (2**attempt)) + random.uniform(0, 0.5)
                print(
                    f"[warn] ChatGPT request exception (attempt {attempt + 1}/{OPENAI_HTTP_RETRIES}): {exc}. "
                    f"Sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
            else:
                break
        except (ValueError, KeyError, TypeError) as exc:
            print(f"[error] ChatGPT response parse error: {exc}")
            return None

    print(f"ChatGPT request error: {last_error or 'exhausted retries'}")
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
