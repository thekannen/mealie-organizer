import argparse
import json
import random
import time

import requests

from .categorizer_core import MealieCategorizer
from .config import env_or_config, secret

MEALIE_URL = env_or_config("MEALIE_URL", "mealie.url", "http://your.server.ip.address:9000/api")
MEALIE_API_KEY = secret("MEALIE_API_KEY")
OLLAMA_URL = env_or_config("OLLAMA_URL", "providers.ollama.url", "http://localhost:11434/api")
OLLAMA_MODEL = env_or_config("OLLAMA_MODEL", "providers.ollama.model", "mistral:7b")
BATCH_SIZE = env_or_config("BATCH_SIZE", "categorizer.batch_size", 2, int)
MAX_WORKERS = env_or_config("MAX_WORKERS", "categorizer.max_workers", 3, int)
CACHE_FILE = env_or_config("CACHE_FILE", "categorizer.cache_files.ollama", "cache/results_ollama.json")
TAG_MAX_NAME_LENGTH = env_or_config("TAG_MAX_NAME_LENGTH", "categorizer.tag_max_name_length", 24, int)
TAG_MIN_USAGE = env_or_config("TAG_MIN_USAGE", "categorizer.tag_min_usage", 0, int)
OLLAMA_REQUEST_TIMEOUT = env_or_config("OLLAMA_REQUEST_TIMEOUT", "providers.ollama.request_timeout", 180, int)
OLLAMA_HTTP_RETRIES = max(1, env_or_config("OLLAMA_HTTP_RETRIES", "providers.ollama.http_retries", 3, int))


def parse_args():
    parser = argparse.ArgumentParser(description="Categorize Mealie recipes using Ollama.")
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


def query_ollama(prompt_text):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt_text + "\n\nRespond only with valid JSON.",
        "options": {
            "num_ctx": env_or_config("OLLAMA_NUM_CTX", "providers.ollama.options.num_ctx", 1024, int),
            "temperature": env_or_config("OLLAMA_TEMPERATURE", "providers.ollama.options.temperature", 0.1, float),
            "num_predict": env_or_config("OLLAMA_NUM_PREDICT", "providers.ollama.options.num_predict", 96, int),
            "top_p": env_or_config("OLLAMA_TOP_P", "providers.ollama.options.top_p", 0.8, float),
            "num_thread": env_or_config("OLLAMA_NUM_THREAD", "providers.ollama.options.num_thread", 8, int),
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
