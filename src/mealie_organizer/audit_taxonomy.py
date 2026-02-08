import argparse
import json
import re

import requests

from .config import REPO_ROOT, env_or_config, secret, resolve_repo_path


def parse_args():
    parser = argparse.ArgumentParser(description="Audit Mealie category/tag quality and usage.")
    parser.add_argument(
        "--output",
        default=env_or_config("TAXONOMY_AUDIT_OUTPUT", "taxonomy.audit_report", "reports/taxonomy_audit_report.json"),
        help="Output file path for audit report JSON.",
    )
    parser.add_argument("--long-tag-threshold", type=int, default=24)
    parser.add_argument("--min-useful-usage", type=int, default=2)
    return parser.parse_args()


def get_json(session, url):
    response = session.get(url, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data.get("items", data)


def normalize_for_similarity(name):
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def detect_problematic_tags(tag_usage, long_threshold, min_useful_usage):
    noisy_patterns = [
        r"\brecipe\b",
        r"\bhow to make\b",
        r"\bfrom scratch\b",
        r"\bwithout drippings\b",
        r"\bfrom drippings\b",
    ]
    issues = []
    for name, usage in sorted(tag_usage.items(), key=lambda item: (item[1], item[0])):
        reasons = []
        if len(name) >= long_threshold:
            reasons.append("name_too_long")
        if usage < min_useful_usage:
            reasons.append("low_usage")
        if any(re.search(pattern, name.lower()) for pattern in noisy_patterns):
            reasons.append("noisy_or_over_specific")
        if reasons:
            issues.append({"name": name, "usage": usage, "reasons": reasons})
    return issues


def find_similar_tags(tags):
    normalized = {}
    for tag in tags:
        name = (tag.get("name") or "").strip()
        if not name:
            continue
        key = normalize_for_similarity(name)
        normalized.setdefault(key, []).append(name)

    groups = []
    for _, names in normalized.items():
        uniq = sorted(set(names))
        if len(uniq) > 1:
            groups.append(uniq)
    return sorted(groups, key=lambda group: (len(group) * -1, group[0]))


def main():
    args = parse_args()

    mealie_url = env_or_config("MEALIE_URL", "mealie.url", "http://your.server.ip.address:9000/api").rstrip("/")
    mealie_api_key = secret("MEALIE_API_KEY")
    if not mealie_url or not mealie_api_key:
        raise RuntimeError("MEALIE_URL and MEALIE_API_KEY are required in environment or .env")

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {mealie_api_key}",
            "Content-Type": "application/json",
        }
    )

    recipes = get_json(session, f"{mealie_url}/recipes?perPage=999")
    categories = get_json(session, f"{mealie_url}/organizers/categories?perPage=999")
    tags = get_json(session, f"{mealie_url}/organizers/tags?perPage=999")

    category_usage = {c.get("name", ""): 0 for c in categories if c.get("name")}
    tag_usage = {t.get("name", ""): 0 for t in tags if t.get("name")}

    uncategorized = 0
    untagged = 0
    for recipe in recipes:
        recipe_categories = recipe.get("recipeCategory") or []
        recipe_tags = recipe.get("tags") or []
        if not recipe_categories:
            uncategorized += 1
        if not recipe_tags:
            untagged += 1

        for cat in recipe_categories:
            name = cat.get("name")
            if name in category_usage:
                category_usage[name] += 1
        for tag in recipe_tags:
            name = tag.get("name")
            if name in tag_usage:
                tag_usage[name] += 1

    problematic_tags = detect_problematic_tags(tag_usage, args.long_tag_threshold, args.min_useful_usage)
    similar_tag_groups = find_similar_tags(tags)

    report = {
        "summary": {
            "recipes": len(recipes),
            "categories": len(categories),
            "tags": len(tags),
            "recipes_without_categories": uncategorized,
            "recipes_without_tags": untagged,
            "unused_categories": sum(1 for _, count in category_usage.items() if count == 0),
            "unused_tags": sum(1 for _, count in tag_usage.items() if count == 0),
        },
        "categories": {
            "usage": dict(sorted(category_usage.items(), key=lambda item: (item[1], item[0]))),
            "unused": sorted([name for name, count in category_usage.items() if count == 0]),
        },
        "tags": {
            "usage": dict(sorted(tag_usage.items(), key=lambda item: (item[1], item[0]))),
            "unused": sorted([name for name, count in tag_usage.items() if count == 0]),
            "problematic": problematic_tags,
            "similar_groups": similar_tag_groups,
        },
        "recommendations": [
            "Merge or delete tags marked as noisy_or_over_specific.",
            "Prefer short reusable tags (single concept) over recipe-title tags.",
            "Run categorizer in missing-tags mode weekly to improve tag coverage.",
            "Keep category list stable; use tags for user-facing discovery.",
        ],
    }

    output_path = resolve_repo_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("[done] Taxonomy audit report written to", output_path)
    print("[summary]", json.dumps(report["summary"], indent=2))
    print(f"[summary] problematic tags: {len(problematic_tags)}")


if __name__ == "__main__":
    main()
