"""Recipe Name Normalizer.

Cleans up recipe names that were auto-generated from URL slugs during import,
turning strings like "how-to-make-chicken-pasta-recipe" into "Chicken Pasta".

Transformations applied (in order):
  1. Replace hyphens and underscores with spaces.
  2. Collapse repeated whitespace.
  3. Strip common URL-artifact prefixes: "recipe for", "how to make",
     "how to cook", "how to", "make", "cook".
  4. Strip trailing word "recipe".
  5. Smart title-case (preserves small words, apostrophes, and acronyms).

A recipe is a candidate for renaming when its name is entirely lowercase
(i.e. it was never given proper casing by a human).  You can also force all
recipes through the normalizer with --all.

Writes PATCH calls to Mealie via the HTTP API.  Use DRY_RUN=true (the default)
to preview changes without writing anything.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api_client import MealieApiClient
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url, resolve_repo_path, to_bool

DEFAULT_REPORT = "reports/recipe_name_normalize_report.json"
DEFAULT_WORKERS = 8

# Ordered from most-specific to least-specific.
_PREFIX_PATTERNS: list[re.Pattern] = [
    re.compile(r"^recipe\s+for\s+", re.IGNORECASE),
    re.compile(r"^how\s+to\s+(?:make|cook)\s+", re.IGNORECASE),
    re.compile(r"^how\s+to\s+", re.IGNORECASE),
    re.compile(r"^(?:make|cook)\s+", re.IGNORECASE),
]
_SUFFIX_PATTERN = re.compile(r"\s+recipe$", re.IGNORECASE)
_HAS_UPPERCASE_RE = re.compile(r"[A-Z]")

# Words that stay lowercase in title case (except when first or last).
_SMALL_WORDS: frozenset[str] = frozenset({
    "a", "an", "the",
    "and", "but", "or", "nor", "for", "yet", "so",
    "at", "by", "in", "of", "on", "to", "up", "as",
    "from", "into", "with", "over", "via", "per",
    "vs",
})

# Common food/cooking abbreviations that should stay uppercase.
_ACRONYMS: dict[str, str] = {
    "bbq": "BBQ", "blt": "BLT", "gf": "GF", "diy": "DIY",
    "pb": "PB", "pbj": "PBJ", "xo": "XO", "hk": "HK",
    "thc": "THC", "vgf": "VGF", "ac": "AC",
}


def _title_case_word(word: str) -> str:
    """Capitalize a single word, handling apostrophes correctly."""
    if "'" in word:
        # "valentine's" → "Valentine's",  "don't" → "Don't"
        parts = word.split("'", 1)
        return parts[0].capitalize() + "'" + parts[1]
    return word.capitalize()


def _smart_title_case(text: str) -> str:
    """Title-case *text* following standard English conventions.

    - Small words (a, an, the, and, of, ...) stay lowercase unless first/last.
    - Apostrophe contractions and possessives keep correct casing.
    - Known acronyms (BBQ, BLT, ...) are uppercased.
    """
    words = text.lower().split()
    if not words:
        return text
    result: list[str] = []
    last_idx = len(words) - 1
    for i, word in enumerate(words):
        # Strip surrounding punctuation for dictionary lookups.
        stripped = word.strip(",:;!?\"'()-")
        if stripped in _ACRONYMS:
            result.append(word.replace(stripped, _ACRONYMS[stripped]))
        elif i == 0 or i == last_idx or stripped not in _SMALL_WORDS:
            result.append(_title_case_word(word))
        else:
            result.append(word)  # already lowercase
    return " ".join(result)


def normalize_recipe_name(raw: str) -> str:
    """Return a cleaned version of *raw*, or the original if no change needed."""
    name = raw.replace("-", " ").replace("_", " ")
    name = re.sub(r"\s+", " ", name).strip()
    for pat in _PREFIX_PATTERNS:
        name = pat.sub("", name).strip()
    name = _SUFFIX_PATTERN.sub("", name).strip()
    return _smart_title_case(name)


def _looks_unformatted(name: str) -> bool:
    """True when the name has no uppercase letters, indicating it was
    auto-generated from a URL slug or import and never human-edited."""
    return not _HAS_UPPERCASE_RE.search(name)


def _should_normalize(recipe: dict[str, Any], *, force_all: bool) -> bool:
    name = str(recipe.get("name") or "").strip()
    slug = str(recipe.get("slug") or "").strip()
    if not name or not slug:
        return False
    if force_all:
        return normalize_recipe_name(name) != name
    return _looks_unformatted(name) and normalize_recipe_name(name) != name


@dataclass
class NameAction:
    slug: str
    old_name: str
    new_name: str


def _analyze_recipe(recipe: dict[str, Any], *, force_all: bool) -> NameAction | None:
    if not _should_normalize(recipe, force_all=force_all):
        return None
    old_name = str(recipe.get("name") or "").strip()
    new_name = normalize_recipe_name(old_name)
    if new_name == old_name:
        return None
    return NameAction(slug=str(recipe.get("slug") or ""), old_name=old_name, new_name=new_name)


class RecipeNameNormalizer:
    def __init__(
        self,
        client: MealieApiClient,
        *,
        dry_run: bool = True,
        apply: bool = False,
        force_all: bool = False,
        report_file: Path | str = DEFAULT_REPORT,
        workers: int = DEFAULT_WORKERS,
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.apply = apply
        self.force_all = force_all
        self.report_file = Path(report_file)
        self.workers = workers

    def _apply_concurrent(self, actions: list[NameAction]) -> tuple[list[dict], int, int]:
        action_log: list[dict] = []
        applied = 0
        failed = 0

        def _patch(action: NameAction) -> tuple[NameAction, bool, str]:
            try:
                self.client.patch_recipe(action.slug, {"name": action.new_name})
                return action, True, ""
            except Exception as exc:
                return action, False, str(exc)

        total = len(actions)
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(_patch, a): a for a in actions}
            for idx, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                action, ok, err = fut.result()
                if ok:
                    applied += 1
                    action_log.append({"status": "ok", "slug": action.slug, "old_name": action.old_name, "new_name": action.new_name})
                    print(f"[ok] {idx}/{total} {action.slug}: '{action.old_name}' → '{action.new_name}'", flush=True)
                else:
                    failed += 1
                    action_log.append({"status": "error", "slug": action.slug, "error": err})
                    print(f"[error] {action.slug}: {err}", flush=True)

        return action_log, applied, failed

    def run(self) -> dict[str, Any]:
        executable = self.apply and not self.dry_run

        print("[start] Fetching all recipes from API ...", flush=True)
        recipes = self.client.get_recipes()
        total = len(recipes)

        actions: list[NameAction] = []
        for r in recipes:
            action = _analyze_recipe(r, force_all=self.force_all)
            if action:
                actions.append(action)

        mode_label = "all recipes" if self.force_all else "slug-derived names only"
        print(
            f"[start] {total} recipes scanned ({mode_label}) → {len(actions)} names to normalize",
            flush=True,
        )

        action_log: list[dict] = []
        applied = 0
        failed = 0

        if executable:
            print(f"[start] Applying {len(actions)} name patches (workers={self.workers}) ...", flush=True)
            action_log, applied, failed = self._apply_concurrent(actions)
        else:
            for action in actions:
                action_log.append({
                    "status": "planned",
                    "slug": action.slug,
                    "old_name": action.old_name,
                    "new_name": action.new_name,
                })
                print(f"[plan] {action.slug}: '{action.old_name}' → '{action.new_name}'", flush=True)

        report: dict[str, Any] = {
            "summary": {
                "total_recipes": total,
                "candidates": len(actions),
                "applied": applied,
                "failed": failed,
                "mode": "apply" if executable else "audit",
                "scope": "all" if self.force_all else "slug-derived",
            },
            "actions": action_log,
        }

        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        self.report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        mode = "apply" if executable else "audit"
        scope = "all" if self.force_all else "slug-derived"
        print(
            f"[done] {len(actions)} name(s) to normalize ({scope}) — "
            f"{applied} applied ({mode} mode)",
            flush=True,
        )
        print("[summary] " + json.dumps({
            "Total Recipes": total,
            "Candidates": len(actions),
            "Applied": applied,
            "Failed": failed,
            "Scope": scope,
            "Mode": mode,
        }), flush=True)
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize recipe names derived from URL slugs.")
    parser.add_argument("--apply", action="store_true", help="Write name changes to Mealie.")
    parser.add_argument(
        "--all",
        dest="force_all",
        action="store_true",
        help="Normalize all recipes, not just those whose names match their slugs.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Concurrent API workers when applying.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    if dry_run:
        print("[start] runtime.dry_run=true (writes disabled; planning only).", flush=True)
    normalizer = RecipeNameNormalizer(
        MealieApiClient(
            base_url=resolve_mealie_url(),
            api_key=resolve_mealie_api_key(required=True),
            timeout_seconds=60,
            retries=3,
            backoff_seconds=0.4,
        ),
        dry_run=dry_run,
        apply=bool(args.apply),
        force_all=bool(args.force_all),
        report_file=resolve_repo_path(DEFAULT_REPORT),
        workers=args.workers,
    )
    normalizer.run()


if __name__ == "__main__":
    main()
