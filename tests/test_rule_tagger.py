from __future__ import annotations

import json
from pathlib import Path

from cookdex.rule_tagger import RecipeRuleTagger, _TAG, _CAT


def test_api_rule_skips_when_target_missing_in_skip_mode(monkeypatch) -> None:
    tagger = RecipeRuleTagger(dry_run=True, use_db=False, missing_targets="skip")
    tagger._missing_target_skips = 0

    monkeypatch.setattr(
        tagger,
        "_api_get_or_create",
        lambda *args, **kwargs: None,
    )
    matched_count = tagger._api_apply_text_rule(
        all_recipes=[{"slug": "r1", "name": "breakfast bowl", "description": ""}],
        rule={"tag": "Breakfast", "pattern": "breakfast"},
        spec=_TAG,
        mealie_url="http://example/api",
        headers={},
        cache={},
    )
    assert matched_count == 0
    assert tagger._missing_target_skips == 1


def test_db_resolve_tag_id_skip_mode_does_not_create() -> None:
    class _FakeDB:
        def lookup_tag_id(self, name: str, group_id: str):
            return None

        def ensure_tag(self, name: str, group_id: str, *, dry_run: bool = True):
            raise AssertionError("ensure_tag should not be called in skip mode")

    tagger = RecipeRuleTagger(dry_run=True, use_db=True, missing_targets="skip")
    tagger._missing_target_skips = 0
    resolved = tagger._db_resolve_tag_id(_FakeDB(), "group-1", "Missing Tag")
    assert resolved is None
    assert tagger._missing_target_skips == 1


def test_db_resolve_tag_id_create_mode_uses_ensure() -> None:
    class _FakeDB:
        def lookup_tag_id(self, name: str, group_id: str):
            return None

        def ensure_tag(self, name: str, group_id: str, *, dry_run: bool = True):
            return "tag-123"

    tagger = RecipeRuleTagger(dry_run=True, use_db=True, missing_targets="create")
    resolved = tagger._db_resolve_tag_id(_FakeDB(), "group-1", "Created Tag")
    assert resolved == "tag-123"


def test_api_text_rule_respects_match_on_name(monkeypatch) -> None:
    tagger = RecipeRuleTagger(dry_run=True, use_db=False, missing_targets="skip")

    monkeypatch.setattr(
        tagger,
        "_api_get_or_create",
        lambda *args, **kwargs: {"id": "t1", "name": "Breakfast", "slug": "breakfast"},
    )
    matched_count = tagger._api_apply_text_rule(
        all_recipes=[
            {"slug": "r1", "name": "Veggie Bowl", "description": "great breakfast"},
            {"slug": "r2", "name": "Breakfast Casserole", "description": ""},
        ],
        rule={"tag": "Breakfast", "pattern": "breakfast", "match_on": "name"},
        spec=_TAG,
        mealie_url="http://example/api",
        headers={},
        cache={},
    )
    assert matched_count == 1


def test_api_text_rule_disabled_is_skipped(monkeypatch) -> None:
    tagger = RecipeRuleTagger(dry_run=True, use_db=False, missing_targets="skip")

    called = {"value": False}

    def _fake_get_or_create(*args, **kwargs):
        called["value"] = True
        return {"id": "t1", "name": "Breakfast", "slug": "breakfast"}

    monkeypatch.setattr(tagger, "_api_get_or_create", _fake_get_or_create)
    matched_count = tagger._api_apply_text_rule(
        all_recipes=[{"slug": "r1", "name": "Breakfast Bowl", "description": ""}],
        rule={"tag": "Breakfast", "pattern": "breakfast", "enabled": False},
        spec=_TAG,
        mealie_url="http://example/api",
        headers={},
        cache={},
    )
    assert matched_count == 0
    assert called["value"] is False


def test_db_text_rule_passes_match_on_to_db() -> None:
    class _FakeDB:
        def __init__(self) -> None:
            self.match_on = None

        def find_recipe_ids_by_text(self, group_id: str, pattern: str, *, match_on: str = "both"):
            self.match_on = match_on
            return ["r1"]

        def link_tag(self, recipe_id: str, tag_id: str, *, dry_run: bool = True):
            return None

    tagger = RecipeRuleTagger(dry_run=True, use_db=True, missing_targets="skip")
    db = _FakeDB()
    tagger._db_resolve_tag_id = lambda *_args, **_kwargs: "tag-1"  # type: ignore[method-assign]

    matched_count = tagger._db_apply_text_rule(
        db=db,  # type: ignore[arg-type]
        group_id="group-1",
        rule={"tag": "Breakfast", "pattern": "breakfast", "match_on": "description"},
        spec=_TAG,
    )
    assert matched_count == 1
    assert db.match_on == "description"


def test_db_text_category_rule_uses_cat_spec() -> None:
    class _FakeDB:
        def find_recipe_ids_by_text(self, group_id: str, pattern: str, *, match_on: str = "both"):
            return ["r1"]

        def link_category(self, recipe_id: str, cat_id: str, *, dry_run: bool = True):
            return None

    tagger = RecipeRuleTagger(dry_run=True, use_db=True, missing_targets="skip")
    db = _FakeDB()
    tagger._db_resolve_category_id = lambda *_args, **_kwargs: "cat-1"  # type: ignore[method-assign]

    matched_count = tagger._db_apply_text_rule(
        db=db,  # type: ignore[arg-type]
        group_id="group-1",
        rule={"category": "Dinner", "pattern": "dinner"},
        spec=_CAT,
    )
    assert matched_count == 1


def test_from_taxonomy_derives_rules(tmp_path: Path, monkeypatch) -> None:
    """from_taxonomy reads taxonomy JSON files and derives rules at runtime."""
    taxonomy_dir = tmp_path / "configs" / "taxonomy"
    taxonomy_dir.mkdir(parents=True)
    (taxonomy_dir / "tags.json").write_text(json.dumps([{"name": "Quick"}, {"name": "Vegan"}]))
    (taxonomy_dir / "categories.json").write_text(json.dumps([{"name": "Dinner"}]))
    (taxonomy_dir / "tools.json").write_text(json.dumps([{"name": "Air Fryer"}]))

    monkeypatch.setattr("cookdex.rule_tagger.REPO_ROOT", tmp_path)

    tagger = RecipeRuleTagger.from_taxonomy(dry_run=True)
    assert tagger._preloaded_rules is not None
    assert len(tagger._preloaded_rules.get("text_tags", [])) == 2
    assert len(tagger._preloaded_rules.get("text_categories", [])) == 1
    assert len(tagger._preloaded_rules.get("tool_tags", [])) == 1


def test_from_taxonomy_empty_when_no_files(tmp_path: Path, monkeypatch) -> None:
    """from_taxonomy with missing files produces zero rules without crashing."""
    monkeypatch.setattr("cookdex.rule_tagger.REPO_ROOT", tmp_path)
    tagger = RecipeRuleTagger.from_taxonomy(dry_run=True)
    assert tagger._preloaded_rules is not None
    for section in tagger._preloaded_rules.values():
        assert section == []


def test_preloaded_rules_skip_file_loading() -> None:
    """When _rules is provided, run() should use them instead of loading a file."""
    rules = {
        "ingredient_tags": [],
        "ingredient_categories": [],
        "text_tags": [{"tag": "Test", "pattern": "test"}],
        "text_categories": [],
        "tool_tags": [],
    }
    tagger = RecipeRuleTagger(dry_run=True, _rules=rules)
    assert tagger._preloaded_rules is rules
