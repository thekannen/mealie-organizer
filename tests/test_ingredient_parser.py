from __future__ import annotations

from cookdex import ingredient_parser


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
