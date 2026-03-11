"""Recipe Re-importer.

Re-scrapes recipes from their original source URLs via Mealie's test-scrape
endpoint (no temp recipes created).  The freshly scraped content overwrites
the existing recipe in-place.  Metadata that took compute hours to assign —
tags, categories, tools, rating, favorites — is preserved.  Ingredients are
imported as raw text (unparsed) so the ingredient parser can process them.

Workflow per recipe:
  1. POST /recipes/test-scrape-url  → raw JSON-LD scraped data (no DB write)
  2. GET  /recipes/{slug}           → snapshot preserved metadata
  3. PATCH /recipes/{slug}          → merge scraped content + preserved metadata

Scraping is parallelised with a thread pool (I/O-bound on external sites).

Use DRY_RUN=true (the default) to preview without modifying anything.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import uuid
from pathlib import Path
from typing import Any

from .api_client import MealieApiClient
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url, resolve_repo_path, to_bool

DEFAULT_REPORT = "reports/recipe_reimport_report.json"
_MAX_WORKERS = 4

_SOURCE_FIELDS = ("orgURL", "originalURL", "source")

# Fields to preserve from the original recipe (not overwritten by scrape).
_PRESERVE_FIELDS = (
    "tags",
    "recipeCategory",
    "tools",
    "rating",
    "settings",
    "extras",
    "comments",
    "notes",
    "dateAdded",
)


def _extract_url(recipe: dict[str, Any]) -> str:
    """Return the first non-empty HTTP(S) URL from source fields."""
    for field in _SOURCE_FIELDS:
        val = recipe.get(field)
        if val and isinstance(val, str):
            val = val.strip()
            if val.lower().startswith(("http://", "https://")):
                return val
    return ""


def _jsonld_to_ingredients(raw: list[Any]) -> list[dict[str, Any]]:
    """Convert JSON-LD ingredient strings into Mealie ingredient dicts."""
    ingredients: list[dict[str, Any]] = []
    for item in raw:
        text = str(item).strip() if item else ""
        if not text:
            continue
        ingredients.append({
            "quantity": 0,
            "unit": None,
            "food": None,
            "note": text,
            "display": text,
            "title": None,
            "originalText": text,
            "referenceId": str(uuid.uuid4()),
        })
    return ingredients


def _jsonld_to_instructions(raw: list[Any]) -> list[dict[str, Any]]:
    """Convert JSON-LD instruction objects into Mealie instruction dicts."""
    instructions: list[dict[str, Any]] = []
    for item in raw:
        text = ""
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = item.get("text", "")
        if not text:
            continue
        instructions.append({
            "id": str(uuid.uuid4()),
            "title": "",
            "summary": "",
            "text": text,
            "ingredientReferences": [],
        })
    return instructions


def _extract_time(raw: Any) -> str | None:
    """Return a duration string or None."""
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _extract_yield(raw: Any) -> str | None:
    """Extract yield string from JSON-LD (may be a list)."""
    if isinstance(raw, list):
        return str(raw[0]).strip() if raw else None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _extract_nutrition(raw: Any) -> dict[str, str] | None:
    """Extract nutrition dict, stripping JSON-LD @type."""
    if not isinstance(raw, dict):
        return None
    return {k: v for k, v in raw.items() if k != "@type"}


class RecipeReimporter:
    def __init__(
        self,
        client: MealieApiClient,
        *,
        dry_run: bool = True,
        max_recipes: int = 0,
        max_workers: int = _MAX_WORKERS,
        slugs_filter: list[str] | None = None,
        report_file: Path | str = DEFAULT_REPORT,
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.max_recipes = max_recipes
        self.max_workers = max_workers
        self.slugs_filter = set(slugs_filter) if slugs_filter else None
        self.report_file = Path(report_file)

    def run(self) -> dict[str, Any]:
        print("[start] Fetching all recipes from API ...", flush=True)
        recipes = self.client.get_recipes()
        total = len(recipes)

        # Filter to recipes with a valid source URL.
        candidates: list[tuple[str, str, str]] = []  # (slug, name, url)
        for r in recipes:
            url = _extract_url(r)
            if not url:
                continue
            slug = r.get("slug", "")
            if self.slugs_filter and slug not in self.slugs_filter:
                continue
            candidates.append((slug, str(r.get("name", "")), url))

        if self.max_recipes > 0:
            candidates = candidates[: self.max_recipes]

        print(
            f"[start] {total} recipes scanned, {len(candidates)} eligible for reimport"
            + (f" (capped at {self.max_recipes})" if self.max_recipes > 0 else ""),
            flush=True,
        )

        if self.dry_run:
            action_log = []
            for idx, (slug, name, url) in enumerate(candidates, 1):
                print(f"[plan] {idx}/{len(candidates)} {slug}: would reimport from {url}", flush=True)
                action_log.append({"slug": slug, "name": name, "url": url, "status": "planned"})
            return self._finish(total, candidates, action_log, 0, 0, 0)

        # Live mode: parallel scrape, sequential patch.
        action_log: list[dict[str, Any]] = []
        reimported = 0
        failed = 0
        skipped = 0
        n = len(candidates)

        # Phase 1: Scrape all URLs in parallel (I/O-bound).
        print(f"[start] Scraping {n} URLs with {self.max_workers} threads ...", flush=True)
        scraped_data: dict[str, dict[str, Any] | Exception] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_slug = {
                pool.submit(self._scrape_url, url): (slug, url)
                for slug, _name, url in candidates
            }
            done_count = 0
            for future in concurrent.futures.as_completed(future_to_slug):
                slug, url = future_to_slug[future]
                done_count += 1
                try:
                    scraped_data[slug] = future.result()
                    print(f"[info] scraped {done_count}/{n} {slug}", flush=True)
                except Exception as exc:
                    scraped_data[slug] = exc
                    print(f"[error] scrape {done_count}/{n} {slug}: {exc}", flush=True)

        # Phase 2: Apply patches sequentially.
        print(f"[start] Applying {n} patches ...", flush=True)
        for idx, (slug, name, url) in enumerate(candidates, 1):
            data = scraped_data.get(slug)
            if isinstance(data, Exception):
                action_log.append({"slug": slug, "name": name, "url": url, "status": "error", "error": str(data)})
                failed += 1
                continue
            if data is None:
                action_log.append({"slug": slug, "name": name, "url": url, "status": "skipped"})
                skipped += 1
                continue

            result = self._apply_patch(idx, n, slug, name, url, data)
            action_log.append(result)
            if result["status"] == "reimported":
                reimported += 1
            elif result["status"] == "error":
                failed += 1
            else:
                skipped += 1

        return self._finish(total, candidates, action_log, reimported, failed, skipped)

    def _scrape_url(self, url: str) -> dict[str, Any]:
        """Scrape a URL using Mealie's test-scrape endpoint (no temp recipe)."""
        return self.client.request_json(
            "POST",
            "/recipes/test-scrape-url",
            json={"url": url, "useOpenAI": False},
            timeout=120,
        )

    def _apply_patch(
        self, idx: int, total: int, slug: str, name: str, url: str,
        scraped: dict[str, Any],
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {"slug": slug, "name": name, "url": url}
        try:
            # Fetch original to snapshot preserved metadata.
            original = self.client.get_recipe(slug)

            # Build patch from scraped JSON-LD data.
            patch: dict[str, Any] = {}

            if scraped.get("name"):
                patch["name"] = str(scraped["name"]).strip()
            if scraped.get("description"):
                patch["description"] = str(scraped["description"]).strip()

            # Ingredients: convert raw strings to proper Mealie format.
            raw_ings = scraped.get("recipeIngredient", [])
            if raw_ings:
                patch["recipeIngredient"] = _jsonld_to_ingredients(raw_ings)

            # Instructions: convert JSON-LD to Mealie format.
            raw_steps = scraped.get("recipeInstructions", [])
            if raw_steps:
                patch["recipeInstructions"] = _jsonld_to_instructions(raw_steps)

            # Nutrition.
            nutrition = _extract_nutrition(scraped.get("nutrition"))
            if nutrition:
                patch["nutrition"] = nutrition

            # Times.
            for time_field in ("prepTime", "totalTime", "cookTime", "performTime"):
                val = _extract_time(scraped.get(time_field))
                if val:
                    patch[time_field] = val

            # Yield.
            yield_val = _extract_yield(scraped.get("recipeYield"))
            if yield_val:
                patch["recipeYield"] = yield_val

            # Keep source URL.
            patch["orgURL"] = url

            # Restore preserved metadata from original.
            for field in _PRESERVE_FIELDS:
                if field in original:
                    patch[field] = original[field]

            # Apply.
            self.client.patch_recipe(slug, patch)

            entry["status"] = "reimported"
            ing_count = len(patch.get("recipeIngredient", []))
            print(f"[ok] {idx}/{total} {slug}: reimported ({ing_count} ingredients)", flush=True)

        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = str(exc)
            print(f"[error] {idx}/{total} {slug}: {exc}", flush=True)

        return entry

    def _finish(
        self, total: int, candidates: list, action_log: list,
        reimported: int, failed: int, skipped: int,
    ) -> dict[str, Any]:
        mode = "apply" if not self.dry_run else "audit"
        report: dict[str, Any] = {
            "summary": {
                "total_recipes": total,
                "candidates": len(candidates),
                "reimported": reimported,
                "failed": failed,
                "skipped": skipped,
                "mode": mode,
            },
            "actions": action_log,
        }

        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        self.report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        print(
            f"[done] {len(candidates)} candidate(s) — {reimported} reimported, "
            f"{failed} failed, {skipped} skipped ({mode} mode)",
            flush=True,
        )
        print("[summary] " + json.dumps({
            "__title__": "Re-importer",
            "Total Recipes": total,
            "Candidates": len(candidates),
            "Reimported": reimported,
            "Failed": failed,
            "Skipped": skipped,
            "Mode": mode,
        }), flush=True)
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Re-import recipes from their original source URLs.")
    parser.add_argument("--apply", action="store_true", help="Apply reimports (default is dry-run).")
    parser.add_argument("--max", type=int, default=0, help="Max recipes to reimport (0 = all).")
    parser.add_argument("--slugs", type=str, default="", help="Comma-separated list of specific slugs.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    if dry_run:
        print("[start] runtime.dry_run=true (writes disabled; planning only).", flush=True)

    slugs_filter = [s.strip() for s in args.slugs.split(",") if s.strip()] if args.slugs else None

    reimporter = RecipeReimporter(
        MealieApiClient(
            base_url=resolve_mealie_url(),
            api_key=resolve_mealie_api_key(required=True),
            timeout_seconds=120,
            retries=3,
            backoff_seconds=0.4,
        ),
        dry_run=dry_run,
        max_recipes=args.max,
        slugs_filter=slugs_filter,
        report_file=resolve_repo_path(DEFAULT_REPORT),
    )
    reimporter.run()


if __name__ == "__main__":
    main()
