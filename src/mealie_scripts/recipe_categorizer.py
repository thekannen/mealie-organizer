import argparse
import json
import random
import time

import requests

from .categorizer_core import MealieCategorizer
from .config import env_or_config, secret

MEALIE_URL = env_or_config("MEALIE_URL", "mealie.url", "http://your.server.ip.address:9000/api")
BATCH_SIZE = env_or_config("BATCH_SIZE", "categorizer.batch_size", 2, int)
MAX_WORKERS = env_or_config("MAX_WORKERS", "categorizer.max_workers", 3, int)
TAG_MAX_NAME_LENGTH = env_or_config("TAG_MAX_NAME_LENGTH", "categorizer.tag_max_name_length", 24, int)
TAG_MIN_USAGE = env_or_config("TAG_MIN_USAGE", "categorizer.tag_min_usage", 0, int)


def parse_args(forced_provider=None):
    parser = argparse.ArgumentParser(description="Categorize Mealie recipes using configured provider.")
    if not forced_provider:
        parser.add_argument(
            "--provider",
            choices=["ollama", "chatgpt"],
            help="Override provider from config for this run.",
        )
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


def resolve_provider(cli_provider=None, forced_provider=None):
    provider = forced_provider or cli_provider or env_or_config("CATEGORIZER_PROVIDER", "categorizer.provider", "ollama")
    provider = (provider or "").strip().lower()
    if provider not in {"ollama", "chatgpt"}:
        raise ValueError(
            "Invalid provider. Use 'ollama' or 'chatgpt' via --provider "
            "or categorizer.provider in configs/config.json."
        )
    return provider


def cache_file_for_provider(provider):
    return env_or_config("CACHE_FILE", f"categorizer.cache_files.{provider}", f"cache/results_{provider}.json")


def query_chatgpt(prompt_text, model, base_url, api_key, request_timeout, http_retries):
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "You are a precise JSON-only assistant."},
            {"role": "user", "content": prompt_text + "\n\nRespond only with valid JSON."},
        ],
    }
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error = None

    for attempt in range(http_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=request_timeout)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                retry_after = response.headers.get("Retry-After")
                wait_for = float(retry_after) if retry_after and retry_after.isdigit() else (1.5 * (2**attempt))
                wait_for += random.uniform(0, 0.5)
                print(
                    f"[warn] ChatGPT transient HTTP {response.status_code} "
                    f"(attempt {attempt + 1}/{http_retries}), sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
                continue

            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < http_retries - 1:
                wait_for = (1.5 * (2**attempt)) + random.uniform(0, 0.5)
                print(
                    f"[warn] ChatGPT request exception (attempt {attempt + 1}/{http_retries}): {exc}. "
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


def query_ollama(prompt_text, model, url, request_timeout, http_retries, options):
    payload = {
        "model": model,
        "prompt": prompt_text + "\n\nRespond only with valid JSON.",
        "options": options,
    }
    last_error = None

    for attempt in range(http_retries):
        try:
            response = requests.post(
                f"{url.rstrip('/')}/generate",
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                stream=True,
                timeout=request_timeout,
            )
            if response.status_code == 429 or 500 <= response.status_code < 600:
                wait_for = (1.25 * (2**attempt)) + random.uniform(0, 0.5)
                print(
                    f"[warn] Ollama transient HTTP {response.status_code} "
                    f"(attempt {attempt + 1}/{http_retries}), sleeping {wait_for:.1f}s"
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
            if attempt < http_retries - 1:
                wait_for = (1.25 * (2**attempt)) + random.uniform(0, 0.5)
                print(
                    f"[warn] Ollama request exception (attempt {attempt + 1}/{http_retries}): {exc}. "
                    f"Sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
            else:
                break

    print(f"Ollama request error: {last_error or 'exhausted retries'}")
    return None


def build_provider_query(provider):
    if provider == "chatgpt":
        api_key = secret("OPENAI_API_KEY", required=True)
        base_url = env_or_config("OPENAI_BASE_URL", "providers.chatgpt.base_url", "https://api.openai.com/v1")
        model = env_or_config("OPENAI_MODEL", "providers.chatgpt.model", "gpt-4o-mini")
        request_timeout = env_or_config("OPENAI_REQUEST_TIMEOUT", "providers.chatgpt.request_timeout", 120, int)
        http_retries = max(1, env_or_config("OPENAI_HTTP_RETRIES", "providers.chatgpt.http_retries", 3, int))

        def _query(prompt_text):
            return query_chatgpt(prompt_text, model, base_url, api_key, request_timeout, http_retries)

        return _query, f"ChatGPT ({model})"

    model = env_or_config("OLLAMA_MODEL", "providers.ollama.model", "mistral:7b")
    url = env_or_config("OLLAMA_URL", "providers.ollama.url", "http://localhost:11434/api")
    request_timeout = env_or_config("OLLAMA_REQUEST_TIMEOUT", "providers.ollama.request_timeout", 180, int)
    http_retries = max(1, env_or_config("OLLAMA_HTTP_RETRIES", "providers.ollama.http_retries", 3, int))
    options = {
        "num_ctx": env_or_config("OLLAMA_NUM_CTX", "providers.ollama.options.num_ctx", 1024, int),
        "temperature": env_or_config("OLLAMA_TEMPERATURE", "providers.ollama.options.temperature", 0.1, float),
        "num_predict": env_or_config("OLLAMA_NUM_PREDICT", "providers.ollama.options.num_predict", 96, int),
        "top_p": env_or_config("OLLAMA_TOP_P", "providers.ollama.options.top_p", 0.8, float),
        "num_thread": env_or_config("OLLAMA_NUM_THREAD", "providers.ollama.options.num_thread", 8, int),
    }

    def _query(prompt_text):
        return query_ollama(prompt_text, model, url, request_timeout, http_retries, options)

    return _query, f"Ollama ({model})"


def main(forced_provider=None):
    args = parse_args(forced_provider=forced_provider)

    mealie_api_key = secret("MEALIE_API_KEY")
    if not mealie_api_key:
        raise RuntimeError("MEALIE_API_KEY is empty. Set it in .env or the environment.")

    provider = resolve_provider(getattr(args, "provider", None), forced_provider=forced_provider)
    query_text, provider_name = build_provider_query(provider)

    categorizer = MealieCategorizer(
        mealie_url=MEALIE_URL,
        mealie_api_key=mealie_api_key,
        batch_size=BATCH_SIZE,
        max_workers=MAX_WORKERS,
        replace_existing=args.recat,
        cache_file=cache_file_for_provider(provider),
        query_text=query_text,
        provider_name=provider_name,
        target_mode=derive_target_mode(args),
        tag_max_name_length=TAG_MAX_NAME_LENGTH,
        tag_min_usage=TAG_MIN_USAGE,
    )
    categorizer.run()


if __name__ == "__main__":
    main()
