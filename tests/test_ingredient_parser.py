from __future__ import annotations

from unittest.mock import MagicMock

from cookdex import ingredient_parser
from cookdex.ingredient_parser import ReviewTagManager


def test_build_candidate_slugs_prefers_has_parsed_flag_when_present():
    recipes = [
        {"slug": "already", "hasParsedIngredients": True, "updatedAt": "2026-01-01T00:00:00Z"},
        {"slug": "todo", "hasParsedIngredients": False, "updatedAt": "2026-01-02T00:00:00Z"},
    ]

    slugs, skipped_cached, missing_flag, updated = ingredient_parser._build_candidate_slugs(
        recipes,
        cache={},
        recheck_review=False,
    )

    assert slugs == ["todo"]
    assert skipped_cached == 0
    assert missing_flag == 0
    assert updated["already"] == "2026-01-01T00:00:00Z"
    assert updated["todo"] == "2026-01-02T00:00:00Z"


def test_build_candidate_slugs_skips_unchanged_cached_recipe_when_flag_missing():
    recipes = [{"slug": "cached", "updatedAt": "2026-01-03T00:00:00Z"}]
    cache = {"cached": {"updated_at": "2026-01-03T00:00:00Z", "status": "already_parsed", "checked_at": "x"}}

    slugs, skipped_cached, missing_flag, _ = ingredient_parser._build_candidate_slugs(
        recipes,
        cache=cache,
        recheck_review=False,
    )

    assert slugs == []
    assert skipped_cached == 1
    assert missing_flag == 1


def test_build_candidate_slugs_recheck_review_overrides_cache_skip():
    recipes = [{"slug": "reviewed", "updatedAt": "2026-01-04T00:00:00Z"}]
    cache = {"reviewed": {"updated_at": "2026-01-04T00:00:00Z", "status": "needs_review", "checked_at": "x"}}

    slugs_default, skipped_default, _, _ = ingredient_parser._build_candidate_slugs(
        recipes,
        cache=cache,
        recheck_review=False,
    )
    slugs_recheck, skipped_recheck, _, _ = ingredient_parser._build_candidate_slugs(
        recipes,
        cache=cache,
        recheck_review=True,
    )

    assert slugs_default == []
    assert skipped_default == 1
    assert slugs_recheck == ["reviewed"]
    assert skipped_recheck == 0


def test_build_candidate_slugs_requeues_when_recipe_was_updated():
    recipes = [{"slug": "changed", "updatedAt": "2026-01-05T00:00:00Z"}]
    cache = {"changed": {"updated_at": "2026-01-01T00:00:00Z", "status": "already_parsed", "checked_at": "x"}}

    slugs, skipped_cached, missing_flag, _ = ingredient_parser._build_candidate_slugs(
        recipes,
        cache=cache,
        recheck_review=False,
    )

    assert slugs == ["changed"]
    assert skipped_cached == 0
    assert missing_flag == 1


# ── ReviewTagManager tests ───────────────────────────────────────────


def _mock_client(existing_tags=None, patch_side_effect=None):
    client = MagicMock()
    client.get_organizer_items.return_value = existing_tags or []
    client.create_organizer_item.return_value = {"id": "new-tag-id", "name": "Parser: Needs Review"}
    if patch_side_effect:
        client.patch_recipe.side_effect = patch_side_effect
    else:
        client.patch_recipe.return_value = {}
    return client


def test_review_tag_manager_creates_tag_when_not_found():
    client = _mock_client(existing_tags=[])
    mgr = ReviewTagManager(client, "Parser: Needs Review", dry_run=False)
    result = mgr.ensure_tagged("my-recipe", [])
    assert result is True
    client.create_organizer_item.assert_called_once_with("tags", {"name": "Parser: Needs Review"})
    client.patch_recipe.assert_called_once()
    call_args = client.patch_recipe.call_args
    assert call_args[0][0] == "my-recipe"
    tags_payload = call_args[0][1]["tags"]
    assert any(t["id"] == "new-tag-id" for t in tags_payload)


def test_review_tag_manager_reuses_existing_tag():
    client = _mock_client(existing_tags=[{"id": "existing-id", "name": "Parser: Needs Review"}])
    mgr = ReviewTagManager(client, "Parser: Needs Review", dry_run=False)
    result = mgr.ensure_tagged("my-recipe", [])
    assert result is True
    client.create_organizer_item.assert_not_called()
    call_args = client.patch_recipe.call_args
    tags_payload = call_args[0][1]["tags"]
    assert any(t["id"] == "existing-id" for t in tags_payload)


def test_ensure_tagged_preserves_existing_tags():
    client = _mock_client(existing_tags=[{"id": "review-id", "name": "Parser: Needs Review"}])
    mgr = ReviewTagManager(client, "Parser: Needs Review", dry_run=False)
    existing_recipe_tags = [{"id": "aaa", "name": "Dinner"}, {"id": "bbb", "name": "Quick"}]
    mgr.ensure_tagged("my-recipe", existing_recipe_tags)
    call_args = client.patch_recipe.call_args
    tags_payload = call_args[0][1]["tags"]
    tag_ids = {t["id"] for t in tags_payload}
    assert tag_ids == {"aaa", "bbb", "review-id"}


def test_ensure_tagged_noop_when_already_present():
    client = _mock_client(existing_tags=[{"id": "review-id", "name": "Parser: Needs Review"}])
    mgr = ReviewTagManager(client, "Parser: Needs Review", dry_run=False)
    existing_recipe_tags = [{"id": "review-id", "name": "Parser: Needs Review"}, {"id": "aaa", "name": "Dinner"}]
    result = mgr.ensure_tagged("my-recipe", existing_recipe_tags)
    assert result is False
    client.patch_recipe.assert_not_called()


def test_ensure_untagged_removes_review_tag():
    client = _mock_client(existing_tags=[{"id": "review-id", "name": "Parser: Needs Review"}])
    mgr = ReviewTagManager(client, "Parser: Needs Review", dry_run=False)
    existing_recipe_tags = [{"id": "review-id", "name": "Parser: Needs Review"}, {"id": "aaa", "name": "Dinner"}]
    result = mgr.ensure_untagged("my-recipe", existing_recipe_tags)
    assert result is True
    call_args = client.patch_recipe.call_args
    tags_payload = call_args[0][1]["tags"]
    tag_ids = {t["id"] for t in tags_payload}
    assert tag_ids == {"aaa"}


def test_ensure_untagged_noop_when_not_present():
    client = _mock_client(existing_tags=[{"id": "review-id", "name": "Parser: Needs Review"}])
    mgr = ReviewTagManager(client, "Parser: Needs Review", dry_run=False)
    existing_recipe_tags = [{"id": "aaa", "name": "Dinner"}]
    result = mgr.ensure_untagged("my-recipe", existing_recipe_tags)
    assert result is False
    client.patch_recipe.assert_not_called()


def test_dry_run_skips_patch():
    client = _mock_client(existing_tags=[{"id": "review-id", "name": "Parser: Needs Review"}])
    mgr = ReviewTagManager(client, "Parser: Needs Review", dry_run=True)
    result = mgr.ensure_tagged("my-recipe", [])
    assert result is True
    client.patch_recipe.assert_not_called()


def test_review_tag_name_case_insensitive_match():
    client = _mock_client(existing_tags=[{"id": "review-id", "name": "parser: needs review"}])
    mgr = ReviewTagManager(client, "Parser: Needs Review", dry_run=False)
    mgr.ensure_tagged("my-recipe", [])
    client.create_organizer_item.assert_not_called()
    call_args = client.patch_recipe.call_args
    tags_payload = call_args[0][1]["tags"]
    assert any(t["id"] == "review-id" for t in tags_payload)
