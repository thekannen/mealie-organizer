import pytest

from cookdex.cookbook_filters import (
    CookbookFilterParseError,
    normalize_query_filter_string,
    parse_cookbook_filter,
    serialize_cookbook_filter,
)


def test_parse_cookbook_filter_supports_aliases_foods_and_operators():
    clauses = parse_cookbook_filter(
        'recipeCategory.name IN ["Dinner"] AND '
        'recipe_ingredient.food.name NOT IN ["Beef"] AND '
        'tools.id CONTAINS ALL ["tool-1"]'
    )

    assert [(clause.resource, clause.identifier, clause.operator, clause.values) for clause in clauses] == [
        ("categories", "name", "IN", ("Dinner",)),
        ("foods", "name", "NOT IN", ("Beef",)),
        ("tools", "id", "CONTAINS ALL", ("tool-1",)),
    ]


def test_parse_cookbook_filter_keeps_and_and_brackets_inside_quoted_values():
    clauses = parse_cookbook_filter('tags.name IN ["Salt AND Pepper", "Tag ] Name"]')

    assert clauses[0].values == ("Salt AND Pepper", "Tag ] Name")
    assert serialize_cookbook_filter(clauses) == 'tags.name IN ["Salt AND Pepper", "Tag ] Name"]'


def test_parse_cookbook_filter_single_quotes_preserve_non_ascii_text():
    clauses = parse_cookbook_filter("recipeCategory.name IN ['Crème brûlée']")

    assert clauses[0].values == ("Crème brûlée",)


def test_parse_cookbook_filter_empty_value_list_stays_empty():
    clauses = parse_cookbook_filter("tags.id IN []")

    assert clauses[0].values == ()
    assert serialize_cookbook_filter(clauses) == "tags.id IN []"


def test_normalize_query_filter_string_preserves_contains_any_compatibility():
    assert (
        normalize_query_filter_string(' tags.name   CONTAINS_ANY   ["Quick", "Weeknight"] ')
        == 'tags.name IN ["Quick", "Weeknight"]'
    )


def test_parse_cookbook_filter_rejects_unsupported_fields():
    with pytest.raises(CookbookFilterParseError) as exc:
        parse_cookbook_filter('unknown.field IN ["x"]')

    assert exc.value.code == "cookbook_invalid_field"
