import types

import pytest

from cookdex.categorizer_core import ProviderUnavailableError
from cookdex import recipe_categorizer
from cookdex.recipe_categorizer import cache_file_for_provider, derive_target_mode, query_chatgpt, resolve_provider


def test_resolve_provider_prefers_forced_provider():
    assert resolve_provider(cli_provider="chatgpt", forced_provider="chatgpt") == "chatgpt"


def test_resolve_provider_uses_cli_provider():
    assert resolve_provider(cli_provider="chatgpt") == "chatgpt"


def test_resolve_provider_accepts_anthropic():
    assert resolve_provider(cli_provider="anthropic") == "anthropic"


def test_resolve_provider_uses_config_default():
    assert resolve_provider() in {"ollama", "chatgpt", "anthropic"}


def test_resolve_provider_rejects_invalid():
    with pytest.raises(ValueError):
        resolve_provider(cli_provider="invalid")


def test_cache_file_for_provider_uses_config():
    assert cache_file_for_provider("ollama") == "cache/results_ollama.json"


def test_query_chatgpt_auth_error_fails_fast(monkeypatch):
    calls = []

    class _UnauthorizedResponse:
        status_code = 401
        headers = {}
        text = '{"error":{"message":"Incorrect API key provided"}}'

        def json(self):
            return {"error": {"message": "Incorrect API key provided"}}

        def raise_for_status(self):
            raise AssertionError("401 should raise ProviderUnavailableError before generic HTTP handling")

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return _UnauthorizedResponse()

    monkeypatch.setattr("cookdex.recipe_categorizer.requests.post", fake_post)

    with pytest.raises(ProviderUnavailableError, match="HTTP 401 Unauthorized"):
        query_chatgpt(
            "{}",
            "gpt-4o-mini",
            "https://api.openai.com/v1",
            "bad-key",
            request_timeout=1,
            http_retries=3,
        )

    assert len(calls) == 1


def test_ollama_uses_smaller_default_batch_size(monkeypatch):
    monkeypatch.delenv("BATCH_SIZE", raising=False)
    monkeypatch.delenv("OLLAMA_BATCH_SIZE", raising=False)

    assert recipe_categorizer.batch_size_for_provider("ollama") == 1
    assert recipe_categorizer.batch_size_for_provider("chatgpt") == 50


def test_ollama_specific_batch_size_overrides_default(monkeypatch):
    monkeypatch.delenv("BATCH_SIZE", raising=False)
    monkeypatch.setenv("OLLAMA_BATCH_SIZE", "4")

    assert recipe_categorizer.batch_size_for_provider("ollama") == 4


def test_ollama_uses_safe_cpu_defaults(monkeypatch):
    captured = {}

    def fake_query_ollama(prompt_text, model, url, request_timeout, http_retries, options):
        captured["request_timeout"] = request_timeout
        captured.update(options)
        return "[]"

    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_PREDICT", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_THREAD", raising=False)
    monkeypatch.delenv("OLLAMA_REQUEST_TIMEOUT", raising=False)
    monkeypatch.setattr(recipe_categorizer, "query_ollama", fake_query_ollama)

    query_text, provider_name = recipe_categorizer.build_provider_query("ollama")
    assert provider_name == "Ollama (llama3.1:8b)"

    query_text("prompt")

    assert captured["request_timeout"] == 300
    assert captured["num_ctx"] == 2048
    assert captured["num_predict"] == 512
    assert captured["num_thread"] == 4


def test_derive_target_mode():
    assert derive_target_mode(types.SimpleNamespace(missing_tags=True, missing_categories=False, missing_tools=False)) == "missing-tags"
    assert derive_target_mode(types.SimpleNamespace(missing_tags=False, missing_categories=True, missing_tools=False)) == "missing-categories"
    assert derive_target_mode(types.SimpleNamespace(missing_tags=False, missing_categories=False, missing_tools=True)) == "missing-tools"
    assert derive_target_mode(types.SimpleNamespace(missing_tags=True, missing_categories=False, missing_tools=True)) == "missing-either"
    assert derive_target_mode(types.SimpleNamespace(missing_tags=False, missing_categories=False, missing_tools=False)) == "missing-either"
