import pytest

from mealie_organizer.taxonomy_manager import (
    MealieTaxonomyManager,
    normalize_payload_items,
    resolve_refresh_replace_flags,
)


def test_normalize_payload_items_from_strings():
    items = normalize_payload_items(["Breakfast", "Dinner"])
    assert items == [{"name": "Breakfast"}, {"name": "Dinner"}]


def test_normalize_payload_items_from_objects():
    items = normalize_payload_items([{"name": "Breakfast"}, {"name": "Dinner", "groupId": "g1"}])
    assert items == [{"name": "Breakfast"}, {"name": "Dinner", "groupId": "g1"}]


def test_normalize_payload_items_rejects_invalid_type():
    with pytest.raises(ValueError):
        normalize_payload_items([1, 2, 3])


def test_noisy_tag_detection():
    assert MealieTaxonomyManager.noisy_tag("How To Make Turkey Gravy") is True
    assert MealieTaxonomyManager.noisy_tag("Weeknight") is False


def test_delete_all_dry_run_does_not_delete(monkeypatch, capsys):
    manager = MealieTaxonomyManager("http://example/api", "token", dry_run=True)

    monkeypatch.setattr(
        manager,
        "existing_lookup",
        lambda _endpoint: {"quick": {"id": "1", "name": "Quick"}},
    )

    def _should_not_delete(*_args, **_kwargs):
        raise AssertionError("session.delete should not run in dry-run mode")

    monkeypatch.setattr(manager.session, "delete", _should_not_delete)

    manager.delete_all("tags")
    out = capsys.readouterr().out
    assert "[plan] Delete: Quick" in out


def test_import_items_replace_dry_run_plans_add(monkeypatch, capsys):
    manager = MealieTaxonomyManager("http://example/api", "token", dry_run=True)

    monkeypatch.setattr(
        manager,
        "existing_lookup",
        lambda _endpoint: {"dinner": {"id": "5", "name": "Dinner"}},
    )

    def _should_not_post(*_args, **_kwargs):
        raise AssertionError("session.post should not run in dry-run mode")

    monkeypatch.setattr(manager.session, "post", _should_not_post)

    manager.import_items("categories", [{"name": "Dinner"}], replace=True)
    out = capsys.readouterr().out
    assert "[plan] Add: Dinner" in out
    assert "[skip] Exists: Dinner" not in out


def test_resolve_refresh_replace_flags_merge_defaults_to_non_destructive():
    assert resolve_refresh_replace_flags("merge", False, False) == (False, False)


def test_resolve_refresh_replace_flags_merge_honors_partial_replace_flags():
    assert resolve_refresh_replace_flags("merge", True, False) == (True, False)


def test_resolve_refresh_replace_flags_replace_forces_full_replace():
    assert resolve_refresh_replace_flags("replace", False, False) == (True, True)
