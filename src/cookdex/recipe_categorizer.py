from __future__ import annotations

import argparse
import json
import random
import time
from typing import Callable

import requests

from .categorizer_core import MealieCategorizer
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url, secret, to_bool


def require_str(value: object, field: str) -> str:
    if isinstance(value, str):
        return value
    raise ValueError(f"Invalid value for '{field}': expected string, got {type(value).__name__}")


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


def require_float(value: object, field: str) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value.strip())
    raise ValueError(f"Invalid value for '{field}': expected float-like, got {type(value).__name__}")


BATCH_SIZE: int = require_int(env_or_config("BATCH_SIZE", "categorizer.batch_size", 5, int), "categorizer.batch_size")
MAX_WORKERS: int = require_int(env_or_config("MAX_WORKERS", "categorizer.max_workers", 3, int), "categorizer.max_workers")
INTER_REQUEST_DELAY: float = require_float(
    env_or_config("INTER_REQUEST_DELAY", "categorizer.inter_request_delay", 1.5, float),
    "categorizer.inter_request_delay",
)
TAG_MAX_NAME_LENGTH: int = require_int(
    env_or_config("TAG_MAX_NAME_LENGTH", "categorizer.tag_max_name_length", 24, int),
    "categorizer.tag_max_name_length",
)
TAG_MIN_USAGE: int = require_int(env_or_config("TAG_MIN_USAGE", "categorizer.tag_min_usage", 0, int), "categorizer.tag_min_usage")


def parse_args(forced_provider: str | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Categorize Mealie recipes using configured provider.")
    if not forced_provider:
        parser.add_argument(
            "--provider",
            choices=["ollama", "chatgpt", "anthropic"],
            help="Override provider from .env/environment for this run.",
        )
    parser.add_argument("--recat", action="store_true", help="Re-categorize all recipes.")
    parser.add_argument("--missing-tags", action="store_true", help="Only process recipes missing tags.")
    parser.add_argument(
        "--missing-categories",
        action="store_true",
        help="Only process recipes missing categories.",
    )
    parser.add_argument("--missing-tools", action="store_true", help="Only process recipes missing tools.")
    return parser.parse_args()


def derive_target_mode(args: argparse.Namespace) -> str:
    selected = [
        bool(getattr(args, "missing_tags", False)),
        bool(getattr(args, "missing_categories", False)),
        bool(getattr(args, "missing_tools", False)),
    ]
    if sum(selected) > 1:
        return "missing-either"
    if getattr(args, "missing_tags", False):
        return "missing-tags"
    if getattr(args, "missing_categories", False):
        return "missing-categories"
    if getattr(args, "missing_tools", False):
        return "missing-tools"
    return "missing-either"


def resolve_provider(cli_provider: str | None = None, forced_provider: str | None = None) -> str:
    provider = forced_provider or cli_provider or env_or_config("CATEGORIZER_PROVIDER", "categorizer.provider", "chatgpt")
    provider = require_str(provider, "categorizer.provider").strip().lower()
    if provider not in {"ollama", "chatgpt", "anthropic"}:
        raise ValueError(
            "Invalid provider. Use 'ollama', 'chatgpt', or 'anthropic' via --provider "
            "or CATEGORIZER_PROVIDER in .env or the environment."
        )
    return provider


def cache_file_for_provider(provider: str) -> str:
    return require_str(
        env_or_config("CACHE_FILE", f"categorizer.cache_files.{provider}", f"cache/results_{provider}.json"),
        f"categorizer.cache_files.{provider}",
    )


_MAX_RATE_LIMIT_RETRIES = 8


def _rate_limit_wait(provider: str, response, rate_limit_hits: int) -> float:
    """Return seconds to sleep on a 429/5xx, using Retry-After when available."""
    retry_after = response.headers.get("Retry-After")
    if retry_after and retry_after.replace(".", "", 1).isdigit():
        wait = float(retry_after) + random.uniform(0.5, 1.5)
    else:
        wait = min(2.0 * (2 ** rate_limit_hits), 60.0) + random.uniform(0.5, 1.5)
    print(
        f"[warn] {provider} HTTP {response.status_code} "
        f"(rate-limit hit #{rate_limit_hits + 1}), sleeping {wait:.1f}s"
    )
    return wait


def query_chatgpt(
    prompt_text: str,
    model: str,
    base_url: str,
    api_key: str,
    request_timeout: int,
    http_retries: int,
) -> str | None:
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
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
    attempt = 0
    rate_limit_hits = 0

    while attempt < http_retries:
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=request_timeout)
            if response.status_code == 429:
                if rate_limit_hits >= _MAX_RATE_LIMIT_RETRIES:
                    print(f"[error] ChatGPT: {_MAX_RATE_LIMIT_RETRIES} rate-limit retries exhausted")
                    return None
                time.sleep(_rate_limit_wait("ChatGPT", response, rate_limit_hits))
                rate_limit_hits += 1
                continue  # don't increment attempt for rate limits
            if 500 <= response.status_code < 600:
                wait_for = (1.5 * (2 ** attempt)) + random.uniform(0, 0.5)
                print(
                    f"[warn] ChatGPT HTTP {response.status_code} "
                    f"(attempt {attempt + 1}/{http_retries}), sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
                attempt += 1
                continue

            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except requests.RequestException as exc:
            last_error = exc
            attempt += 1
            if attempt < http_retries:
                wait_for = (1.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.5)
                print(
                    f"[warn] ChatGPT request exception (attempt {attempt}/{http_retries}): {exc}. "
                    f"Sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
            continue
        except (ValueError, KeyError, TypeError) as exc:
            print(f"[error] ChatGPT response parse error: {exc}")
            return None

    print(f"ChatGPT request error: {last_error or 'exhausted retries'}")
    return None


OLLAMA_ARRAY_SCHEMA: dict = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "slug": {"type": "string"},
            "categories": {"type": "array", "items": {"type": "string"}},
            "tags": {"type": "array", "items": {"type": "string"}},
            "tools": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["slug", "categories", "tags", "tools"],
    },
}


def query_ollama(
    prompt_text: str,
    model: str,
    url: str,
    request_timeout: int,
    http_retries: int,
    options: dict[str, int | float],
) -> str | None:
    payload = {
        "model": model,
        "prompt": prompt_text + "\n\nRespond only with valid JSON.",
        "format": OLLAMA_ARRAY_SCHEMA,
        "options": options,
    }
    last_error = None
    attempt = 0
    rate_limit_hits = 0

    while attempt < http_retries:
        try:
            response = requests.post(
                f"{url.rstrip('/')}/generate",
                headers={"Content-Type": "application/json"},
                json={**payload, "stream": False},
                timeout=request_timeout,
            )
            if response.status_code == 429:
                if rate_limit_hits >= _MAX_RATE_LIMIT_RETRIES:
                    print(f"[error] Ollama: {_MAX_RATE_LIMIT_RETRIES} rate-limit retries exhausted")
                    return None
                time.sleep(_rate_limit_wait("Ollama", response, rate_limit_hits))
                rate_limit_hits += 1
                continue
            if 500 <= response.status_code < 600:
                wait_for = (1.25 * (2 ** attempt)) + random.uniform(0, 0.5)
                print(
                    f"[warn] Ollama HTTP {response.status_code} "
                    f"(attempt {attempt + 1}/{http_retries}), sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
                attempt += 1
                continue

            response.raise_for_status()
            data = response.json()
            return (data.get("response") or "").strip()
        except requests.RequestException as exc:
            last_error = exc
            attempt += 1
            if attempt < http_retries:
                wait_for = (1.25 * (2 ** (attempt - 1))) + random.uniform(0, 0.5)
                print(
                    f"[warn] Ollama request exception (attempt {attempt}/{http_retries}): {exc}. "
                    f"Sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
            continue

    print(f"Ollama request error: {last_error or 'exhausted retries'}")
    return None


def query_anthropic(
    prompt_text: str,
    model: str,
    base_url: str,
    api_key: str,
    request_timeout: int,
    http_retries: int,
    max_tokens: int,
) -> str | None:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "user", "content": prompt_text + "\n\nRespond only with valid JSON."},
            {"role": "assistant", "content": "["},
        ],
        "system": "You are a precise JSON-only assistant. Always respond with a raw JSON array.",
    }
    url = f"{base_url.rstrip('/')}/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    last_error = None
    attempt = 0
    rate_limit_hits = 0

    while attempt < http_retries:
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=request_timeout)
            if response.status_code == 429:
                if rate_limit_hits >= _MAX_RATE_LIMIT_RETRIES:
                    print(f"[error] Anthropic: {_MAX_RATE_LIMIT_RETRIES} rate-limit retries exhausted")
                    return None
                time.sleep(_rate_limit_wait("Anthropic", response, rate_limit_hits))
                rate_limit_hits += 1
                continue  # don't increment attempt for rate limits
            if 500 <= response.status_code < 600:
                wait_for = (1.5 * (2 ** attempt)) + random.uniform(0, 0.5)
                print(
                    f"[warn] Anthropic HTTP {response.status_code} "
                    f"(attempt {attempt + 1}/{http_retries}), sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
                attempt += 1
                continue

            response.raise_for_status()
            data = response.json()
            content = data.get("content", [])
            if isinstance(content, list) and content:
                text = content[0].get("text", "").strip()
                # Prepend the "[" from the prefilled assistant turn.
                return "[" + text if text else None
            return None
        except requests.RequestException as exc:
            last_error = exc
            attempt += 1
            if attempt < http_retries:
                wait_for = (1.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.5)
                print(
                    f"[warn] Anthropic request exception (attempt {attempt}/{http_retries}): {exc}. "
                    f"Sleeping {wait_for:.1f}s"
                )
                time.sleep(wait_for)
            continue
        except (ValueError, KeyError, TypeError) as exc:
            print(f"[error] Anthropic response parse error: {exc}")
            return None

    print(f"Anthropic request error: {last_error or 'exhausted retries'}")
    return None


def build_provider_query(provider: str) -> tuple[Callable[[str], str | None], str]:
    if provider == "anthropic":
        api_key = secret("ANTHROPIC_API_KEY", required=True)
        base_url = require_str(
            env_or_config("ANTHROPIC_BASE_URL", "providers.anthropic.base_url", "https://api.anthropic.com/v1"),
            "providers.anthropic.base_url",
        )
        model = require_str(
            env_or_config("ANTHROPIC_MODEL", "providers.anthropic.model", "claude-haiku-4-5-20251001"),
            "providers.anthropic.model",
        )
        request_timeout = require_int(
            env_or_config("ANTHROPIC_REQUEST_TIMEOUT", "providers.anthropic.request_timeout", 120, int),
            "providers.anthropic.request_timeout",
        )
        http_retries = max(
            1,
            require_int(
                env_or_config("ANTHROPIC_HTTP_RETRIES", "providers.anthropic.http_retries", 3, int),
                "providers.anthropic.http_retries",
            ),
        )
        max_tokens = require_int(
            env_or_config("ANTHROPIC_MAX_TOKENS", "providers.anthropic.max_tokens", 4096, int),
            "providers.anthropic.max_tokens",
        )

        def _query_anthropic(prompt_text: str) -> str | None:
            return query_anthropic(prompt_text, model, base_url, api_key, request_timeout, http_retries, max_tokens)

        return _query_anthropic, f"Anthropic ({model})"

    if provider == "chatgpt":
        api_key = secret("OPENAI_API_KEY", required=True)
        base_url = require_str(
            env_or_config("OPENAI_BASE_URL", "providers.chatgpt.base_url", "https://api.openai.com/v1"),
            "providers.chatgpt.base_url",
        )
        model = require_str(
            env_or_config("OPENAI_MODEL", "providers.chatgpt.model", "gpt-4o-mini"),
            "providers.chatgpt.model",
        )
        request_timeout = require_int(
            env_or_config("OPENAI_REQUEST_TIMEOUT", "providers.chatgpt.request_timeout", 120, int),
            "providers.chatgpt.request_timeout",
        )
        http_retries = max(
            1,
            require_int(
                env_or_config("OPENAI_HTTP_RETRIES", "providers.chatgpt.http_retries", 3, int),
                "providers.chatgpt.http_retries",
            ),
        )

        def _query_chatgpt(prompt_text: str) -> str | None:
            return query_chatgpt(prompt_text, model, base_url, api_key, request_timeout, http_retries)

        return _query_chatgpt, f"ChatGPT ({model})"

    model = require_str(
        env_or_config("OLLAMA_MODEL", "providers.ollama.model", ""),
        "providers.ollama.model",
    )
    if not model:
        raise ValueError(
            "No Ollama model configured. Set OLLAMA_MODEL in environment, "
            "config file, or the Settings UI."
        )
    url = require_str(
        env_or_config("OLLAMA_URL", "providers.ollama.url", "http://localhost:11434/api"),
        "providers.ollama.url",
    )
    request_timeout = require_int(
        env_or_config("OLLAMA_REQUEST_TIMEOUT", "providers.ollama.request_timeout", 180, int),
        "providers.ollama.request_timeout",
    )
    http_retries = max(
        1,
        require_int(
            env_or_config("OLLAMA_HTTP_RETRIES", "providers.ollama.http_retries", 3, int),
            "providers.ollama.http_retries",
        ),
    )
    options = {
        "num_ctx": require_int(
            env_or_config("OLLAMA_NUM_CTX", "providers.ollama.options.num_ctx", 4096, int),
            "providers.ollama.options.num_ctx",
        ),
        "temperature": require_float(
            env_or_config("OLLAMA_TEMPERATURE", "providers.ollama.options.temperature", 0.0, float),
            "providers.ollama.options.temperature",
        ),
        "num_predict": require_int(
            env_or_config("OLLAMA_NUM_PREDICT", "providers.ollama.options.num_predict", 1024, int),
            "providers.ollama.options.num_predict",
        ),
        "top_p": require_float(
            env_or_config("OLLAMA_TOP_P", "providers.ollama.options.top_p", 0.8, float),
            "providers.ollama.options.top_p",
        ),
        "num_thread": require_int(
            env_or_config("OLLAMA_NUM_THREAD", "providers.ollama.options.num_thread", 8, int),
            "providers.ollama.options.num_thread",
        ),
    }

    def _query_ollama(prompt_text: str) -> str | None:
        return query_ollama(prompt_text, model, url, request_timeout, http_retries, options)

    return _query_ollama, f"Ollama ({model})"


def main(forced_provider: str | None = None) -> None:
    args = parse_args(forced_provider=forced_provider)

    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    mealie_url = resolve_mealie_url()
    mealie_api_key = resolve_mealie_api_key(required=True)

    provider = resolve_provider(getattr(args, "provider", None), forced_provider=forced_provider)
    query_text, provider_name = build_provider_query(provider)

    categorizer = MealieCategorizer(
        mealie_url=mealie_url,
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
        dry_run=dry_run,
        inter_request_delay=INTER_REQUEST_DELAY,
    )
    categorizer.run()


if __name__ == "__main__":
    main()
