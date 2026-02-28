from cookdex.categorizer_core import MealieCategorizer, parse_json_response


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


def test_parse_json_response_returns_none_for_empty_and_none():
    assert parse_json_response("") is None
    assert parse_json_response("   ") is None
    assert parse_json_response(None) is None


def test_parse_json_response_valid_json_passes_through():
    raw = '[{"slug":"abc","categories":["Dinner"],"tags":["Quick"],"tools":["Blender"]}]'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["slug"] == "abc"
    assert parsed[0]["tools"] == ["Blender"]


def test_parse_json_response_does_not_corrupt_urls_in_values():
    raw = '[{"slug":"test","url":"https://example.com","categories":["Dinner"]}]'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["url"] == "https://example.com"


def test_parse_json_response_does_not_double_quote_keys():
    raw = '{"slug": "test", "categories": ["Dinner"]}'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, dict) or isinstance(parsed, list)
    if isinstance(parsed, dict):
        assert parsed["slug"] == "test"


def test_parse_json_response_preserves_apostrophes():
    raw = '[{"slug":"grandmas-pie","tags":["Grandma\'s Favorite"]}]'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert "Grandma's Favorite" in parsed[0]["tags"]


def test_parse_json_response_handles_preamble_text():
    raw = "Here are the categorized recipes:\n\n" + \
          '[{"slug":"abc","categories":["Dinner"],"tags":["Quick"]}]'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["slug"] == "abc"


def test_parse_json_response_handles_postamble_text():
    raw = '[{"slug":"abc","categories":["Dinner"]}]\n\nI hope this helps!'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["slug"] == "abc"


def test_parse_json_response_handles_truncated_array():
    raw = '[{"slug":"abc","categories":["Dinner"]},{"slug":"def","categories":["Lu'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert len(parsed) >= 1
    assert parsed[0]["slug"] == "abc"


def test_parse_json_response_handles_truncated_after_comma():
    raw = '[{"slug":"abc","categories":["Dinner"]},'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["slug"] == "abc"


def test_parse_json_response_smart_double_quotes():
    raw = '[{\u201cslug\u201d: \u201cabc\u201d, \u201ccategories\u201d: [\u201cDinner\u201d]}]'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["slug"] == "abc"


def test_parse_json_response_unwraps_object_wrapping_array():
    raw = '{"results": [{"slug":"abc","categories":["Dinner"]}]}'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["slug"] == "abc"


def test_parse_json_response_nested_brackets_in_values():
    raw = 'Result: [{"slug":"test","note":"uses [brackets] in text","categories":["Dinner"]}]'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["note"] == "uses [brackets] in text"


def test_update_recipe_metadata_dry_run_does_not_patch(monkeypatch, tmp_path, capsys):
    def _should_not_patch(*_args, **_kwargs):
        raise AssertionError("requests.patch should not run in dry-run mode")

    monkeypatch.setattr("cookdex.categorizer_core.requests.patch", _should_not_patch)

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

    recipe = {"slug": "test-recipe", "recipeCategory": [], "tags": [], "tools": []}
    categories_by_name = {"dinner": {"id": "1", "name": "Dinner", "slug": "dinner", "groupId": None}}
    tags_by_name = {"quick": {"id": "2", "name": "Quick", "slug": "quick", "groupId": None}}
    tools_by_name = {"blender": {"id": "3", "name": "Blender", "slug": "blender", "groupId": None}}

    updated = categorizer.update_recipe_metadata(
        recipe,
        ["Dinner"],
        ["Quick"],
        ["Blender"],
        categories_by_name,
        tags_by_name,
        tools_by_name,
    )
    out = capsys.readouterr().out

    assert updated is True
    assert "[plan] test-recipe:" in out


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
    categorizer.cache = {"cached-recipe": {"categories": ["Dinner"], "tags": ["Quick"], "tools": ["Blender"]}}

    recipe = {
        "slug": "cached-recipe",
        "name": "Cached Recipe",
        "ingredients": [],
        "recipeCategory": [],
        "tags": [],
        "tools": [],
    }

    prompts: list[str] = []

    def fake_safe_query_with_retry(prompt_text, retries=None):
        prompts.append(prompt_text)
        return [{"slug": "cached-recipe", "categories": ["Dinner"], "tags": ["Quick"], "tools": ["Blender"]}]

    updates = []

    def fake_update(recipe_data, categories, tags, tools, categories_lookup, tags_lookup, tools_lookup):
        updates.append((recipe_data["slug"], categories, tags, tools))
        return True

    monkeypatch.setattr(categorizer, "safe_query_with_retry", fake_safe_query_with_retry)
    monkeypatch.setattr(categorizer, "update_recipe_metadata", fake_update)

    categorizer.process_batch(
        [recipe],
        ["Dinner"],
        ["Quick"],
        ["Blender"],
        {"dinner": {"name": "Dinner"}},
        {"quick": {"name": "Quick"}},
        {"blender": {"name": "Blender"}},
    )

    assert prompts
    assert updates == [("cached-recipe", ["Dinner"], ["Quick"], ["Blender"])]


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
        {"slug": "recipe-one", "name": "One", "ingredients": [], "recipeCategory": [], "tags": [], "tools": []},
        {"slug": "recipe-two", "name": "Two", "ingredients": [], "recipeCategory": [], "tags": [], "tools": []},
    ]

    def fake_safe_query_with_retry(prompt_text, retries=None):
        if "slug=recipe-one" in prompt_text and "slug=recipe-two" in prompt_text:
            return None
        if "slug=recipe-one" in prompt_text and "food recipe classifier" in prompt_text:
            return [{"slug": "recipe-one", "categories": ["Dinner"], "tags": ["Quick"], "tools": ["Blender"]}]
        if "slug=recipe-two" in prompt_text and "food recipe classifier" in prompt_text:
            return [{"slug": "recipe-two", "categories": ["Dinner"], "tags": ["Comfort Food"], "tools": ["Dutch Oven"]}]
        return None

    updates = []

    def fake_update(recipe_data, categories, tags, tools, categories_lookup, tags_lookup, tools_lookup):
        updates.append((recipe_data["slug"], categories, tags, tools))
        return True

    monkeypatch.setattr(categorizer, "safe_query_with_retry", fake_safe_query_with_retry)
    monkeypatch.setattr(categorizer, "update_recipe_metadata", fake_update)

    categorizer.process_batch(
        recipes,
        ["Dinner"],
        ["Quick", "Comfort Food"],
        ["Blender", "Dutch Oven"],
        {"dinner": {"name": "Dinner"}},
        {
            "quick": {"name": "Quick"},
            "comfort food": {"name": "Comfort Food"},
        },
        {"blender": {"name": "Blender"}, "dutch oven": {"name": "Dutch Oven"}},
    )

    assert updates == [
        ("recipe-one", ["Dinner"], ["Quick"], ["Blender"]),
        ("recipe-two", ["Dinner"], ["Comfort Food"], ["Dutch Oven"]),
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

    recipe = {"slug": "split-recipe", "name": "Split", "ingredients": [], "recipeCategory": [], "tags": [], "tools": []}

    def fake_safe_query_with_retry(prompt_text, retries=None):
        if "food recipe classifier" in prompt_text:
            return None
        if "food recipe category selector" in prompt_text:
            return [{"slug": "split-recipe", "categories": ["Dinner"]}]
        if "food recipe tagging assistant" in prompt_text:
            return [{"slug": "split-recipe", "tags": ["Quick"]}]
        if "food recipe kitchen tool selector" in prompt_text:
            return [{"slug": "split-recipe", "tools": ["Blender"]}]
        return None

    updates = []

    def fake_update(recipe_data, categories, tags, tools, categories_lookup, tags_lookup, tools_lookup):
        updates.append((recipe_data["slug"], categories, tags, tools))
        return True

    monkeypatch.setattr(categorizer, "safe_query_with_retry", fake_safe_query_with_retry)
    monkeypatch.setattr(categorizer, "update_recipe_metadata", fake_update)

    categorizer.process_batch(
        [recipe],
        ["Dinner"],
        ["Quick"],
        ["Blender"],
        {"dinner": {"name": "Dinner"}},
        {"quick": {"name": "Quick"}},
        {"blender": {"name": "Blender"}},
    )

    assert updates == [("split-recipe", ["Dinner"], ["Quick"], ["Blender"])]


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
        "tools": [{"name": "Blender", "slug": "blender"}],
    }

    def fake_safe_query_with_retry(prompt_text, retries=None):
        return [{"slug": "needs-tags", "categories": ["Sauce"], "tags": ["Quick"], "tools": ["Blender"]}]

    updates = []

    def fake_update(recipe_data, categories, tags, tools, categories_lookup, tags_lookup, tools_lookup):
        updates.append((recipe_data["slug"], categories, tags, tools))
        return True

    monkeypatch.setattr(categorizer, "safe_query_with_retry", fake_safe_query_with_retry)
    monkeypatch.setattr(categorizer, "update_recipe_metadata", fake_update)

    categorizer.process_batch(
        [recipe],
        ["Sauce"],
        ["Quick"],
        ["Blender"],
        {"sauce": {"name": "Sauce"}},
        {"quick": {"name": "Quick"}},
        {"blender": {"name": "Blender"}},
    )

    assert updates == [("needs-tags", ["Sauce"], ["Quick"], ["Blender"])]


def test_update_recipe_metadata_cache_write_permission_error_does_not_crash(monkeypatch, tmp_path, capsys):
    class _PatchResponse:
        status_code = 200
        text = ""

    monkeypatch.setattr("cookdex.categorizer_core.requests.patch", lambda *_args, **_kwargs: _PatchResponse())

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

    original_open = type(categorizer.cache_file).open

    def fake_open(path_obj, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if path_obj == categorizer.cache_file and "w" in mode:
            raise PermissionError("permission denied")
        return original_open(path_obj, *args, **kwargs)

    monkeypatch.setattr("pathlib.Path.open", fake_open)

    recipe = {"slug": "perm-denied-recipe", "recipeCategory": [], "tags": [], "tools": []}
    categories_by_name = {"dinner": {"id": "1", "name": "Dinner", "slug": "dinner", "groupId": None}}
    tags_by_name = {"quick": {"id": "2", "name": "Quick", "slug": "quick", "groupId": None}}
    tools_by_name = {"blender": {"id": "3", "name": "Blender", "slug": "blender", "groupId": None}}

    updated = categorizer.update_recipe_metadata(
        recipe,
        ["Dinner"],
        ["Quick"],
        ["Blender"],
        categories_by_name,
        tags_by_name,
        tools_by_name,
    )
    out = capsys.readouterr().out

    assert updated is True
    assert categorizer.cache_enabled is False
    assert "Cache disabled: cannot write" in out


# ---------------------------------------------------------------------------
# Output protocol tests
# ---------------------------------------------------------------------------


def test_plan_line_uses_colon_separator(monkeypatch, tmp_path, capsys):
    """[plan] lines must use ':' separator for frontend parser compatibility."""
    monkeypatch.setattr("cookdex.categorizer_core.requests.patch", lambda *a, **k: None)

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

    recipe = {"slug": "my-recipe", "recipeCategory": [], "tags": [], "tools": []}
    categorizer.update_recipe_metadata(
        recipe,
        ["Dinner"],
        [],
        [],
        {"dinner": {"id": "1", "name": "Dinner", "slug": "dinner", "groupId": None}},
        {},
        {},
    )
    out = capsys.readouterr().out
    assert "[plan] my-recipe: cats=Dinner" in out
    assert "->" not in out


def test_ok_line_has_idx_total(monkeypatch, tmp_path, capsys):
    """[ok] lines must have idx/total format for frontend progress bar."""
    class _PatchResponse:
        status_code = 200
        text = ""

    monkeypatch.setattr("cookdex.categorizer_core.requests.patch", lambda *a, **k: _PatchResponse())

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
    categorizer.set_progress_total(10)
    categorizer.advance_progress(3)

    recipe = {"slug": "ok-recipe", "recipeCategory": [], "tags": [], "tools": []}
    categorizer.update_recipe_metadata(
        recipe,
        ["Dinner"],
        [],
        [],
        {"dinner": {"id": "1", "name": "Dinner", "slug": "dinner", "groupId": None}},
        {},
        {},
    )
    out = capsys.readouterr().out
    assert "[ok] 3/10 ok-recipe" in out


def test_summary_is_json_with_title(tmp_path, capsys):
    """print_summary must emit single-line JSON with __title__."""
    import json as _json

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
    categorizer.set_progress_total(100)
    categorizer.advance_progress(100)
    categorizer.print_summary()
    out = capsys.readouterr().out

    assert out.startswith("[summary] ")
    json_str = out.strip().removeprefix("[summary] ")
    data = _json.loads(json_str)
    assert data["__title__"] == "AI Categorizer"
    assert "Recipes Processed" in data
    assert "Categories Added" in data


def test_parse_json_response_unwraps_json_object_mode():
    """ChatGPT json_object mode wraps arrays in an object — must unwrap."""
    raw = '{"results": [{"slug":"a","categories":["Dinner"]},{"slug":"b","tags":["Quick"]}]}'
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert parsed[0]["slug"] == "a"
    assert parsed[1]["slug"] == "b"


def test_parse_json_response_unwraps_various_wrapper_keys():
    """The unwrapper should work regardless of the wrapper key name."""
    for key in ("results", "recipes", "data", "items"):
        raw = f'{{"{key}": [{{"slug":"test","categories":["Lunch"]}}]}}'
        parsed = parse_json_response(raw)
        assert isinstance(parsed, list), f"Failed for wrapper key '{key}'"
        assert parsed[0]["slug"] == "test"
