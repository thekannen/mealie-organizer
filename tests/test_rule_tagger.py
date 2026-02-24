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
