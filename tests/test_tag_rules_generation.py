from __future__ import annotations

from cookdex.tag_rules_generation import build_default_tag_rules


def test_build_default_tag_rules_applies_category_overrides() -> None:
    payload = build_default_tag_rules(
        tags=[{"name": "BBQ"}],
        categories=[{"name": "Dinner"}, {"name": "Originals"}, {"name": "Custom Bucket"}],
        tools=[{"name": "Air Fryer"}],
    )

    categories = {row["category"]: row for row in payload["text_categories"]}
    assert categories["Dinner"]["match_on"] == "name"
    assert "stir" in categories["Dinner"]["pattern"].lower()
    assert categories["Custom Bucket"]["match_on"] == "name"

    bbq = next(row for row in payload["text_tags"] if row["tag"] == "BBQ")
    assert "barbecue" in bbq["pattern"].lower()


def test_build_default_tag_rules_preserves_core_sections() -> None:
    payload = build_default_tag_rules(
        tags=[{"name": "Vegan"}],
        categories=[{"name": "Soup"}],
        tools=[{"name": "Stand Mixer"}],
    )
    assert isinstance(payload["ingredient_tags"], list)
    assert isinstance(payload["ingredient_categories"], list)
    assert payload["tool_tags"][0]["tool"] == "Stand Mixer"
