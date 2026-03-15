"""Tests for the recipe_dredger package."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# url_utils
# ---------------------------------------------------------------------------

from cookdex.recipe_dredger.url_utils import canonicalize_url


class TestCanonicalizeUrl:
    def test_strips_www(self):
        assert canonicalize_url("https://www.example.com/foo") == "https://example.com/foo"

    def test_strips_trailing_slash(self):
        assert canonicalize_url("https://example.com/foo/") == "https://example.com/foo"

    def test_root_keeps_slash(self):
        assert canonicalize_url("https://example.com/") == "https://example.com/"

    def test_strips_utm(self):
        result = canonicalize_url("https://example.com/page?utm_source=foo&real=1")
        assert "utm_source" not in result
        assert "real=1" in result

    def test_strips_tracking_keys(self):
        result = canonicalize_url("https://example.com/page?fbclid=abc&q=test")
        assert "fbclid" not in result
        assert "q=test" in result

    def test_empty_returns_empty(self):
        assert canonicalize_url("") == ""
        assert canonicalize_url(None) == ""

    def test_lowercases_scheme_and_host(self):
        assert canonicalize_url("HTTPS://Example.COM/Path") == "https://example.com/Path"


# ---------------------------------------------------------------------------
# DredgerStore
# ---------------------------------------------------------------------------

from cookdex.recipe_dredger.storage import DredgerStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_state.db"
        yield DredgerStore(db_path=db_path)


class TestDredgerStoreImported:
    def test_add_and_check(self, store):
        assert not store.is_imported("https://example.com/recipe-1")
        store.add_imported("https://example.com/recipe-1")
        assert store.is_imported("https://example.com/recipe-1")

    def test_count(self, store):
        assert store.imported_count() == 0
        store.add_imported("https://example.com/a")
        store.add_imported("https://example.com/b")
        assert store.imported_count() == 2

    def test_add_removes_from_retry(self, store):
        store.add_retry("https://example.com/a", "transient", increment=True)
        assert store.is_in_retry("https://example.com/a")
        store.add_imported("https://example.com/a")
        assert not store.is_in_retry("https://example.com/a")


class TestDredgerStoreRejects:
    def test_add_and_check(self, store):
        store.add_reject("https://example.com/junk", reason="Not a recipe")
        assert store.is_rejected("https://example.com/junk")
        assert store.rejected_count() == 1

    def test_add_removes_from_retry(self, store):
        store.add_retry("https://example.com/a", "transient")
        store.add_reject("https://example.com/a", "permanent")
        assert not store.is_in_retry("https://example.com/a")


class TestDredgerStoreRetry:
    def test_add_and_increment(self, store):
        attempts = store.add_retry("https://example.com/a", "err", increment=True)
        assert attempts == 1
        attempts = store.add_retry("https://example.com/a", "err2", increment=True)
        assert attempts == 2

    def test_get_retry_queue(self, store):
        store.add_retry("https://example.com/a", "err", increment=True)
        store.add_retry("https://example.com/b", "err2", increment=True)
        queue = store.get_retry_queue()
        assert len(queue) == 2
        urls = {entry["url"] for entry in queue}
        assert "https://example.com/a" in urls or any("example.com/a" in u for u in urls)


class TestDredgerStoreIsKnown:
    def test_imported_is_known(self, store):
        store.add_imported("https://example.com/a")
        assert store.is_known("https://example.com/a")

    def test_rejected_is_known(self, store):
        store.add_reject("https://example.com/b")
        assert store.is_known("https://example.com/b")

    def test_retry_is_known(self, store):
        store.add_retry("https://example.com/c", "err")
        assert store.is_known("https://example.com/c")

    def test_unknown(self, store):
        assert not store.is_known("https://example.com/unknown")


class TestDredgerStoreSitemapCache:
    def test_cache_and_retrieve(self, store):
        store.cache_sitemap("https://example.com", "https://example.com/sitemap.xml", ["url1", "url2"])
        cached = store.get_cached_sitemap("https://example.com")
        assert cached is not None
        assert cached["urls"] == ["url1", "url2"]

    def test_expired_cache_returns_none(self, store):
        store.cache_sitemap("https://example.com", "https://example.com/sitemap.xml", ["url1"])
        result = store.get_cached_sitemap("https://example.com", cache_expiry_days=0)
        # With 0 day expiry, should be expired immediately
        assert result is None


class TestDredgerStoreSites:
    def test_add_and_list(self, store):
        site_id = store.add_site("https://example.com", label="Test", region="General")
        assert site_id > 0
        sites = store.get_all_sites()
        assert len(sites) == 1
        assert sites[0]["url"] == "https://example.com"
        assert sites[0]["region"] == "General"

    def test_strips_trailing_slash(self, store):
        store.add_site("https://example.com/")
        sites = store.get_all_sites()
        assert sites[0]["url"] == "https://example.com"

    def test_duplicate_raises(self, store):
        store.add_site("https://example.com")
        with pytest.raises(sqlite3.IntegrityError):
            store.add_site("https://example.com")

    def test_update(self, store):
        site_id = store.add_site("https://example.com")
        assert store.update_site(site_id, enabled=False)
        sites = store.get_all_sites()
        assert sites[0]["enabled"] == 0

    def test_delete(self, store):
        site_id = store.add_site("https://example.com")
        assert store.delete_site(site_id)
        assert store.sites_count() == 0

    def test_get_enabled_sites(self, store):
        store.add_site("https://enabled.example.com")
        disabled_id = store.add_site("https://disabled.example.com")
        store.update_site(disabled_id, enabled=False)
        enabled = store.get_enabled_sites()
        assert len(enabled) == 1
        assert enabled[0] == "https://enabled.example.com"

    def test_seed_defaults(self, store):
        defaults = [
            {"url": "https://a.com", "region": "General"},
            {"url": "https://b.com", "region": "Asian"},
        ]
        inserted = store.seed_defaults(defaults)
        assert inserted == 2
        assert store.sites_count() == 2

    def test_seed_skips_when_not_empty(self, store):
        store.add_site("https://existing.com")
        inserted = store.seed_defaults([{"url": "https://new.com"}])
        assert inserted == 0
        assert store.sites_count() == 1

    def test_seed_force_replaces(self, store):
        store.add_site("https://existing.example.com")
        inserted = store.seed_defaults([{"url": "https://new.example.com"}], force=True)
        assert inserted == 1
        sites = store.get_enabled_sites()
        assert sites == ["https://new.example.com"]


# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------

from cookdex.recipe_dredger.patterns import (
    LISTICLE_REGEX,
    HOW_TO_COOK_REGEX,
    NON_RECIPE_DIGEST_REGEX,
)


class TestPatterns:
    def test_listicle_matches(self):
        assert LISTICLE_REGEX.search("top 10 recipes for dinner")
        assert LISTICLE_REGEX.search("best appetizer ideas")

    def test_listicle_no_match(self):
        assert not LISTICLE_REGEX.search("chicken tikka masala")

    def test_how_to_matches(self):
        assert HOW_TO_COOK_REGEX.search("how to cook rice")
        assert HOW_TO_COOK_REGEX.search("how to make bread")

    def test_how_to_no_match(self):
        assert not HOW_TO_COOK_REGEX.search("easy chicken recipe")

    def test_digest_matches(self):
        assert NON_RECIPE_DIGEST_REGEX.search("friday finds this week")
        assert NON_RECIPE_DIGEST_REGEX.search("monthly report")


# ---------------------------------------------------------------------------
# Verifier pre-filter
# ---------------------------------------------------------------------------

from cookdex.recipe_dredger.verifier import RecipeVerifier


class TestVerifierPreFilter:
    def test_rejects_image_url(self):
        v = RecipeVerifier.__new__(RecipeVerifier)
        assert v.pre_filter_candidate("https://example.com/photo.jpg") is not None

    def test_rejects_wp_uploads(self):
        v = RecipeVerifier.__new__(RecipeVerifier)
        assert v.pre_filter_candidate("https://example.com/wp-content/uploads/file") is not None

    def test_accepts_recipe_url(self):
        v = RecipeVerifier.__new__(RecipeVerifier)
        assert v.pre_filter_candidate("https://example.com/chicken-tikka-masala") is None

    def test_rejects_blog_index(self):
        v = RecipeVerifier.__new__(RecipeVerifier)
        assert v.pre_filter_candidate("https://example.com/blog") is not None


class TestVerifierParanoidSkip:
    def test_how_to_slug(self):
        v = RecipeVerifier.__new__(RecipeVerifier)
        assert v.is_paranoid_skip("https://example.com/how-to-cook-rice") is not None

    def test_listicle_slug(self):
        v = RecipeVerifier.__new__(RecipeVerifier)
        assert v.is_paranoid_skip("https://example.com/top-10-recipes") is not None

    def test_normal_recipe_passes(self):
        v = RecipeVerifier.__new__(RecipeVerifier)
        assert v.is_paranoid_skip("https://example.com/chicken-tikka-masala") is None


# ---------------------------------------------------------------------------
# Default sites list
# ---------------------------------------------------------------------------

from cookdex.recipe_dredger.sites import DEFAULT_SITES


class TestDefaultSites:
    def test_not_empty(self):
        assert len(DEFAULT_SITES) > 50

    def test_all_have_url(self):
        for entry in DEFAULT_SITES:
            assert entry["url"].startswith("https://")

    def test_all_have_region(self):
        for entry in DEFAULT_SITES:
            assert entry.get("region"), f"Missing region for {entry['url']}"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

from cookdex.recipe_dredger.models import RecipeCandidate


class TestRecipeCandidate:
    def test_equality(self):
        a = RecipeCandidate(url="https://example.com/a")
        b = RecipeCandidate(url="https://example.com/a")
        assert a == b

    def test_hash(self):
        a = RecipeCandidate(url="https://example.com/a")
        b = RecipeCandidate(url="https://example.com/a")
        assert hash(a) == hash(b)
        assert len({a, b}) == 1


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------

from cookdex.webui_server.tasks import TaskRegistry


class TestDredgerTaskRegistration:
    def test_recipe_dredger_task_exists(self):
        registry = TaskRegistry()
        assert "recipe-dredger" in registry.task_ids

    def test_build_dry_run(self):
        registry = TaskRegistry()
        execution = registry.build_execution("recipe-dredger", {"dry_run": True})
        assert "--dry-run" in execution.command
        assert not execution.dangerous_requested

    def test_build_live_run(self):
        registry = TaskRegistry()
        execution = registry.build_execution("recipe-dredger", {"dry_run": False})
        assert "--dry-run" not in execution.command
        assert execution.dangerous_requested

    def test_build_with_options(self):
        registry = TaskRegistry()
        execution = registry.build_execution("recipe-dredger", {
            "dry_run": True,
            "limit": 10,
            "depth": 500,
            "no_cache": True,
            "import_workers": 4,
            "precheck_duplicates": False,
            "language_filter": False,
            "max_retry_attempts": 5,
        })
        cmd = execution.command
        assert "--limit" in cmd
        assert "10" in cmd
        assert "--depth" in cmd
        assert "500" in cmd
        assert "--no-cache" in cmd
        assert "--workers" in cmd
        assert "4" in cmd
        assert "--no-precheck" in cmd
        assert "--no-language-filter" in cmd
        assert "--max-retries" in cmd
        assert "5" in cmd

    def test_describe_includes_dredger(self):
        registry = TaskRegistry()
        descriptions = registry.describe_tasks()
        dredger = next((t for t in descriptions if t["task_id"] == "recipe-dredger"), None)
        assert dredger is not None
        assert dredger["group"] == "Data Pipeline"
        assert len(dredger["options"]) == 8


# ---------------------------------------------------------------------------
# ImportManager URL normalization
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock
from cookdex.recipe_dredger.importer import ImportManager


class TestImportManagerUrlNormalization:
    def _make_manager(self, url: str) -> ImportManager:
        store = MagicMock()
        rate_limiter = MagicMock()
        return ImportManager(
            mealie_url=url,
            mealie_api_key="test-key",
            store=store,
            rate_limiter=rate_limiter,
            dry_run=True,
        )

    def test_strips_api_suffix(self):
        mgr = self._make_manager("http://host:9000/api")
        assert mgr.mealie_url == "http://host:9000"

    def test_strips_api_suffix_with_trailing_slash(self):
        mgr = self._make_manager("http://host:9000/api/")
        assert mgr.mealie_url == "http://host:9000"

    def test_no_api_suffix_unchanged(self):
        mgr = self._make_manager("http://host:9000")
        assert mgr.mealie_url == "http://host:9000"
