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
