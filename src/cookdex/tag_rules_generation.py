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


def build_default_tag_rules(
    *,
    tags: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    tag_names = _unique_sorted_names(tags)
    category_names = _unique_sorted_names(categories)
    tool_names = _unique_sorted_names(tools)

    text_tags = [{"tag": name, "pattern": rule_pattern_for_name(name)} for name in tag_names]

    # Category rules default to title matching to avoid description-driven noise.
    text_categories = [
        {"category": name, "pattern": rule_pattern_for_name(name), "match_on": "name"}
        for name in category_names
    ]

    tool_tags = [{"tool": name, "pattern": rule_pattern_for_name(name)} for name in tool_names]

    return {
        "ingredient_tags": [],
        "ingredient_categories": [],
        "text_tags": text_tags,
        "text_categories": text_categories,
        "tool_tags": tool_tags,
    }
