from __future__ import annotations

from cookdex.rule_tagger import RecipeRuleTagger


def test_api_rule_skips_when_target_missing_in_skip_mode(monkeypatch) -> None:
    tagger = RecipeRuleTagger(dry_run=True, use_db=False, missing_targets="skip")
    tagger._missing_target_skips = 0

    def fake_get_or_create(*args, **kwargs):
        return None

    monkeypatch.setattr(tagger, "_api_get_or_create_tag", fake_get_or_create)
    matched_count = tagger._api_apply_text_rule(
        all_recipes=[{"slug": "r1", "name": "breakfast bowl", "description": ""}],
        rule={"tag": "Breakfast", "pattern": "breakfast"},
        mealie_url="http://example/api",
        headers={},
        tag_cache={},
        allow_create=False,
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
        "_api_get_or_create_tag",
        lambda *args, **kwargs: {"id": "t1", "name": "Breakfast", "slug": "breakfast"},
    )
    matched_count = tagger._api_apply_text_rule(
        all_recipes=[
            {"slug": "r1", "name": "Veggie Bowl", "description": "great breakfast"},
            {"slug": "r2", "name": "Breakfast Casserole", "description": ""},
        ],
        rule={"tag": "Breakfast", "pattern": "breakfast", "match_on": "name"},
        mealie_url="http://example/api",
        headers={},
        tag_cache={},
        allow_create=False,
    )
    assert matched_count == 1


def test_api_text_rule_disabled_is_skipped(monkeypatch) -> None:
    tagger = RecipeRuleTagger(dry_run=True, use_db=False, missing_targets="skip")

    called = {"value": False}

    def _fake_get_or_create(*args, **kwargs):
        called["value"] = True
        return {"id": "t1", "name": "Breakfast", "slug": "breakfast"}

    monkeypatch.setattr(tagger, "_api_get_or_create_tag", _fake_get_or_create)
    matched_count = tagger._api_apply_text_rule(
        all_recipes=[{"slug": "r1", "name": "Breakfast Bowl", "description": ""}],
        rule={"tag": "Breakfast", "pattern": "breakfast", "enabled": False},
        mealie_url="http://example/api",
        headers={},
        tag_cache={},
        allow_create=False,
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
    )
    assert matched_count == 1
    assert db.match_on == "description"
