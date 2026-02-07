import argparse
import json
import os
import random
import time

import requests

from .categorizer_core import REPO_ROOT, load_env_file, MealieCategorizer

load_env_file(REPO_ROOT / ".env")

MEALIE_URL = os.environ.get("MEALIE_URL", "http://your.server.ip.address:9000/api")
MEALIE_API_KEY = os.environ.get("MEALIE_API_KEY", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral:7b")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "2"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "3"))
CACHE_FILE = os.environ.get("CACHE_FILE", str(REPO_ROOT / "cache" / "results_ollama.json"))
TAG_MAX_NAME_LENGTH = int(os.environ.get("TAG_MAX_NAME_LENGTH", "24"))
TAG_MIN_USAGE = int(os.environ.get("TAG_MIN_USAGE", "0"))
OLLAMA_REQUEST_TIMEOUT = int(os.environ.get("OLLAMA_REQUEST_TIMEOUT", "180"))
OLLAMA_HTTP_RETRIES = max(1, int(os.environ.get("OLLAMA_HTTP_RETRIES", "3")))


def parse_args():
    parser = argparse.ArgumentParser(description="Categorize Mealie recipes using Ollama.")
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


def query_ollama(prompt_text):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt_text + "\n\nRespond only with valid JSON.",
        "options": {
            "num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "1024")),
            "temperature": float(os.environ.get("OLLAMA_TEMPERATURE", "0.1")),
            "num_predict": int(os.environ.get("OLLAMA_NUM_PREDICT", "96")),
            "top_p": float(os.environ.get("OLLAMA_TOP_P", "0.8")),
            "num_thread": int(os.environ.get("OLLAMA_NUM_THREAD", "8")),
        },
    }
    last_error = None
    for attempt in range(OLLAMA_HTTP_RETRIES):
        try:
            response = requests.post(
                f"{OLLAMA_URL}/generate",
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                stream=True,
                timeout=OLLAMA_REQUEST_TIMEOUT,
            )
            if response.status_code == 429 or 500 <= response.status_code < 600:
                wait_for = (1.25 * (2**attempt)) + random.uniform(0, 0.5)
                print(
                    f"[warn] Ollama transient HTTP {response.status_code} "
                    f"(attempt {attempt + 1}/{OLLAMA_HTTP_RETRIES}), sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
                continue

            response.raise_for_status()
            text = ""
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    if "response" in chunk:
                        text += chunk["response"]
                except json.JSONDecodeError:
                    continue
            return text.strip()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < OLLAMA_HTTP_RETRIES - 1:
                wait_for = (1.25 * (2**attempt)) + random.uniform(0, 0.5)
                print(
                    f"[warn] Ollama request exception (attempt {attempt + 1}/{OLLAMA_HTTP_RETRIES}): {exc}. "
                    f"Sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
            else:
                break

    print(f"Ollama request error: {last_error or 'exhausted retries'}")
    return None


def main():
    args = parse_args()
    if not MEALIE_API_KEY:
        raise RuntimeError("MEALIE_API_KEY is empty. Set it in .env or the environment.")

    categorizer = MealieCategorizer(
        mealie_url=MEALIE_URL,
        mealie_api_key=MEALIE_API_KEY,
        batch_size=BATCH_SIZE,
        max_workers=MAX_WORKERS,
        replace_existing=args.recat,
        cache_file=CACHE_FILE,
        query_text=query_ollama,
        provider_name=f"Ollama ({OLLAMA_MODEL})",
        target_mode=derive_target_mode(args),
        tag_max_name_length=TAG_MAX_NAME_LENGTH,
        tag_min_usage=TAG_MIN_USAGE,
    )
    categorizer.run()


if __name__ == "__main__":
    main()
