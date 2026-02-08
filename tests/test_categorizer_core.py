from mealie_organizer.categorizer_core import MealieCategorizer, parse_json_response


def test_parse_json_response_handles_json_fence():
    raw = "```json\n[{\"slug\":\"abc\",\"categories\":[\"Dinner\"],\"tags\":[\"Quick\"]}]\n```"
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["slug"] == "abc"


def test_parse_json_response_handles_unquoted_keys_and_trailing_comma():
    raw = "[{slug: 'abc', categories: ['Dinner'], tags: ['Quick'],}]"
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["categories"] == ["Dinner"]


def test_parse_json_response_returns_none_for_invalid_payload():
    parsed = parse_json_response("not-json-output")
    assert parsed is None


def test_update_recipe_metadata_dry_run_does_not_patch(monkeypatch, tmp_path, capsys):
    def _should_not_patch(*_args, **_kwargs):
        raise AssertionError("requests.patch should not run in dry-run mode")

    monkeypatch.setattr("mealie_organizer.categorizer_core.requests.patch", _should_not_patch)

    categorizer = MealieCategorizer(
        mealie_url="http://example/api",
        mealie_api_key="token",
        batch_size=1,
        max_workers=1,
        replace_existing=False,
        cache_file=tmp_path / "cache.json",
        query_text=lambda _prompt: "[]",
        provider_name="test",
        dry_run=True,
    )

    recipe = {"slug": "test-recipe", "recipeCategory": [], "tags": []}
    categories_by_name = {"dinner": {"id": "1", "name": "Dinner", "slug": "dinner", "groupId": None}}
    tags_by_name = {"quick": {"id": "2", "name": "Quick", "slug": "quick", "groupId": None}}

    updated = categorizer.update_recipe_metadata(recipe, ["Dinner"], ["Quick"], categories_by_name, tags_by_name)
    out = capsys.readouterr().out

    assert updated is True
    assert "[plan] test-recipe ->" in out


def test_process_batch_dry_run_does_not_skip_cached_recipe(monkeypatch, tmp_path):
    categorizer = MealieCategorizer(
        mealie_url="http://example/api",
        mealie_api_key="token",
        batch_size=1,
        max_workers=1,
        replace_existing=False,
        cache_file=tmp_path / "cache.json",
        query_text=lambda _prompt: "[]",
        provider_name="test",
        dry_run=True,
    )
    categorizer.cache = {"cached-recipe": {"categories": ["Dinner"], "tags": ["Quick"]}}

    recipe = {
        "slug": "cached-recipe",
        "name": "Cached Recipe",
        "ingredients": [],
        "recipeCategory": [],
        "tags": [],
    }

    prompts: list[str] = []

    def fake_safe_query_with_retry(prompt_text, retries=None):
        prompts.append(prompt_text)
        return [{"slug": "cached-recipe", "categories": ["Dinner"], "tags": ["Quick"]}]

    updates = []

    def fake_update(recipe_data, categories, tags, categories_lookup, tags_lookup):
        updates.append((recipe_data["slug"], categories, tags))
        return True

    monkeypatch.setattr(categorizer, "safe_query_with_retry", fake_safe_query_with_retry)
    monkeypatch.setattr(categorizer, "update_recipe_metadata", fake_update)

    categorizer.process_batch(
        [recipe],
        ["Dinner"],
        ["Quick"],
        {"dinner": {"name": "Dinner"}},
        {"quick": {"name": "Quick"}},
    )

    assert prompts
    assert updates == [("cached-recipe", ["Dinner"], ["Quick"])]


def test_process_batch_falls_back_to_per_recipe_when_batch_parse_fails(monkeypatch, tmp_path):
    categorizer = MealieCategorizer(
        mealie_url="http://example/api",
        mealie_api_key="token",
        batch_size=2,
        max_workers=1,
        replace_existing=False,
        cache_file=tmp_path / "cache.json",
        query_text=lambda _prompt: "[]",
        provider_name="test",
        dry_run=True,
    )

    recipes = [
        {"slug": "recipe-one", "name": "One", "ingredients": [], "recipeCategory": [], "tags": []},
        {"slug": "recipe-two", "name": "Two", "ingredients": [], "recipeCategory": [], "tags": []},
    ]

    def fake_safe_query_with_retry(prompt_text, retries=None):
        if "slug=recipe-one" in prompt_text and "slug=recipe-two" in prompt_text:
            return None
        if "slug=recipe-one" in prompt_text and "food recipe classifier" in prompt_text:
            return [{"slug": "recipe-one", "categories": ["Dinner"], "tags": ["Quick"]}]
        if "slug=recipe-two" in prompt_text and "food recipe classifier" in prompt_text:
            return [{"slug": "recipe-two", "categories": ["Dinner"], "tags": ["Comfort Food"]}]
        return None

    updates = []

    def fake_update(recipe_data, categories, tags, categories_lookup, tags_lookup):
        updates.append((recipe_data["slug"], categories, tags))
        return True

    monkeypatch.setattr(categorizer, "safe_query_with_retry", fake_safe_query_with_retry)
    monkeypatch.setattr(categorizer, "update_recipe_metadata", fake_update)

    categorizer.process_batch(
        recipes,
        ["Dinner"],
        ["Quick", "Comfort Food"],
        {"dinner": {"name": "Dinner"}},
        {
            "quick": {"name": "Quick"},
            "comfort food": {"name": "Comfort Food"},
        },
    )

    assert updates == [
        ("recipe-one", ["Dinner"], ["Quick"]),
        ("recipe-two", ["Dinner"], ["Comfort Food"]),
    ]


def test_process_batch_fallback_uses_split_category_and_tag_prompts(monkeypatch, tmp_path):
    categorizer = MealieCategorizer(
        mealie_url="http://example/api",
        mealie_api_key="token",
        batch_size=1,
        max_workers=1,
        replace_existing=False,
        cache_file=tmp_path / "cache.json",
        query_text=lambda _prompt: "[]",
        provider_name="test",
        dry_run=True,
    )

    recipe = {"slug": "split-recipe", "name": "Split", "ingredients": [], "recipeCategory": [], "tags": []}

    def fake_safe_query_with_retry(prompt_text, retries=None):
        if "food recipe classifier" in prompt_text:
            return None
        if "food recipe category selector" in prompt_text:
            return [{"slug": "split-recipe", "categories": ["Dinner"]}]
        if "food recipe tagging assistant" in prompt_text:
            return [{"slug": "split-recipe", "tags": ["Quick"]}]
        return None

    updates = []

    def fake_update(recipe_data, categories, tags, categories_lookup, tags_lookup):
        updates.append((recipe_data["slug"], categories, tags))
        return True

    monkeypatch.setattr(categorizer, "safe_query_with_retry", fake_safe_query_with_retry)
    monkeypatch.setattr(categorizer, "update_recipe_metadata", fake_update)

    categorizer.process_batch(
        [recipe],
        ["Dinner"],
        ["Quick"],
        {"dinner": {"name": "Dinner"}},
        {"quick": {"name": "Quick"}},
    )

    assert updates == [("split-recipe", ["Dinner"], ["Quick"])]


def test_process_batch_does_not_skip_cached_when_tags_missing(monkeypatch, tmp_path):
    categorizer = MealieCategorizer(
        mealie_url="http://example/api",
        mealie_api_key="token",
        batch_size=1,
        max_workers=1,
        replace_existing=False,
        cache_file=tmp_path / "cache.json",
        query_text=lambda _prompt: "[]",
        provider_name="test",
        dry_run=False,
    )
    categorizer.cache = {"needs-tags": {"categories": ["Sauce"], "tags": []}}

    recipe = {
        "slug": "needs-tags",
        "name": "Needs Tags",
        "ingredients": [],
        "recipeCategory": [{"name": "Sauce", "slug": "sauce"}],
        "tags": [],
    }

    def fake_safe_query_with_retry(prompt_text, retries=None):
        return [{"slug": "needs-tags", "categories": ["Sauce"], "tags": ["Quick"]}]

    updates = []

    def fake_update(recipe_data, categories, tags, categories_lookup, tags_lookup):
        updates.append((recipe_data["slug"], categories, tags))
        return True

    monkeypatch.setattr(categorizer, "safe_query_with_retry", fake_safe_query_with_retry)
    monkeypatch.setattr(categorizer, "update_recipe_metadata", fake_update)

    categorizer.process_batch(
        [recipe],
        ["Sauce"],
        ["Quick"],
        {"sauce": {"name": "Sauce"}},
        {"quick": {"name": "Quick"}},
    )

    assert updates == [("needs-tags", ["Sauce"], ["Quick"])]
