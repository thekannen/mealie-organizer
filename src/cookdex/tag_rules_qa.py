"""Tag-rule QA pipeline: generate, evaluate, tune, and gate.

This module provides a local/live-data quality loop for
``configs/taxonomy/tag_rules.json``:

1. Generate a baseline from current taxonomy (optional / when missing)
2. Evaluate rule effectiveness against live recipe summaries
3. Iteratively tune noisy rules (description-heavy text matches)
4. Enforce acceptance thresholds with pass/fail output

Default tuning behavior is conservative:
- For text rules dominated by description-only matches, switch to ``match_on=name``
  when there is enough title signal.
- Otherwise disable the rule.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

from .config import REPO_ROOT, resolve_mealie_api_key, resolve_mealie_url
from .tag_rules_generation import build_default_tag_rules

DEFAULT_RULES_PATH = REPO_ROOT / "configs" / "taxonomy" / "tag_rules.json"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "qa" / "tag_rules_qa_report.json"

TARGET_SECTIONS: tuple[tuple[str, str], ...] = (
    ("text_tags", "tag"),
    ("text_categories", "category"),
)


@dataclass
class QAThresholds:
    min_text_tags_coverage_pct: float = 70.0
    min_text_categories_coverage_pct: float = 48.0
    max_text_tags_zero_hit_ratio: float = 0.20
    max_text_categories_zero_hit_ratio: float = 0.20
    max_text_tags_desc_dominant: int = 0
    max_text_categories_desc_dominant: int = 0
    max_text_tags_coverage_drop_pct: float = 6.0
    max_text_categories_coverage_drop_pct: float = 8.0
    desc_dominant_ratio: float = 0.95
    desc_dominant_min_hits: int = 20
    min_name_hits_for_name_only: int = 5


def _normalize_name(value: Any) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())


def _name_key(value: Any) -> str:
    return _normalize_name(value).casefold()


def _bool_value(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    return default


def _rule_enabled(rule: dict[str, Any]) -> bool:
    return _bool_value(rule.get("enabled"), default=True)


def _rule_match_on(rule: dict[str, Any]) -> str:
    raw = str(rule.get("match_on") or "").strip().casefold()
    if raw in {"name", "description", "both"}:
        return raw
    fields = rule.get("fields")
    if isinstance(fields, str):
        lowered = fields.strip().casefold()
        if lowered in {"name", "description", "both"}:
            return lowered
    if isinstance(fields, list):
        names = {str(item or "").strip().casefold() for item in fields}
        has_name = "name" in names
        has_desc = "description" in names
        if has_name and has_desc:
            return "both"
        if has_name:
            return "name"
        if has_desc:
            return "description"
    return "both"


def _load_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return copy.deepcopy(default)


def _load_named_entries(path: Path) -> list[str]:
    payload = _load_json_file(path, default=[])
    if not isinstance(payload, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in payload:
        name = _normalize_name(item.get("name") if isinstance(item, dict) else item)
        key = _name_key(name)
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    out.sort(key=lambda value: value.casefold())
    return out


def generate_rules_from_taxonomy(repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    taxonomy_root = (repo_root / "configs" / "taxonomy").resolve()
    tags = [{"name": name} for name in _load_named_entries(taxonomy_root / "tags.json")]
    categories = [{"name": name} for name in _load_named_entries(taxonomy_root / "categories.json")]
    tools = [{"name": name} for name in _load_named_entries(taxonomy_root / "tools.json")]
    return build_default_tag_rules(tags=tags, categories=categories, tools=tools)


def fetch_recipe_summaries(*, mealie_url: str, api_key: str) -> list[dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    recipes: list[dict[str, Any]] = []
    base = mealie_url.rstrip("/")
    url: str | None = f"{base}/recipes?perPage=1000"
    while url:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            recipes.extend(data)
            break
        recipes.extend(data.get("items") or [])
        next_link = data.get("next")
        if not (isinstance(next_link, str) and next_link):
            url = None
        elif next_link.startswith("/"):
            url = base + next_link
        else:
            url = next_link
    return recipes


def _compile_pattern(pattern: Any) -> re.Pattern[str]:
    raw = str(pattern or "").replace(r"\y", r"\b")
    return re.compile(raw, re.IGNORECASE)


def _match_recipe(compiled: re.Pattern[str], recipe: dict[str, Any], match_on: str) -> tuple[bool, bool, bool]:
    name = str(recipe.get("name") or "")
    description = str(recipe.get("description") or "")
    in_name = bool(compiled.search(name))
    in_desc = bool(compiled.search(description))
    if match_on == "name":
        return in_name, in_name, False
    if match_on == "description":
        return in_desc, False, in_desc
    return (in_name or in_desc), in_name, in_desc


def evaluate_rules(
    *,
    rules: dict[str, Any],
    recipes: list[dict[str, Any]],
    thresholds: QAThresholds,
) -> dict[str, Any]:
    recipe_count = len(recipes)
    sections: dict[str, Any] = {}

    for section, target_field in TARGET_SECTIONS:
        section_rules = rules.get(section, [])
        if not isinstance(section_rules, list):
            section_rules = []

        coverage_ids: set[str] = set()
        per_rule: list[dict[str, Any]] = []
        active_rules = 0
        disabled_rules = 0
        zero_hit_rules = 0
        desc_dominant_rules = 0

        for idx, raw_rule in enumerate(section_rules):
            if not isinstance(raw_rule, dict):
                continue
            name = _normalize_name(raw_rule.get(target_field))
            enabled = _rule_enabled(raw_rule)
            match_on = _rule_match_on(raw_rule)
            rule_result = {
                "index": idx,
                "name": name,
                "enabled": enabled,
                "match_on": match_on,
                "total_hits": 0,
                "name_hits": 0,
                "description_hits": 0,
                "description_only_hits": 0,
                "description_only_ratio": 0.0,
            }
            if not enabled:
                disabled_rules += 1
                per_rule.append(rule_result)
                continue

            active_rules += 1
            try:
                compiled = _compile_pattern(raw_rule.get("pattern"))
            except re.error:
                per_rule.append(rule_result)
                zero_hit_rules += 1
                continue

            hit_ids: set[str] = set()
            total_hits = 0
            name_hits = 0
            desc_hits = 0
            desc_only_hits = 0

            for recipe in recipes:
                recipe_id = str(recipe.get("id") or recipe.get("slug") or recipe.get("name") or "")
                matched, in_name, in_desc = _match_recipe(compiled, recipe, match_on)
                if in_name:
                    name_hits += 1
                if in_desc:
                    desc_hits += 1
                if in_desc and not in_name:
                    desc_only_hits += 1
                if matched:
                    total_hits += 1
                    if recipe_id:
                        hit_ids.add(recipe_id)

            rule_result.update(
                {
                    "total_hits": total_hits,
                    "name_hits": name_hits,
                    "description_hits": desc_hits,
                    "description_only_hits": desc_only_hits,
                    "description_only_ratio": round((desc_only_hits / total_hits), 4) if total_hits else 0.0,
                }
            )
            per_rule.append(rule_result)
            coverage_ids.update(hit_ids)

            if total_hits == 0:
                zero_hit_rules += 1
            if (
                match_on == "both"
                and total_hits >= thresholds.desc_dominant_min_hits
                and (desc_only_hits / total_hits) >= thresholds.desc_dominant_ratio
            ):
                desc_dominant_rules += 1

        coverage_pct = round((len(coverage_ids) / recipe_count) * 100, 2) if recipe_count else 0.0
        zero_hit_ratio = round((zero_hit_rules / active_rules), 4) if active_rules else 0.0
        sections[section] = {
            "active_rules": active_rules,
            "disabled_rules": disabled_rules,
            "coverage_count": len(coverage_ids),
            "coverage_pct": coverage_pct,
            "zero_hit_rules": zero_hit_rules,
            "zero_hit_ratio": zero_hit_ratio,
            "desc_dominant_rules": desc_dominant_rules,
            "rules": per_rule,
        }

    return {
        "recipe_count": recipe_count,
        "sections": sections,
    }


def meets_acceptance(
    *,
    baseline: dict[str, Any],
    current: dict[str, Any],
    thresholds: QAThresholds,
) -> tuple[bool, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    base_sections = baseline.get("sections", {})
    cur_sections = current.get("sections", {})

    def _section(name: str) -> dict[str, Any]:
        return cur_sections.get(name, {}) if isinstance(cur_sections, dict) else {}

    def _base_section(name: str) -> dict[str, Any]:
        return base_sections.get(name, {}) if isinstance(base_sections, dict) else {}

    tag = _section("text_tags")
    cat = _section("text_categories")
    tag_base = _base_section("text_tags")
    cat_base = _base_section("text_categories")

    checks.append(
        {
            "name": "text_tags coverage",
            "ok": float(tag.get("coverage_pct", 0.0)) >= thresholds.min_text_tags_coverage_pct,
            "value": tag.get("coverage_pct", 0.0),
            "threshold": thresholds.min_text_tags_coverage_pct,
        }
    )
    checks.append(
        {
            "name": "text_categories coverage",
            "ok": float(cat.get("coverage_pct", 0.0)) >= thresholds.min_text_categories_coverage_pct,
            "value": cat.get("coverage_pct", 0.0),
            "threshold": thresholds.min_text_categories_coverage_pct,
        }
    )
    checks.append(
        {
            "name": "text_tags zero-hit ratio",
            "ok": float(tag.get("zero_hit_ratio", 0.0)) <= thresholds.max_text_tags_zero_hit_ratio,
            "value": tag.get("zero_hit_ratio", 0.0),
            "threshold": thresholds.max_text_tags_zero_hit_ratio,
        }
    )
    checks.append(
        {
            "name": "text_categories zero-hit ratio",
            "ok": float(cat.get("zero_hit_ratio", 0.0)) <= thresholds.max_text_categories_zero_hit_ratio,
            "value": cat.get("zero_hit_ratio", 0.0),
            "threshold": thresholds.max_text_categories_zero_hit_ratio,
        }
    )
    checks.append(
        {
            "name": "text_tags desc-dominant",
            "ok": int(tag.get("desc_dominant_rules", 0)) <= thresholds.max_text_tags_desc_dominant,
            "value": tag.get("desc_dominant_rules", 0),
            "threshold": thresholds.max_text_tags_desc_dominant,
        }
    )
    checks.append(
        {
            "name": "text_categories desc-dominant",
            "ok": int(cat.get("desc_dominant_rules", 0)) <= thresholds.max_text_categories_desc_dominant,
            "value": cat.get("desc_dominant_rules", 0),
            "threshold": thresholds.max_text_categories_desc_dominant,
        }
    )

    tag_drop = max(0.0, float(tag_base.get("coverage_pct", 0.0)) - float(tag.get("coverage_pct", 0.0)))
    cat_drop = max(0.0, float(cat_base.get("coverage_pct", 0.0)) - float(cat.get("coverage_pct", 0.0)))
    checks.append(
        {
            "name": "text_tags coverage drop",
            "ok": tag_drop <= thresholds.max_text_tags_coverage_drop_pct,
            "value": round(tag_drop, 2),
            "threshold": thresholds.max_text_tags_coverage_drop_pct,
        }
    )
    checks.append(
        {
            "name": "text_categories coverage drop",
            "ok": cat_drop <= thresholds.max_text_categories_coverage_drop_pct,
            "value": round(cat_drop, 2),
            "threshold": thresholds.max_text_categories_coverage_drop_pct,
        }
    )

    return all(check.get("ok") for check in checks), checks


def tune_rules_once(
    *,
    rules: dict[str, Any],
    evaluation: dict[str, Any],
    thresholds: QAThresholds,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tuned = copy.deepcopy(rules)
    changes: list[dict[str, Any]] = []
    sections = evaluation.get("sections", {})

    for section, target_field in TARGET_SECTIONS:
        section_eval = sections.get(section, {})
        per_rule = section_eval.get("rules", [])
        tuned_rules = tuned.get(section, [])
        if not isinstance(per_rule, list) or not isinstance(tuned_rules, list):
            continue

        for rule_eval in per_rule:
            try:
                idx = int(rule_eval.get("index"))
            except Exception:
                continue
            if idx < 0 or idx >= len(tuned_rules):
                continue
            raw_rule = tuned_rules[idx]
            if not isinstance(raw_rule, dict):
                continue
            if not _rule_enabled(raw_rule):
                continue
            if _rule_match_on(raw_rule) != "both":
                continue

            total_hits = int(rule_eval.get("total_hits", 0))
            name_hits = int(rule_eval.get("name_hits", 0))
            desc_ratio = float(rule_eval.get("description_only_ratio", 0.0))
            if total_hits < thresholds.desc_dominant_min_hits:
                continue
            if desc_ratio < thresholds.desc_dominant_ratio:
                continue

            target_name = _normalize_name(raw_rule.get(target_field))
            if name_hits >= thresholds.min_name_hits_for_name_only:
                raw_rule["match_on"] = "name"
                changes.append(
                    {
                        "section": section,
                        "target": target_name,
                        "action": "match_on=name",
                        "total_hits": total_hits,
                        "name_hits": name_hits,
                        "description_only_ratio": desc_ratio,
                    }
                )
            else:
                raw_rule["enabled"] = False
                changes.append(
                    {
                        "section": section,
                        "target": target_name,
                        "action": "enabled=false",
                        "total_hits": total_hits,
                        "name_hits": name_hits,
                        "description_only_ratio": desc_ratio,
                    }
                )

    return tuned, changes


def _rules_need_generation(rules: dict[str, Any]) -> bool:
    for section in ("text_tags", "text_categories", "tool_tags"):
        value = rules.get(section, [])
        if isinstance(value, list) and len(value) > 0:
            return False
    return True


def run_qa_pipeline(
    *,
    repo_root: Path,
    rules_path: Path,
    report_path: Path,
    regenerate: bool,
    write: bool,
    max_iterations: int,
    thresholds: QAThresholds,
) -> dict[str, Any]:
    disk_rules = _load_json_file(rules_path, default={})
    if not isinstance(disk_rules, dict):
        disk_rules = {}
    loaded_rules = copy.deepcopy(disk_rules)

    generated = False
    if regenerate or _rules_need_generation(loaded_rules):
        loaded_rules = generate_rules_from_taxonomy(repo_root)
        generated = True

    mealie_url = resolve_mealie_url().rstrip("/")
    mealie_api_key = resolve_mealie_api_key(required=True)
    recipes = fetch_recipe_summaries(mealie_url=mealie_url, api_key=mealie_api_key)

    initial_rules = copy.deepcopy(loaded_rules)
    baseline = evaluate_rules(rules=loaded_rules, recipes=recipes, thresholds=thresholds)
    current_rules = copy.deepcopy(loaded_rules)
    current_eval = baseline
    all_changes: list[dict[str, Any]] = []

    for _ in range(max(1, max_iterations)):
        passed, checks = meets_acceptance(baseline=baseline, current=current_eval, thresholds=thresholds)
        if passed:
            break
        next_rules, changes = tune_rules_once(rules=current_rules, evaluation=current_eval, thresholds=thresholds)
        if not changes:
            break
        all_changes.extend(changes)
        current_rules = next_rules
        current_eval = evaluate_rules(rules=current_rules, recipes=recipes, thresholds=thresholds)

    passed, checks = meets_acceptance(baseline=baseline, current=current_eval, thresholds=thresholds)
    tuned_rules_changed = current_rules != initial_rules
    disk_rules_changed = current_rules != disk_rules
    if write and disk_rules_changed:
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        rules_path.write_text(json.dumps(current_rules, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    report = {
        "status": "pass" if passed else "fail",
        "generated_baseline": generated,
        "rules_changed": tuned_rules_changed,
        "rules_changed_from_disk": disk_rules_changed,
        "rules_written": bool(write and disk_rules_changed),
        "max_iterations": max(1, max_iterations),
        "changes_count": len(all_changes),
        "changes": all_changes,
        "thresholds": asdict(thresholds),
        "checks": checks,
        "baseline": baseline,
        "final": current_eval,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate and tune taxonomy tag rules until QA thresholds pass."
    )
    parser.add_argument("--rules-path", default=str(DEFAULT_RULES_PATH), help="Path to tag_rules.json")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Where to write QA report JSON")
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Rebuild text/category/tool rules from taxonomy before tuning.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist tuned rules back to --rules-path.",
    )
    parser.add_argument("--max-iterations", type=int, default=6, help="Maximum tune/evaluate cycles.")
    args = parser.parse_args(argv)

    thresholds = QAThresholds()
    report = run_qa_pipeline(
        repo_root=REPO_ROOT,
        rules_path=Path(args.rules_path).resolve(),
        report_path=Path(args.report_path).resolve(),
        regenerate=bool(args.regenerate),
        write=bool(args.write),
        max_iterations=max(1, int(args.max_iterations)),
        thresholds=thresholds,
    )

    status = str(report.get("status", "fail")).upper()
    changes = int(report.get("changes_count", 0))
    final = report.get("final", {})
    sections = final.get("sections", {}) if isinstance(final, dict) else {}
    tag_cov = sections.get("text_tags", {}).get("coverage_pct", 0.0)
    cat_cov = sections.get("text_categories", {}).get("coverage_pct", 0.0)
    print(
        f"[tag-rules-qa] {status} | changes={changes} | "
        f"text_tags_coverage={tag_cov}% | text_categories_coverage={cat_cov}%"
    )
    print(f"[tag-rules-qa] report: {args.report_path}")
    if bool(args.write) and bool(report.get("rules_written")):
        print(f"[tag-rules-qa] wrote tuned rules: {args.rules_path}")

    return 0 if str(report.get("status")) == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
