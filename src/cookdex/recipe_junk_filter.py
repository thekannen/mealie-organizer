"""Recipe Junk Filter.

Detects and removes non-recipe content that slipped in during bulk import:
listicles, how-to articles, digest posts, utility pages, and recipes with
placeholder or missing instructions.

Detection logic (per recipe, applied in order):
  1. How-to articles  – name/slug starts with "how to make/cook"
  2. Listicles        – "top 10 recipes", "best X desserts", numbered collections
  3. Digest posts     – "friday finds", "weekly roundup", "monthly report", etc.
  4. High-risk keywords – cleaning, storing, review, giveaway, beauty, detox, etc.
  5. Utility pages    – slug contains privacy-policy, about-us, contact, login, etc.
  6. Bad instructions – placeholder text ("could not detect", "unavailable") or empty

In dry-run mode (default) the tool reports what would be deleted without touching
anything.  Pass --apply to actually delete.

Use --reason to filter by a specific junk category only.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api_client import MealieApiClient
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url, resolve_repo_path, to_bool

DEFAULT_REPORT = "reports/recipe_junk_filter_report.json"

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

_HOW_TO_RE = re.compile(r"^how\s+to\s+(?:make|cook)\b", re.IGNORECASE)

_LISTICLE_RE = re.compile(
    r"\b(top|best)\b.*\b(recipes?|meals?|dishes?|desserts?|breakfasts?|lunches?|dinners?|snacks?|drinks?)\b"
    r"|^\s*\d{1,3}\b.*\b(recipes?|meals?|dishes?)\b",
    re.IGNORECASE,
)

_DIGEST_RE = re.compile(
    r"\b(friday\s*finds?|sunday\s*stuff|weekly\s*round\s*up|monthly\s*report"
    r"|weekend\s*reads?|favorites?\s*of\s*the\s*week|what\s*i\s*ate"
    r"|meal\s*plan|menu\s*plan|weekly\s*menu|holiday\s*guide)\b",
    re.IGNORECASE,
)

_HIGH_RISK_KEYWORDS = frozenset({
    "cleaning", "storing", "freezing", "pantry", "kitchen tools",
    "review", "giveaway", "shop", "store", "product", "gift", "unboxing",
    "news", "travel", "podcast", "interview",
    "night cream", "face mask", "skin care", "beauty", "diy",
    "detox water", "lose weight", "taste test", "clear winner",
    "foods to try", "things to eat", "we tried",
})

_UTILITY_SLUGS = frozenset({
    "privacy-policy", "contact", "about-us", "about", "login",
    "cart", "checkout", "terms", "terms-of-service", "disclaimer",
    "sitemap", "404", "page-not-found",
})

_BAD_INSTRUCTIONS = frozenset({
    "could not detect instructions",
    "instruction unavailable",
    "no instructions found",
    "instructions not available",
    "unable to extract instructions",
})


def _classify(name: str, slug: str, instructions_text: str) -> tuple[str | None, str]:
    """Return (reason_code, human_reason) or (None, '') if the recipe is clean."""
    name_lower = name.lower()
    slug_lower = slug.lower()

    # 1. How-to
    if _HOW_TO_RE.search(name_lower) or _HOW_TO_RE.search(slug_lower.replace("-", " ")):
        return "how_to", "How-to article (not a recipe)"

    # 2. Listicle
    if _LISTICLE_RE.search(name_lower):
        return "listicle", "Listicle / roundup post"

    # 3. Digest
    if _DIGEST_RE.search(name_lower) or _DIGEST_RE.search(slug_lower.replace("-", " ")):
        return "digest", "Digest / weekly post"

    # 4. High-risk keywords
    for kw in _HIGH_RISK_KEYWORDS:
        if kw in name_lower:
            return "keyword", f"High-risk keyword: '{kw}'"

    # 5. Utility pages
    for util in _UTILITY_SLUGS:
        if util in slug_lower:
            return "utility", f"Utility page slug: '{util}'"

    # 6. Bad instructions
    if instructions_text:
        inst_lower = instructions_text.lower().strip()
        for bad in _BAD_INSTRUCTIONS:
            if bad in inst_lower:
                return "bad_instructions", f"Placeholder instruction text: '{bad}'"
    else:
        return "no_instructions", "Recipe has no instructions"

    return None, ""


def _extract_instructions_text(recipe: dict[str, Any]) -> str:
    """Flatten recipeInstructions to a plain string for matching."""
    raw = recipe.get("recipeInstructions")
    if not raw:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or ""))
        return " ".join(parts)
    return str(raw)


@dataclass
class JunkAction:
    slug: str
    name: str
    reason_code: str
    reason: str


def _analyze_recipe(recipe: dict[str, Any], *, filter_reason: str | None) -> JunkAction | None:
    name = str(recipe.get("name") or "").strip()
    slug = str(recipe.get("slug") or "").strip()
    instructions_text = _extract_instructions_text(recipe)
    reason_code, reason = _classify(name, slug, instructions_text)
    if not reason_code:
        return None
    if filter_reason and reason_code != filter_reason:
        return None
    return JunkAction(slug=slug, name=name, reason_code=reason_code, reason=reason)


class RecipeJunkFilter:
    def __init__(
        self,
        client: MealieApiClient,
        *,
        dry_run: bool = True,
        apply: bool = False,
        filter_reason: str | None = None,
        report_file: Path | str = DEFAULT_REPORT,
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.apply = apply
        self.filter_reason = filter_reason
        self.report_file = Path(report_file)

    def run(self) -> dict[str, Any]:
        executable = self.apply and not self.dry_run

        print("[start] Fetching all recipes from API ...", flush=True)
        recipes = self.client.get_recipes()
        total = len(recipes)

        actions: list[JunkAction] = []
        for r in recipes:
            action = _analyze_recipe(r, filter_reason=self.filter_reason)
            if action:
                actions.append(action)

        by_reason: dict[str, int] = {}
        for a in actions:
            by_reason[a.reason_code] = by_reason.get(a.reason_code, 0) + 1

        print(
            f"[start] {total} recipes scanned → {len(actions)} junk recipes detected",
            flush=True,
        )
        for code, count in sorted(by_reason.items()):
            print(f"  {code}: {count}", flush=True)

        action_log: list[dict] = []
        deleted = 0
        failed = 0

        for action in actions:
            entry: dict[str, Any] = {
                "slug": action.slug,
                "name": action.name,
                "reason_code": action.reason_code,
                "reason": action.reason,
            }
            if executable:
                try:
                    self.client.delete_recipe(action.slug)
                    entry["status"] = "deleted"
                    deleted += 1
                    print(f"[ok] deleted '{action.name}' ({action.slug}) — {action.reason}", flush=True)
                except Exception as exc:
                    entry["status"] = "error"
                    entry["error"] = str(exc)
                    failed += 1
                    print(f"[error] {action.slug}: {exc}", flush=True)
            else:
                entry["status"] = "planned"
                print(f"[plan] '{action.name}' ({action.slug}) — {action.reason}", flush=True)
            action_log.append(entry)

        report: dict[str, Any] = {
            "summary": {
                "total_recipes": total,
                "junk_found": len(actions),
                "by_reason": by_reason,
                "deleted": deleted,
                "failed": failed,
                "mode": "apply" if executable else "audit",
            },
            "actions": action_log,
        }

        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        self.report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[done] Junk filter report written to {self.report_file}", flush=True)
        print(
            f'[summary] {{"total": {total}, "junk": {len(actions)}, '
            f'"deleted": {deleted}, "failed": {failed}, '
            f'"mode": "{"apply" if executable else "audit"}"}}',
            flush=True,
        )
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect and remove junk recipes from Mealie.")
    parser.add_argument("--apply", action="store_true", help="Delete junk recipes from Mealie.")
    parser.add_argument(
        "--reason",
        choices=["how_to", "listicle", "digest", "keyword", "utility", "bad_instructions", "no_instructions"],
        default=None,
        help="Only process recipes matching this specific junk category.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    if dry_run:
        print("[start] runtime.dry_run=true (writes disabled; planning only).", flush=True)
    junk_filter = RecipeJunkFilter(
        MealieApiClient(
            base_url=resolve_mealie_url(),
            api_key=resolve_mealie_api_key(required=True),
            timeout_seconds=60,
            retries=3,
            backoff_seconds=0.4,
        ),
        dry_run=dry_run,
        apply=bool(args.apply),
        filter_reason=args.reason,
        report_file=resolve_repo_path(DEFAULT_REPORT),
    )
    junk_filter.run()


if __name__ == "__main__":
    main()
