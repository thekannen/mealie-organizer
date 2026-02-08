import pytest

from mealie_organizer.cookbook_manager import MealieCookbookManager, normalize_cookbook_items


def test_normalize_cookbook_items_minimal_defaults():
    items = normalize_cookbook_items([
        {
            "name": "Weeknight Dinners",
            "queryFilterString": "tags.name CONTAINS_ANY [\"Quick\"]",
        }
    ])

    assert items[0]["name"] == "Weeknight Dinners"
    assert items[0]["description"] == ""
    assert items[0]["public"] is False
    assert items[0]["position"] == 1


def test_normalize_cookbook_items_rejects_non_list():
    with pytest.raises(ValueError):
        normalize_cookbook_items({"name": "Invalid"})


def test_sync_cookbooks_dry_run_plans_create_update_delete(monkeypatch, capsys):
    manager = MealieCookbookManager("http://example/api", "token", dry_run=True)

    monkeypatch.setattr(
        manager,
        "build_name_id_maps",
        lambda: ({"meal prep": "tag-id-1", "weeknight": "tag-id-2", "quick": "tag-id-3"}, {"dinner": "cat-id-1"}),
    )

    monkeypatch.setattr(
        manager,
        "get_cookbooks",
        lambda: [
            {
                "id": "1",
                "name": "Weeknight Dinners",
                "description": "Old",
                "queryFilterString": "old",
                "public": False,
                "position": 1,
            },
            {
                "id": "2",
                "name": "To Remove",
                "description": "",
                "queryFilterString": "",
                "public": False,
                "position": 9,
            },
        ],
    )


    desired = [
        {
            "name": "Weeknight Dinners",
            "description": "New",
            "queryFilterString": "new",
            "public": False,
            "position": 1,
        },
        {
            "name": "Meal Prep",
            "description": "",
            "queryFilterString": "tags.name CONTAINS_ANY [\"Meal Prep\"]",
            "public": False,
            "position": 2,
        },
    ]

    created, updated, deleted, skipped, failed = manager.sync_cookbooks(desired, replace=True)
    out = capsys.readouterr().out

    assert "[plan] Update cookbook: Weeknight Dinners" in out
    assert "[plan] Create cookbook: Meal Prep" in out
    assert "[plan] Delete cookbook: To Remove" in out
    assert (created, updated, deleted, skipped, failed) == (1, 1, 1, 0, 0)


def test_normalize_cookbook_items_converts_contains_any_to_in():
    items = normalize_cookbook_items(
        [
            {
                "name": "Quick Meals",
                "queryFilterString": "tags.name CONTAINS_ANY [\"Quick\", \"Weeknight\"]",
            }
        ]
    )

    assert items[0]["queryFilterString"] == 'tags.name IN ["Quick", "Weeknight"]'


def test_compile_query_filter_for_editor_converts_name_filters_to_ids():
    manager = MealieCookbookManager("http://example/api", "token", dry_run=True)
    query_filter = (
        'recipeCategory.name IN ["Dinner"] AND '
        'tags.name IN ["Weeknight", "30-Minute"]'
    )

    compiled = manager.compile_query_filter_for_editor(
        query_filter,
        {"dinner": "cat-1"},
        {"weeknight": "tag-1", "30-minute": "tag-2"},
    )

    assert compiled == 'recipe_category.id IN ["cat-1"] AND tags.id IN ["tag-1","tag-2"]'


def test_compile_query_filter_for_editor_normalizes_recipe_category_id_field():
    manager = MealieCookbookManager("http://example/api", "token", dry_run=True)
    query_filter = 'recipeCategory.id IN ["cat-1"]'

    compiled = manager.compile_query_filter_for_editor(
        query_filter,
        {},
        {},
    )

    assert compiled == 'recipe_category.id IN ["cat-1"]'


def test_compile_query_filter_for_editor_keeps_unknown_names():
    manager = MealieCookbookManager("http://example/api", "token", dry_run=True)
    query_filter = 'tags.name IN ["Unknown Tag"]'

    compiled = manager.compile_query_filter_for_editor(
        query_filter,
        {},
        {},
    )

    assert compiled == query_filter
