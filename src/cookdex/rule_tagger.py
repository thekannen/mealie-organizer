"""Rule-based recipe tagger — no LLM required.

Assigns tags and tools to Mealie recipes using configurable regex rules.
Works in two modes:

API mode (default, no extra setup)
    Runs ``text_tags`` rules against recipe name and description via the
    Mealie HTTP API.  Fast for that phase; ingredient and tool rules are
    skipped with an informational note.

DB mode (``--use-db``, requires ``cookdex[db]`` extras + DB config)
    Runs all three rule types (ingredient, text, tool) via direct SQL
    queries — dramatically faster on large libraries and enables
    ingredient-food matching and instruction-text tool detection.

In both modes dry-run is the default; use ``--apply`` to write changes.

Usage
-----
    # Preview text-tag matches via API (no DB required)
    python -m cookdex.rule_tagger

    # Apply text tags via API
    python -m cookdex.rule_tagger --apply

    # Apply all rules via DB (ingredient + text + tool)
    python -m cookdex.rule_tagger --apply --use-db

    # Custom rules file
    python -m cookdex.rule_tagger --apply --use-db --config /path/to/rules.json

Config file schema (JSON)
--------------------------
    {
      "ingredient_tags": [
        {
          "tag": "Chicken",
          "pattern": "chicken|chicken breast",
          "exclude_pattern": "chicken broth|chicken stock",
          "min_matches": 1
        }
      ],
      "text_tags": [
        {
          "tag": "Breakfast",
          "pattern": "breakfast|pancake|waffle|omelet"
        }
      ],
      "tool_tags": [
        {
          "tool": "Air Fryer",
          "pattern": "air fryer|air-fryer"
        }
      ]
    }

Rule types
----------
ingredient_tags
    Match against parsed ingredient food names (``ingredient_foods.name``).
    Requires ``--use-db``.  Use ``min_matches >= 2`` for cuisine
    fingerprinting (recipe must contain at least N distinct matching foods).

text_tags
    Match against ``recipes.name`` and ``recipes.description``.
    Works in both API mode and DB mode.

tool_tags
    Match against ``recipe_instructions.text`` and assign a kitchen
    **tool** (``recipes_to_tools``) rather than a tag.
    Requires ``--use-db``.

Pattern syntax
--------------
Patterns are case-insensitive regex.  Use ``\\y`` for word boundaries
(PostgreSQL syntax) or ``\\b`` (Python/SQLite syntax) — both work in DB
mode.  In API mode patterns are compiled with Python ``re`` (use ``\\b``
or omit boundaries for simplicity).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import requests as _requests

from .config import REPO_ROOT, resolve_mealie_api_key, resolve_mealie_url
from .db_client import MealieDBClient, is_db_enabled

DEFAULT_RULES_FILE = str(REPO_ROOT / "configs" / "taxonomy" / "tag_rules.json")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _load_rules(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Tag rules config not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tagger
# ---------------------------------------------------------------------------


class RecipeRuleTagger:
    """Apply rule-based tags and tool assignments to Mealie recipes.

    Supports two modes:
      - API mode (default): ``text_tags`` only, writes via Mealie PATCH API
      - DB mode (``use_db=True``): all rule types, direct SQL reads/writes
    """

    def __init__(
        self,
        rules_file: str = DEFAULT_RULES_FILE,
        *,
        dry_run: bool = True,
        use_db: bool = False,
    ) -> None:
        self.rules_file = rules_file
        self.dry_run = dry_run
        self.use_db = use_db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Run all configured rules and return a stats dict."""
        rules = _load_rules(self.rules_file)

        if self.use_db:
            return self._run_db(rules)
        return self._run_api(rules)

    # ------------------------------------------------------------------
    # API mode
    # ------------------------------------------------------------------

    def _run_api(self, rules: dict[str, Any]) -> dict[str, Any]:
        """API-only path: text_tags via Mealie HTTP API."""
        stats: dict[str, Any] = {
            "ingredient_tags": {},
            "text_tags": {},
            "tool_tags": {},
        }

        skipped: list[str] = []
        if rules.get("ingredient_tags"):
            skipped.append("ingredient_tags")
        if rules.get("tool_tags"):
            skipped.append("tool_tags")
        if skipped:
            print(
                f"[info] API mode: skipping {', '.join(skipped)} rules — "
                "add --use-db to enable ingredient and tool matching.",
                flush=True,
            )

        mealie_url = resolve_mealie_url().rstrip("/")
        api_key = resolve_mealie_api_key()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        print(
            f"[start] Rule tagger (API mode) — dry_run={self.dry_run}",
            flush=True,
        )

        text_rules = rules.get("text_tags", [])
        if text_rules:
            all_recipes = self._api_get_all_recipes(mealie_url, headers)
            tag_cache: dict[str, Optional[dict]] = {}
            for rule in text_rules:
                tag_name = rule.get("tag", "")
                count = self._api_apply_text_rule(
                    all_recipes, rule, mealie_url, headers, tag_cache
                )
                stats["text_tags"][tag_name] = count

        total = sum(stats["text_tags"].values())
        action = "Would apply" if self.dry_run else "Applied"
        print(
            f"[summary] {action} {total} tag assignments "
            f"({len(stats['text_tags'])} text rules)",
            flush=True,
        )
        if self.dry_run:
            print("[dry-run] No changes written.", flush=True)
        return stats

    def _api_get_all_recipes(
        self, mealie_url: str, headers: dict
    ) -> list[dict]:
        """Fetch all recipe summaries via paginated GET /recipes."""
        recipes: list[dict] = []
        url: Optional[str] = f"{mealie_url}/recipes?perPage=1000"
        while url:
            resp = _requests.get(url, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                recipes.extend(data)
                break
            recipes.extend(data.get("items") or [])
            next_link = data.get("next")
            url = next_link if isinstance(next_link, str) and next_link else None
        return recipes

    def _api_get_or_create_tag(
        self,
        tag_name: str,
        mealie_url: str,
        headers: dict,
        cache: dict[str, Optional[dict]],
    ) -> Optional[dict]:
        """Return existing tag dict (by name) or create it; cached."""
        key = tag_name.lower()
        if key in cache:
            return cache[key]

        resp = _requests.get(
            f"{mealie_url}/tags?perPage=1000", headers=headers, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        all_tags = data.get("items", data) if isinstance(data, dict) else data
        for t in all_tags:
            cache[t["name"].lower()] = t

        if key in cache:
            return cache[key]

        if self.dry_run:
            placeholder = {"id": "dry-run-id", "name": tag_name, "slug": "dry-run"}
            cache[key] = placeholder
            return placeholder

        resp = _requests.post(
            f"{mealie_url}/tags",
            json={"name": tag_name},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        tag = resp.json()
        cache[tag["name"].lower()] = tag
        return tag

    def _api_apply_text_rule(
        self,
        all_recipes: list[dict],
        rule: dict[str, Any],
        mealie_url: str,
        headers: dict,
        tag_cache: dict[str, Optional[dict]],
    ) -> int:
        """Match text pattern against recipe name/description; add tag via API."""
        tag_name: str = rule["tag"]
        pattern: str = rule["pattern"]

        # Translate \y word boundaries to \b for Python regex
        py_pattern = pattern.replace(r"\y", r"\b")
        compiled = re.compile(py_pattern, re.IGNORECASE)

        matched = [
            r
            for r in all_recipes
            if compiled.search(r.get("name") or "")
            or compiled.search(r.get("description") or "")
        ]
        count = len(matched)
        if count:
            print(
                f"[text] '{tag_name}': {count} recipe(s) matched"
                f"{' (dry-run)' if self.dry_run else ''}",
                flush=True,
            )

        if not matched:
            return 0

        tag = self._api_get_or_create_tag(tag_name, mealie_url, headers, tag_cache)
        if tag is None:
            return 0
        tag_id = tag["id"]

        if not self.dry_run:
            for recipe in matched:
                existing_ids = {t.get("id") for t in (recipe.get("tags") or [])}
                if tag_id in existing_ids:
                    continue
                slug = recipe["slug"]
                # Fetch full recipe to build the PATCH payload
                resp = _requests.get(
                    f"{mealie_url}/recipes/{slug}", headers=headers, timeout=30
                )
                if not resp.ok:
                    print(f"[warn] Could not fetch '{slug}': {resp.status_code}", flush=True)
                    continue
                full = resp.json()
                full["tags"] = (full.get("tags") or []) + [
                    {"id": tag_id, "name": tag["name"], "slug": tag.get("slug", "")}
                ]
                patch = _requests.patch(
                    f"{mealie_url}/recipes/{slug}",
                    json=full,
                    headers=headers,
                    timeout=30,
                )
                if not patch.ok:
                    print(f"[warn] PATCH failed for '{slug}': {patch.status_code}", flush=True)

        return count

    # ------------------------------------------------------------------
    # DB mode
    # ------------------------------------------------------------------

    def _run_db(self, rules: dict[str, Any]) -> dict[str, Any]:
        """DB-accelerated path: all three rule types via direct SQL."""
        if not is_db_enabled():
            print(
                "[error] --use-db requires direct DB access.\n"
                "  Set MEALIE_DB_TYPE=postgres (or sqlite) in .env and\n"
                "  install extras:  pip install 'cookdex[db]'",
                flush=True,
            )
            sys.exit(1)

        stats: dict[str, Any] = {
            "ingredient_tags": {},
            "text_tags": {},
            "tool_tags": {},
        }

        with MealieDBClient() as db:
            group_id = db.get_group_id()
            if not group_id:
                print("[error] Could not determine group_id from database.", flush=True)
                sys.exit(1)

            print(
                f"[start] Rule tagger (DB mode) — dry_run={self.dry_run}  group_id={group_id}",
                flush=True,
            )

            for rule in rules.get("ingredient_tags", []):
                tag = rule.get("tag", "")
                stats["ingredient_tags"][tag] = self._db_apply_ingredient_rule(
                    db, group_id, rule
                )

            for rule in rules.get("text_tags", []):
                tag = rule.get("tag", "")
                stats["text_tags"][tag] = self._db_apply_text_rule(db, group_id, rule)

            for rule in rules.get("tool_tags", []):
                tool = rule.get("tool", "")
                stats["tool_tags"][tool] = self._db_apply_tool_rule(db, group_id, rule)

        total = (
            sum(stats["ingredient_tags"].values())
            + sum(stats["text_tags"].values())
            + sum(stats["tool_tags"].values())
        )
        action = "Would apply" if self.dry_run else "Applied"
        print(
            f"[summary] {action} {total} tag/tool assignments  "
            f"({len(stats['ingredient_tags'])} ingredient, "
            f"{len(stats['text_tags'])} text, "
            f"{len(stats['tool_tags'])} tool rules)",
            flush=True,
        )
        if self.dry_run:
            print("[dry-run] No changes written.", flush=True)
        return stats

    def _db_apply_ingredient_rule(
        self,
        db: MealieDBClient,
        group_id: str,
        rule: dict[str, Any],
    ) -> int:
        tag_name: str = rule["tag"]
        pattern: str = rule["pattern"]
        exclude: str = rule.get("exclude_pattern", "")
        min_matches: int = int(rule.get("min_matches", 1))

        recipe_ids = db.find_recipe_ids_by_ingredient(
            group_id,
            pattern,
            exclude_pattern=exclude,
            min_matches=min_matches,
        )
        count = len(recipe_ids)
        if count:
            print(
                f"[ingredient] '{tag_name}': {count} recipe(s) matched"
                f"{' (dry-run)' if self.dry_run else ''}",
                flush=True,
            )
        tag_id = db.ensure_tag(tag_name, group_id, dry_run=self.dry_run)
        for recipe_id in recipe_ids:
            db.link_tag(recipe_id, tag_id, dry_run=self.dry_run)
        return count

    def _db_apply_text_rule(
        self,
        db: MealieDBClient,
        group_id: str,
        rule: dict[str, Any],
    ) -> int:
        tag_name: str = rule["tag"]
        pattern: str = rule["pattern"]

        recipe_ids = db.find_recipe_ids_by_text(group_id, pattern)
        count = len(recipe_ids)
        if count:
            print(
                f"[text] '{tag_name}': {count} recipe(s) matched"
                f"{' (dry-run)' if self.dry_run else ''}",
                flush=True,
            )
        tag_id = db.ensure_tag(tag_name, group_id, dry_run=self.dry_run)
        for recipe_id in recipe_ids:
            db.link_tag(recipe_id, tag_id, dry_run=self.dry_run)
        return count

    def _db_apply_tool_rule(
        self,
        db: MealieDBClient,
        group_id: str,
        rule: dict[str, Any],
    ) -> int:
        tool_name: str = rule["tool"]
        pattern: str = rule["pattern"]

        recipe_ids = db.find_recipe_ids_by_instruction(group_id, pattern)
        count = len(recipe_ids)
        if count:
            print(
                f"[tool] '{tool_name}': {count} recipe(s) matched"
                f"{' (dry-run)' if self.dry_run else ''}",
                flush=True,
            )
        tool_id = db.ensure_tool(tool_name, group_id, dry_run=self.dry_run)
        for recipe_id in recipe_ids:
            db.link_tool(recipe_id, tool_id, dry_run=self.dry_run)
        return count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Rule-based recipe tagger — assigns tags/tools via regex rules, no LLM required.\n"
            "API mode (default): runs text_tags rules via Mealie HTTP API.\n"
            "--use-db: adds ingredient and tool matching via direct DB queries."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write changes (default: dry-run preview only).",
    )
    parser.add_argument(
        "--use-db",
        action="store_true",
        default=False,
        help=(
            "Use direct DB queries for all rule types (ingredient, text, tool). "
            "Requires MEALIE_DB_TYPE in .env and cookdex[db] extras."
        ),
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_RULES_FILE,
        metavar="FILE",
        help=f"Tag rules JSON config file (default: {DEFAULT_RULES_FILE}).",
    )
    args = parser.parse_args()

    tagger = RecipeRuleTagger(
        rules_file=args.config,
        dry_run=not args.apply,
        use_db=args.use_db,
    )
    tagger.run()


if __name__ == "__main__":
    main()
