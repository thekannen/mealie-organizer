from __future__ import annotations

from cookdex.tag_rules_qa import QAThresholds, evaluate_rules, meets_acceptance, tune_rules_once


def _sample_rules() -> dict:
    return {
        "ingredient_tags": [],
        "ingredient_categories": [],
        "text_tags": [
            {"tag": "Chicken", "pattern": r"\yChicken\y"},
            {"tag": "Comfort Food", "pattern": r"\yComfort[\s_-]+Food\y"},
        ],
        "text_categories": [
            {"category": "Dinner", "pattern": r"\yDinner\y"},
            {"category": "Soup", "pattern": r"\ySoup\y"},
        ],
        "tool_tags": [],
    }


def _sample_recipes() -> list[dict]:
    return [
        {"id": "1", "name": "Chicken Soup", "description": "comfort food dinner classic"},
        {"id": "2", "name": "Tomato Soup", "description": "easy dinner"},
        {"id": "3", "name": "Pasta Bake", "description": "best comfort food for party dinner"},
    ]


def test_tuner_reduces_description_dominant_rules() -> None:
    thresholds = QAThresholds(
        min_text_tags_coverage_pct=10.0,
        min_text_categories_coverage_pct=10.0,
        max_text_tags_zero_hit_ratio=0.8,
        max_text_categories_zero_hit_ratio=0.8,
        max_text_tags_desc_dominant=0,
        max_text_categories_desc_dominant=0,
        max_text_tags_coverage_drop_pct=30.0,
        max_text_categories_coverage_drop_pct=30.0,
        desc_dominant_ratio=0.6,
        desc_dominant_min_hits=2,
        min_name_hits_for_name_only=1,
    )

    rules = _sample_rules()
    recipes = _sample_recipes()
    baseline = evaluate_rules(rules=rules, recipes=recipes, thresholds=thresholds)
    assert baseline["sections"]["text_tags"]["desc_dominant_rules"] >= 1
    assert baseline["sections"]["text_categories"]["desc_dominant_rules"] >= 1

    tuned, changes = tune_rules_once(rules=rules, evaluation=baseline, thresholds=thresholds)
    assert len(changes) >= 1

    after = evaluate_rules(rules=tuned, recipes=recipes, thresholds=thresholds)
    assert after["sections"]["text_tags"]["desc_dominant_rules"] == 0
    assert after["sections"]["text_categories"]["desc_dominant_rules"] == 0


def test_acceptance_checks_include_coverage_drop_guard() -> None:
    thresholds = QAThresholds(
        min_text_tags_coverage_pct=10.0,
        min_text_categories_coverage_pct=10.0,
        max_text_tags_zero_hit_ratio=0.8,
        max_text_categories_zero_hit_ratio=0.8,
        max_text_tags_desc_dominant=5,
        max_text_categories_desc_dominant=5,
        max_text_tags_coverage_drop_pct=0.5,
        max_text_categories_coverage_drop_pct=0.5,
    )
    rules = _sample_rules()
    recipes = _sample_recipes()
    baseline = evaluate_rules(rules=rules, recipes=recipes, thresholds=thresholds)

    reduced = {
        "recipe_count": baseline["recipe_count"],
        "sections": {
            "text_tags": {**baseline["sections"]["text_tags"], "coverage_pct": 0.0},
            "text_categories": {**baseline["sections"]["text_categories"], "coverage_pct": 0.0},
        },
    }
    ok, checks = meets_acceptance(baseline=baseline, current=reduced, thresholds=thresholds)
    assert ok is False
    assert any(check["name"] == "text_tags coverage drop" and not check["ok"] for check in checks)
    assert any(check["name"] == "text_categories coverage drop" and not check["ok"] for check in checks)
