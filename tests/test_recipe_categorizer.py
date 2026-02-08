import types

import pytest

from mealie_organizer.recipe_categorizer import cache_file_for_provider, derive_target_mode, resolve_provider


def test_resolve_provider_prefers_forced_provider():
    assert resolve_provider(cli_provider="chatgpt", forced_provider="chatgpt") == "chatgpt"


def test_resolve_provider_uses_cli_provider():
    assert resolve_provider(cli_provider="chatgpt") == "chatgpt"


def test_resolve_provider_uses_config_default():
    assert resolve_provider() in {"ollama", "chatgpt"}


def test_resolve_provider_rejects_invalid():
    with pytest.raises(ValueError):
        resolve_provider(cli_provider="invalid")


def test_cache_file_for_provider_uses_config():
    assert cache_file_for_provider("ollama") == "cache/results_ollama.json"


def test_derive_target_mode():
    assert derive_target_mode(types.SimpleNamespace(missing_tags=True, missing_categories=False)) == "missing-tags"
    assert derive_target_mode(types.SimpleNamespace(missing_tags=False, missing_categories=True)) == "missing-categories"
    assert derive_target_mode(types.SimpleNamespace(missing_tags=False, missing_categories=False)) == "missing-either"
