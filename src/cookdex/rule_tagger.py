"""Rule-based recipe tagger — no LLM required.

Assigns tags, categories, and tools to Mealie recipes using configurable
regex rules.  Works in two modes:

API mode (default, no extra setup)
    Runs ``text_tags`` and ``text_categories`` rules against recipe name
    and description via the Mealie HTTP API.  Ingredient and tool rules are
    skipped with an informational note.

DB mode (``--use-db``, requires ``cookdex[db]`` extras + DB config)
    Runs all rule types (ingredient, text, tool — for both tags and
    categories) via direct SQL queries — dramatically faster on large
    libraries and enables ingredient-food matching and instruction-text
    tool detection.

In both modes dry-run is the default; use ``--apply`` to write changes.

Usage
-----
    # Preview text-tag/category matches via API (no DB required)
    python -m cookdex.rule_tagger

    # Apply text tags and categories via API
    python -m cookdex.rule_tagger --apply

    # Apply all rules via DB (ingredient + text + tool, tags + categories)
    python -m cookdex.rule_tagger --apply --use-db

    # Custom rules file
    python -m cookdex.rule_tagger --apply --use-db --config /path/to/rules.json

    # Derive rules from taxonomy files (no rules file needed)
    python -m cookdex.rule_tagger --apply --from-taxonomy

Config file schema (JSON)
--------------------------
    {
      "ingredient_tags":      [{"tag": "...",      "pattern": "...", ...}],
      "text_tags":            [{"tag": "...",      "pattern": "...", ...}],
      "text_categories":      [{"category": "...", "pattern": "...", ...}],
      "ingredient_categories":[{"category": "...", "pattern": "...", ...}],
      "tool_tags":            [{"tool": "...",     "pattern": "..."}]
    }
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import requests as _requests

from .config import REPO_ROOT, config_value, resolve_mealie_api_key, resolve_mealie_url
from .db_client import MealieDBClient, is_db_enabled
from .tag_rules_generation import build_default_tag_rules

DEFAULT_RULES_FILE = str(REPO_ROOT / "configs" / "taxonomy" / "tag_rules.json")
_MISSING_TARGET_CHOICES = {"skip", "create"}


# ---------------------------------------------------------------------------
# Organizer type descriptors — eliminate tag/category code duplication
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _OrgSpec:
    """Describes one kind of organizer (tag, category, or tool)."""
    label: str          # for log messages: "tag", "category", "tool"
    rule_key: str       # key in rule dict: "tag", "category", "tool"
    api_path: str       # Mealie API list/create endpoint
    recipe_field: str   # field on recipe JSON object


_TAG = _OrgSpec("tag", "tag", "organizers/tags", "tags")
_CAT = _OrgSpec("category", "category", "organizers/categories", "recipeCategory")


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
    """Apply rule-based tags, categories, and tool assignments to Mealie recipes."""

    def __init__(
        self,
        rules_file: str = DEFAULT_RULES_FILE,
        *,
        dry_run: bool = True,
        use_db: bool = False,
        missing_targets: str = "skip",
        _rules: dict[str, Any] | None = None,
    ) -> None:
        self.rules_file = rules_file
        self.dry_run = dry_run
        self.use_db = use_db
        self._preloaded_rules = _rules
        mode = str(missing_targets or "skip").strip().lower()
        if mode not in _MISSING_TARGET_CHOICES:
            raise ValueError(
                f"missing_targets must be one of {sorted(_MISSING_TARGET_CHOICES)}"
            )
        self.missing_targets = mode
        self.create_missing_targets = mode == "create"
        self._missing_target_skips = 0

    @classmethod
    def from_taxonomy(
        cls,
        *,
        dry_run: bool = True,
        use_db: bool = False,
        missing_targets: str = "skip",
    ) -> "RecipeRuleTagger":
        """Create a tagger with rules derived at runtime from taxonomy files."""
        tags_path = REPO_ROOT / str(
            config_value("taxonomy.tags_file", "configs/taxonomy/tags.json")
        )
        cats_path = REPO_ROOT / str(
            config_value("taxonomy.categories_file", "configs/taxonomy/categories.json")
        )
        tools_path = REPO_ROOT / str(
            config_value("tools.file", "configs/taxonomy/tools.json")
        )

        def _read_json_list(path: Path) -> list[dict[str, Any]]:
            if not path.exists():
                return []
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                return []

        tags = _read_json_list(tags_path)
        categories = _read_json_list(cats_path)
        tools = _read_json_list(tools_path)

        if not tags and not categories and not tools:
            print(
                "[warn] No taxonomy files found — rule tagger will have zero rules.\n"
                "  Run taxonomy-refresh first, or provide a --config file.",
                flush=True,
            )

        rules = build_default_tag_rules(tags=tags, categories=categories, tools=tools)
        return cls(dry_run=dry_run, use_db=use_db, missing_targets=missing_targets, _rules=rules)

    # ------------------------------------------------------------------
    # Rule helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rule_enabled(rule: dict[str, Any]) -> bool:
        raw = rule.get("enabled", True)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().casefold() not in {"0", "false", "no", "off"}
        return bool(raw)

    @staticmethod
    def _rule_match_on(rule: dict[str, Any]) -> str:
        raw = str(rule.get("match_on") or "").strip().casefold()
        if raw in {"name", "description", "both"}:
            return raw
        return "both"

    @staticmethod
    def _recipe_matches_text(
        recipe: dict[str, Any],
        compiled: re.Pattern[str],
        *,
        match_on: str,
    ) -> bool:
        name = recipe.get("name") or ""
        description = recipe.get("description") or ""
        if match_on == "name":
            return bool(compiled.search(name))
        if match_on == "description":
            return bool(compiled.search(description))
        return bool(compiled.search(name)) or bool(compiled.search(description))

    @staticmethod
    def _compile_pattern(pattern: str) -> re.Pattern[str]:
        return re.compile(pattern.replace(r"\y", r"\b"), re.IGNORECASE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Run all configured rules and return a stats dict."""
        if self._preloaded_rules is not None:
            rules = self._preloaded_rules
        else:
            rules = _load_rules(self.rules_file)

        if self.use_db:
            return self._run_db(rules)
        return self._run_api(rules)

    # ------------------------------------------------------------------
    # API mode
    # ------------------------------------------------------------------

    def _run_api(self, rules: dict[str, Any]) -> dict[str, Any]:
        stats: dict[str, Any] = {
            "ingredient_tags": {},
            "text_tags": {},
            "text_categories": {},
            "ingredient_categories": {},
            "tool_tags": {},
            "missing_target_skips": 0,
        }
        self._missing_target_skips = 0

        skipped: list[str] = []
        for key in ("ingredient_tags", "ingredient_categories", "tool_tags"):
            if rules.get(key):
                skipped.append(key)
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
            f"[start] Rule tagger (API mode) — dry_run={self.dry_run}  missing_targets={self.missing_targets}",
            flush=True,
        )

        text_rules = rules.get("text_tags", [])
        category_rules = rules.get("text_categories", [])
        if text_rules or category_rules:
            all_recipes = self._api_get_all_recipes(mealie_url, headers)
            tag_cache: dict[str, Optional[dict]] = {}
            cat_cache: dict[str, Optional[dict]] = {}
            for rule in text_rules:
                name = rule.get("tag", "")
                stats["text_tags"][name] = self._api_apply_text_rule(
                    all_recipes, rule, _TAG, mealie_url, headers, tag_cache,
                )
            for rule in category_rules:
                name = rule.get("category", "")
                stats["text_categories"][name] = self._api_apply_text_rule(
                    all_recipes, rule, _CAT, mealie_url, headers, cat_cache,
                )

        total_tags = sum(stats["text_tags"].values())
        total_cats = sum(stats["text_categories"].values())
        print(
            f"[done] {total_tags + total_cats} assignment(s) — "
            f"{len(stats['text_tags'])} tag rule(s), {len(stats['text_categories'])} category rule(s)",
            flush=True,
        )
        print("[summary] " + json.dumps({
            "__title__": "Rule Tagger",
            "Total Assignments": total_tags + total_cats,
            "Tag Rules": len(stats["text_tags"]),
            "Category Rules": len(stats["text_categories"]),
            "Missing Target Rules Skipped": self._missing_target_skips,
            "Dry Run": self.dry_run,
        }), flush=True)
        stats["missing_target_skips"] = self._missing_target_skips
        if self.dry_run:
            print("[dry-run] No changes written.", flush=True)
        return stats

    def _api_get_all_recipes(
        self, mealie_url: str, headers: dict
    ) -> list[dict]:
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
            if not (isinstance(next_link, str) and next_link):
                url = None
            elif next_link.startswith("/"):
                url = mealie_url + next_link
            else:
                url = next_link
        return recipes

    def _api_get_or_create(
        self,
        name: str,
        spec: _OrgSpec,
        mealie_url: str,
        headers: dict,
        cache: dict[str, Optional[dict]],
    ) -> Optional[dict]:
        """Return existing organizer (tag/category) by name, or create it; cached."""
        key = name.lower()
        if key in cache:
            return cache[key]

        resp = _requests.get(
            f"{mealie_url}/{spec.api_path}?perPage=1000", headers=headers, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        all_items = data.get("items", data) if isinstance(data, dict) else data
        for item in all_items:
            cache[item["name"].lower()] = item

        if key in cache:
            return cache[key]

        if not self.create_missing_targets:
            cache[key] = None
            return None

        if self.dry_run:
            placeholder = {"id": "dry-run-id", "name": name, "slug": "dry-run"}
            cache[key] = placeholder
            return placeholder

        resp = _requests.post(
            f"{mealie_url}/{spec.api_path}",
            json={"name": name},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        created = resp.json()
        cache[created["name"].lower()] = created
        return created

    def _api_apply_text_rule(
        self,
        all_recipes: list[dict],
        rule: dict[str, Any],
        spec: _OrgSpec,
        mealie_url: str,
        headers: dict,
        cache: dict[str, Optional[dict]],
    ) -> int:
        """Match text pattern against recipe name/description; add tag or category via API."""
        if not self._rule_enabled(rule):
            return 0
        target_name: str = rule[spec.rule_key]
        compiled = self._compile_pattern(rule["pattern"])
        match_on = self._rule_match_on(rule)

        matched = [
            r for r in all_recipes
            if self._recipe_matches_text(r, compiled, match_on=match_on)
        ]
        if not matched:
            return 0

        count = len(matched)
        print(
            f"[info] {spec.label} '{target_name}': {count} recipe(s) matched"
            f"{' (dry-run)' if self.dry_run else ''}",
            flush=True,
        )

        org = self._api_get_or_create(target_name, spec, mealie_url, headers, cache)
        if org is None:
            self._missing_target_skips += 1
            print(
                f"[skip] {spec.label} '{target_name}' is not in current Mealie taxonomy "
                f"(missing_targets={self.missing_targets}).",
                flush=True,
            )
            return 0
        org_id = org["id"]

        if not self.dry_run:
            for recipe in matched:
                existing_ids = {item.get("id") for item in (recipe.get(spec.recipe_field) or [])}
                if org_id in existing_ids:
                    continue
                slug = recipe["slug"]
                resp = _requests.get(
                    f"{mealie_url}/recipes/{slug}", headers=headers, timeout=30
                )
                if not resp.ok:
                    print(f"[warn] Could not fetch '{slug}': {resp.status_code}", flush=True)
                    continue
                full = resp.json()
                full[spec.recipe_field] = (full.get(spec.recipe_field) or []) + [
                    {"id": org_id, "name": org["name"], "slug": org.get("slug", "")}
                ]
                patch = _requests.patch(
                    f"{mealie_url}/recipes/{slug}",
                    json=full,
                    headers=headers,
                    timeout=30,
                )
                if patch.status_code == 403:
                    print(f"[warn] PATCH '{slug}' returned 403 (Mealie slug-mismatch bug)", flush=True)
                elif not patch.ok:
                    print(f"[warn] PATCH failed for '{slug}': {patch.status_code}", flush=True)

        return count

    # ------------------------------------------------------------------
    # DB mode
    # ------------------------------------------------------------------

    def _run_db(self, rules: dict[str, Any]) -> dict[str, Any]:
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
            "text_categories": {},
            "ingredient_categories": {},
            "tool_tags": {},
            "missing_target_skips": 0,
        }
        self._missing_target_skips = 0

        with MealieDBClient() as db:
            group_id = db.get_group_id()
            if not group_id:
                print("[error] Could not determine group_id from database.", flush=True)
                sys.exit(1)

            print(
                f"[start] Rule tagger (DB mode) — dry_run={self.dry_run}  "
                f"group_id={group_id}  missing_targets={self.missing_targets}",
                flush=True,
            )

            for rule in rules.get("ingredient_tags", []):
                name = rule.get("tag", "")
                stats["ingredient_tags"][name] = self._db_apply_ingredient_rule(
                    db, group_id, rule, _TAG,
                )
            for rule in rules.get("text_tags", []):
                name = rule.get("tag", "")
                stats["text_tags"][name] = self._db_apply_text_rule(db, group_id, rule, _TAG)
            for rule in rules.get("text_categories", []):
                name = rule.get("category", "")
                stats["text_categories"][name] = self._db_apply_text_rule(db, group_id, rule, _CAT)
            for rule in rules.get("ingredient_categories", []):
                name = rule.get("category", "")
                stats["ingredient_categories"][name] = self._db_apply_ingredient_rule(
                    db, group_id, rule, _CAT,
                )
            for rule in rules.get("tool_tags", []):
                name = rule.get("tool", "")
                stats["tool_tags"][name] = self._db_apply_tool_rule(db, group_id, rule)

        total = sum(
            sum(stats[key].values())
            for key in ("ingredient_tags", "text_tags", "text_categories", "ingredient_categories", "tool_tags")
        )
        print("[summary] " + json.dumps({
            "__title__": "Rule Tagger",
            "Total Assignments": total,
            "Ingredient Tag Rules": len(stats["ingredient_tags"]),
            "Text Tag Rules": len(stats["text_tags"]),
            "Text Category Rules": len(stats["text_categories"]),
            "Ingredient Category Rules": len(stats["ingredient_categories"]),
            "Tool Rules": len(stats["tool_tags"]),
            "Missing Target Rules Skipped": self._missing_target_skips,
            "Dry Run": self.dry_run,
        }), flush=True)
        stats["missing_target_skips"] = self._missing_target_skips
        if self.dry_run:
            print("[dry-run] No changes written.", flush=True)
        return stats

    # --- DB resolvers (tag / category / tool) ---

    def _db_resolve_id(
        self,
        db: MealieDBClient,
        group_id: str,
        name: str,
        lookup: Callable[[str, str], Optional[str]],
        ensure: Callable[..., Optional[str]],
        label: str,
    ) -> Optional[str]:
        if self.create_missing_targets:
            return ensure(name, group_id, dry_run=self.dry_run)
        found = lookup(name, group_id)
        if found:
            return found
        self._missing_target_skips += 1
        print(
            f"[skip] {label} '{name}' is not in current taxonomy (missing_targets={self.missing_targets}).",
            flush=True,
        )
        return None

    def _db_resolve_tag_id(self, db: MealieDBClient, group_id: str, name: str) -> Optional[str]:
        return self._db_resolve_id(db, group_id, name, db.lookup_tag_id, db.ensure_tag, "tag")

    def _db_resolve_category_id(self, db: MealieDBClient, group_id: str, name: str) -> Optional[str]:
        return self._db_resolve_id(db, group_id, name, db.lookup_category_id, db.ensure_category, "category")

    def _db_resolve_tool_id(self, db: MealieDBClient, group_id: str, name: str) -> Optional[str]:
        return self._db_resolve_id(db, group_id, name, db.lookup_tool_id, db.ensure_tool, "tool")

    # --- DB rule application ---

    def _db_apply_text_rule(
        self,
        db: MealieDBClient,
        group_id: str,
        rule: dict[str, Any],
        spec: _OrgSpec,
    ) -> int:
        if not self._rule_enabled(rule):
            return 0
        name: str = rule[spec.rule_key]
        match_on = self._rule_match_on(rule)
        resolve = self._db_resolve_tag_id if spec is _TAG else self._db_resolve_category_id
        link = db.link_tag if spec is _TAG else db.link_category

        org_id = resolve(db, group_id, name)
        if not org_id:
            return 0

        recipe_ids = db.find_recipe_ids_by_text(group_id, rule["pattern"], match_on=match_on)
        if recipe_ids:
            print(
                f"[text] '{name}': {len(recipe_ids)} recipe(s) matched"
                f"{' (dry-run)' if self.dry_run else ''}",
                flush=True,
            )
        for recipe_id in recipe_ids:
            link(recipe_id, org_id, dry_run=self.dry_run)
        return len(recipe_ids)

    def _db_apply_ingredient_rule(
        self,
        db: MealieDBClient,
        group_id: str,
        rule: dict[str, Any],
        spec: _OrgSpec,
    ) -> int:
        name: str = rule[spec.rule_key]
        pattern: str = rule["pattern"]
        exclude: str = rule.get("exclude_pattern", "")
        min_matches: int = int(rule.get("min_matches", 1))
        resolve = self._db_resolve_tag_id if spec is _TAG else self._db_resolve_category_id
        link = db.link_tag if spec is _TAG else db.link_category

        org_id = resolve(db, group_id, name)
        if not org_id:
            return 0

        recipe_ids = db.find_recipe_ids_by_ingredient(
            group_id, pattern, exclude_pattern=exclude, min_matches=min_matches,
        )
        if recipe_ids:
            label = "ingredient" if spec is _TAG else "ingredient-category"
            print(
                f"[{label}] '{name}': {len(recipe_ids)} recipe(s) matched"
                f"{' (dry-run)' if self.dry_run else ''}",
                flush=True,
            )
        for recipe_id in recipe_ids:
            link(recipe_id, org_id, dry_run=self.dry_run)
        return len(recipe_ids)

    def _db_apply_tool_rule(
        self,
        db: MealieDBClient,
        group_id: str,
        rule: dict[str, Any],
    ) -> int:
        tool_name: str = rule["tool"]
        tool_id = self._db_resolve_tool_id(db, group_id, tool_name)
        if not tool_id:
            return 0

        recipe_ids = db.find_recipe_ids_by_instruction(group_id, rule["pattern"])
        if recipe_ids:
            print(
                f"[tool] '{tool_name}': {len(recipe_ids)} recipe(s) matched"
                f"{' (dry-run)' if self.dry_run else ''}",
                flush=True,
            )
        for recipe_id in recipe_ids:
            db.link_tool(recipe_id, tool_id, dry_run=self.dry_run)
        return len(recipe_ids)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Rule-based recipe tagger — assigns tags/tools via regex rules, no LLM required.\n"
            "API mode (default): runs text_tags rules via Mealie HTTP API.\n"
            "--use-db: adds ingredient and tool matching via direct DB queries.\n"
            "--from-taxonomy: derive rules at runtime from taxonomy config files."
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
    parser.add_argument(
        "--from-taxonomy",
        action="store_true",
        default=False,
        help=(
            "Derive rules at runtime from taxonomy config files (tags.json, "
            "categories.json, tools.json) instead of loading tag_rules.json."
        ),
    )
    parser.add_argument(
        "--missing-targets",
        choices=sorted(_MISSING_TARGET_CHOICES),
        default="skip",
        help=(
            "How to handle rules whose target tag/category/tool is missing from current taxonomy: "
            "'skip' (default) or 'create'."
        ),
    )
    args = parser.parse_args()

    if args.from_taxonomy:
        tagger = RecipeRuleTagger.from_taxonomy(
            dry_run=not args.apply,
            use_db=args.use_db,
            missing_targets=args.missing_targets,
        )
    else:
        tagger = RecipeRuleTagger(
            rules_file=args.config,
            dry_run=not args.apply,
            use_db=args.use_db,
            missing_targets=args.missing_targets,
        )
    tagger.run()


if __name__ == "__main__":
    main()
