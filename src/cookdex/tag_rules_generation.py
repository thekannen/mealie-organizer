from __future__ import annotations

import re
from typing import Any


def normalize_name(value: Any) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())


def name_key(value: Any) -> str:
    return normalize_name(value).casefold()


def rule_pattern_for_name(name: Any) -> str:
    normalized = normalize_name(name)
    tokens = re.findall(r"[A-Za-z0-9]+", normalized)
    if not tokens:
        escaped = re.escape(normalized)
        return rf"\y{escaped}\y" if escaped else ""
    core = r"[\s_-]+".join(re.escape(token) for token in tokens)
    return rf"\y{core}\y"


def _unique_sorted_names(items: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for item in items:
        name = normalize_name(item.get("name"))
        key = name_key(name)
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    names.sort(key=lambda value: value.casefold())
    return names


_CATEGORY_RULE_OVERRIDES: dict[str, dict[str, Any]] = {
    "appetizer": {
        "pattern": r"\y(appetizer|starter|small[\s_-]+plate|dip|salsa|bruschetta|crostini|deviled[\s_-]+eggs?|wings?)\y",
        "match_on": "name",
    },
    "bread": {
        "pattern": r"\y(bread|loaf|rolls?|buns?|bagels?|focaccia|naan|pita|flatbread|sourdough|cornbread|biscuits?)\y",
        "match_on": "name",
    },
    "breakfast": {
        "pattern": r"\y(breakfast|omelet|omelette|frittata|pancakes?|waffles?|french[\s_-]+toast|granola|oatmeal|porridge|shakshuka|overnight[\s_-]+oats?|egg[\s_-]+bites?)\y",
        "match_on": "name",
    },
    "brunch": {
        "pattern": r"\y(brunch|quiche|strata|benedict|avocado[\s_-]+toast)\y",
        "match_on": "name",
    },
    "dessert": {
        "pattern": r"\y(dessert|cake|cookie|brownie|blondie|pie|tart|cobbler|crisp|pudding|custard|ice[\s_-]+cream|gelato|sorbet|cheesecake|mousse|fudge|cupcakes?|donuts?|doughnuts?|macarons?)\y",
        "match_on": "name",
    },
    "dinner": {
        "pattern": r"\y(dinner|entree|main[\s_-]+course|casserole|stir[\s_-]*fry|roast(ed)?|curry|stew|skillet|meatloaf|pot[\s_-]+pie|weeknight)\y",
        "match_on": "name",
    },
    "drink": {
        "pattern": r"\y(drink|cocktail|mocktail|smoothie|latte|lemonade|iced[\s_-]+tea|tea|coffee|spritz|soda|milkshake|punch|agua[\s_-]+fresca|hot[\s_-]+chocolate)\y",
        "match_on": "name",
    },
    "lunch": {
        "pattern": r"\y(lunch|sandwich|wrap|panini|quesadilla|bento|burger|lunchbox|grain[\s_-]+bowl|rice[\s_-]+bowl)\y",
        "match_on": "name",
    },
    "originals": {
        "pattern": r"\y(originals?|signature|house[\s_-]+special)\y",
        "match_on": "name",
    },
    "salad": {
        "pattern": r"\y(salad|slaw|coleslaw|tabbouleh)\y",
        "match_on": "name",
    },
    "sauce": {
        "pattern": r"\y(sauce|dressing|vinaigrette|marinade|aioli|pesto|chutney|salsa|gravy|reduction|glaze|dip|spread|relish|jam|jelly|compote)\y",
        "match_on": "name",
    },
    "side": {
        "pattern": r"\y(side|side[\s_-]+dish|fries|chips|mashed[\s_-]+potatoes|rice[\s_-]+pilaf|roasted[\s_-]+vegetables?|green[\s_-]+beans|asparagus|slaw)\y",
        "match_on": "name",
    },
    "snack": {
        "pattern": r"\y(snack|energy[\s_-]+bites?|granola[\s_-]+bars?|trail[\s_-]+mix|popcorn|chips|crackers|jerky|pretzels?)\y",
        "match_on": "name",
    },
    "soup": {
        "pattern": r"\y(soup|stew|chowder|bisque|ramen|pho|broth|congee|gumbo|pozole|minestrone)\y",
        "match_on": "name",
    },
}


_TAG_RULE_OVERRIDES: dict[str, dict[str, Any]] = {
    "30-minute": {"pattern": r"\y(30[\s_-]*minute|thirty[\s_-]*minute)\y"},
    "5-ingredient": {"pattern": r"\y(5[\s_-]*ingredient|five[\s_-]*ingredient)\y"},
    "bbq": {"pattern": r"\y(bbq|barbecue)\y"},
    "non-alcoholic": {
        "pattern": r"\y(non[\s_-]*alcoholic|mocktail|virgin)\y",
        "match_on": "name",
    },
    "comfort food": {
        "pattern": r"\y(comfort[\s_-]*food|cozy)\y",
        "match_on": "name",
    },
    "baking": {
        "pattern": r"\y(baking|baked)\y",
        "match_on": "name",
    },
    "make-ahead": {
        "pattern": r"\y(make[\s_-]*ahead|meal[\s_-]*prep)\y",
        "match_on": "name",
    },
    "party": {
        "pattern": r"\y(party|potluck|game[\s_-]*day)\y",
        "match_on": "name",
    },
    "beginner-friendly": {
        "pattern": r"\y(beginner[\s_-]*friendly|easy|simple)\y",
        "match_on": "name",
    },
    "kid-friendly": {
        "pattern": r"\y(kid[\s_-]*friendly|family[\s_-]*friendly)\y",
        "match_on": "name",
    },
    "high-protein": {
        "pattern": r"\y(high[\s_-]*protein|protein[\s_-]*packed)\y",
        "match_on": "name",
    },
    "low-carb": {"pattern": r"\y(low[\s_-]*carb|keto)\y"},
    "gluten-free": {"pattern": r"\y(gluten[\s_-]*free|gf)\y"},
    "dairy-free": {"pattern": r"\y(dairy[\s_-]*free|df)\y"},
    "nut-free": {"pattern": r"\y(nut[\s_-]*free)\y"},
    "pescatarian": {"pattern": r"\y(pescatarian|fish[-\s]*based)\y"},
    "vegan": {"pattern": r"\y(vegan|plant[\s_-]*based)\y"},
    "vegetarian": {"pattern": r"\y(vegetarian|meatless)\y"},
}


def build_default_tag_rules(
    *,
    tags: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    tag_names = _unique_sorted_names(tags)
    category_names = _unique_sorted_names(categories)
    tool_names = _unique_sorted_names(tools)

    text_tags: list[dict[str, Any]] = []
    for name in tag_names:
        override = _TAG_RULE_OVERRIDES.get(name_key(name), {})
        rule = {"tag": name, "pattern": str(override.get("pattern") or rule_pattern_for_name(name))}
        if override.get("match_on"):
            rule["match_on"] = str(override["match_on"])
        text_tags.append(rule)

    text_categories: list[dict[str, Any]] = []
    for name in category_names:
        override = _CATEGORY_RULE_OVERRIDES.get(name_key(name), {})
        rule = {"category": name, "pattern": str(override.get("pattern") or rule_pattern_for_name(name))}
        # Category rules default to title matching to avoid description-driven noise.
        rule["match_on"] = str(override.get("match_on") or "name")
        text_categories.append(rule)

    tool_tags = [{"tool": name, "pattern": rule_pattern_for_name(name)} for name in tool_names]

    return {
        "ingredient_tags": [],
        "ingredient_categories": [],
        "text_tags": text_tags,
        "text_categories": text_categories,
        "tool_tags": tool_tags,
    }
