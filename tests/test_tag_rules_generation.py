from __future__ import annotations

from cookdex.tag_rules_generation import build_default_tag_rules, rule_pattern_for_name


def test_build_default_tag_rules_derives_patterns_from_names() -> None:
    payload = build_default_tag_rules(
        tags=[{"name": "BBQ"}, {"name": "Comfort Food"}],
        categories=[{"name": "Dinner"}, {"name": "Originals"}, {"name": "Custom Bucket"}],
        tools=[{"name": "Air Fryer"}],
    )

    categories = {row["category"]: row for row in payload["text_categories"]}
    # All categories default to match_on="name"
    assert categories["Dinner"]["match_on"] == "name"
    assert categories["Custom Bucket"]["match_on"] == "name"
    # Patterns are derived from the taxonomy name itself
    assert categories["Dinner"]["pattern"] == rule_pattern_for_name("Dinner")
    assert categories["Custom Bucket"]["pattern"] == rule_pattern_for_name("Custom Bucket")

    tags = {row["tag"]: row for row in payload["text_tags"]}
    assert tags["BBQ"]["pattern"] == rule_pattern_for_name("BBQ")
    assert tags["Comfort Food"]["pattern"] == rule_pattern_for_name("Comfort Food")


def test_build_default_tag_rules_preserves_core_sections() -> None:
    payload = build_default_tag_rules(
        tags=[{"name": "Vegan"}],
        categories=[{"name": "Soup"}],
        tools=[{"name": "Stand Mixer"}],
    )
    assert isinstance(payload["ingredient_tags"], list)
    assert isinstance(payload["ingredient_categories"], list)
    assert payload["tool_tags"][0]["tool"] == "Stand Mixer"


def test_build_default_tag_rules_deduplicates_names() -> None:
    payload = build_default_tag_rules(
        tags=[{"name": "Quick"}, {"name": "quick"}, {"name": "QUICK"}],
        categories=[],
        tools=[],
    )
    assert len(payload["text_tags"]) == 1
    assert payload["text_tags"][0]["tag"] == "Quick"


def test_rule_pattern_for_name_multi_word() -> None:
    pattern = rule_pattern_for_name("Air Fryer")
    assert r"Air" in pattern
    assert r"Fryer" in pattern
    assert r"[\s_-]+" in pattern
