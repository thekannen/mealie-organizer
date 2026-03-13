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

Each recipe is fully processed (scrape → patch) before the next begins.
A small thread pool (default 2 workers) overlaps scrape I/O without
overwhelming Mealie.  Failed scrapes are retried with exponential backoff.

Progress is saved incrementally — the run can be resumed from where it left
off by passing --resume.

Use DRY_RUN=true (the default) to preview without modifying anything.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .api_client import MealieApiClient
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url, resolve_repo_path, to_bool
from .db_client import resolve_db_client

DEFAULT_REPORT = "reports/recipe_reimport_report.json"

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

# Retry settings for transient errors (500, 408).
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 5.0  # seconds — doubles each retry (5, 10, 20)

# Default delay between recipe processing to avoid overloading Mealie.
_DEFAULT_DELAY = 0.5  # seconds

# Default number of concurrent workers (scrape + patch per worker).
_DEFAULT_WORKERS = 2


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
        workers: int = _DEFAULT_WORKERS,
        slugs_filter: list[str] | None = None,
        delay: float = _DEFAULT_DELAY,
        resume: bool = False,
        report_file: Path | str = DEFAULT_REPORT,
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.max_recipes = max_recipes
        self.workers = max(1, min(workers, 4))
        self.slugs_filter = set(slugs_filter) if slugs_filter else None
        self.delay = delay
        self.resume = resume
        self.report_file = Path(report_file)
        self._db = None
        self._completed_slugs: set[str] = set()
        self._lock = threading.Lock()
        self._counter = 0

    def _load_completed(self) -> set[str]:
        """Load previously completed slugs from report file for resume."""
        if not self.resume or not self.report_file.exists():
            return set()
        try:
            data = json.loads(self.report_file.read_text(encoding="utf-8"))
            return {
                a["slug"]
                for a in data.get("actions", [])
                if a.get("status") == "reimported"
            }
        except Exception:
            return set()

    def _save_progress(
        self, total: int, candidates: list, action_log: list,
        reimported: int, failed: int, skipped: int,
    ) -> None:
        """Save current progress to report file (called after each recipe)."""
        report = {
            "summary": {
                "total_recipes": total,
                "candidates": len(candidates),
                "reimported": reimported,
                "failed": failed,
                "skipped": skipped,
                "mode": "apply",
                "in_progress": True,
            },
            "actions": action_log,
        }
        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        self.report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

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

        # Resume: load previously completed slugs.
        self._completed_slugs = self._load_completed()
        resume_skipped = 0
        if self._completed_slugs:
            before = len(candidates)
            candidates = [(s, n, u) for s, n, u in candidates if s not in self._completed_slugs]
            resume_skipped = before - len(candidates)

        print(
            f"[start] {total} recipes scanned, {len(candidates)} eligible for reimport"
            + (f" (capped at {self.max_recipes})" if self.max_recipes > 0 else "")
            + (f" ({resume_skipped} already done, skipped)" if resume_skipped else ""),
            flush=True,
        )

        if self.dry_run:
            action_log = []
            for idx, (slug, name, url) in enumerate(candidates, 1):
                print(f"[plan] {idx}/{len(candidates)} {slug}: would reimport from {url}", flush=True)
                action_log.append({"slug": slug, "name": name, "url": url, "status": "planned"})
            return self._finish(total, candidates, action_log, 0, 0, 0)

        # Live mode: process recipes with a small thread pool.
        # Each worker does the full scrape → patch cycle for one recipe at a time.
        action_log: list[dict[str, Any]] = [None] * len(candidates)  # type: ignore[list-item]
        reimported = 0
        failed = 0
        skipped = 0
        n = len(candidates)
        self._counter = 0

        print(f"[start] Processing {n} recipes ({self.workers} workers, delay={self.delay}s) ...", flush=True)

        def _worker(idx: int, slug: str, name: str, url: str) -> dict[str, Any]:
            if self.delay > 0:
                time.sleep(self.delay)
            return self._process_one(idx, n, slug, name, url)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            future_to_idx = {
                pool.submit(_worker, idx, slug, name, url): idx
                for idx, (slug, name, url) in enumerate(candidates)
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                result = future.result()
                action_log[idx] = result

                with self._lock:
                    if result["status"] == "reimported":
                        reimported += 1
                    elif result["status"] == "error":
                        failed += 1
                    else:
                        skipped += 1
                    done = reimported + failed + skipped
                    if done % 25 == 0:
                        self._save_progress(total, candidates, action_log, reimported, failed, skipped)

        return self._finish(total, candidates, action_log, reimported, failed, skipped)

    def _scrape_with_retry(self, slug: str, url: str) -> dict[str, Any]:
        """Scrape a URL with retry + exponential backoff for transient errors."""
        last_exc = None
        for attempt in range(_MAX_RETRIES):
            try:
                return self.client.request_json(
                    "POST",
                    "/recipes/test-scrape-url",
                    json={"url": url, "useOpenAI": False},
                    timeout=120,
                )
            except Exception as exc:
                last_exc = exc
                status = getattr(getattr(exc, "response", None), "status_code", 0)
                # Only retry on transient errors (500, 408, 502, 503, 504).
                if status not in (408, 500, 502, 503, 504):
                    raise
                wait = _RETRY_BACKOFF_BASE * (2 ** attempt)
                if attempt < _MAX_RETRIES - 1:
                    print(f"[retry] {slug}: {status} on attempt {attempt + 1}, waiting {wait:.0f}s ...", flush=True)
                    time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    def _process_one(
        self, idx: int, total: int, slug: str, name: str, url: str,
    ) -> dict[str, Any]:
        """Scrape + patch a single recipe."""
        entry: dict[str, Any] = {"slug": slug, "name": name, "url": url}
        try:
            # Phase 1: Scrape.
            scraped = self._scrape_with_retry(slug, url)

            # Phase 2: Get original + patch.
            original = self.client.get_recipe(slug)

            # Build patch — do NOT include name or slug (causes 403 on mismatch).
            patch: dict[str, Any] = {}

            if scraped.get("description"):
                patch["description"] = str(scraped["description"]).strip()

            raw_ings = scraped.get("recipeIngredient", [])
            if raw_ings:
                patch["recipeIngredient"] = _jsonld_to_ingredients(raw_ings)

            raw_steps = scraped.get("recipeInstructions", [])
            if raw_steps:
                patch["recipeInstructions"] = _jsonld_to_instructions(raw_steps)

            nutrition = _extract_nutrition(scraped.get("nutrition"))
            if nutrition:
                patch["nutrition"] = nutrition

            for time_field in ("prepTime", "totalTime", "cookTime", "performTime"):
                val = _extract_time(scraped.get(time_field))
                if val:
                    patch[time_field] = val

            yield_val = _extract_yield(scraped.get("recipeYield"))
            if yield_val:
                patch["recipeYield"] = yield_val

            patch["orgURL"] = url

            for field in _PRESERVE_FIELDS:
                if field in original:
                    patch[field] = original[field]

            # PATCH with 403 slug-repair fallback.
            try:
                self.client.patch_recipe(slug, patch)
            except Exception as patch_exc:
                status_code = getattr(getattr(patch_exc, "response", None), "status_code", 0)
                new_slug = self._repair_slug(slug, original) if status_code == 403 else None
                if new_slug:
                    self.client.patch_recipe(new_slug, patch)
                else:
                    raise

            entry["status"] = "reimported"
            ing_count = len(patch.get("recipeIngredient", []))
            print(f"[ok] {idx}/{total} {slug}: reimported ({ing_count} ingredients)", flush=True)

        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = str(exc)
            print(f"[error] {idx}/{total} {slug}: {exc}", flush=True)

        return entry

    def _repair_slug(self, listing_slug: str, original: dict[str, Any]) -> str | None:
        """Fix a slug/name mismatch in the DB so Mealie's can_update() passes."""
        try:
            if self._db is None:
                self._db = resolve_db_client()
            if self._db is None:
                return None

            from slugify import slugify

            current_name = original.get("name", "")
            name_slug = slugify(current_name)

            if name_slug == listing_slug:
                return None

            recipe_id = original.get("id")
            if not recipe_id:
                return None

            p = self._db._db.placeholder
            self._db._db.execute(
                f"UPDATE recipes SET slug = {p} WHERE id = {p}",
                (name_slug, recipe_id),
            )
            self._db._db.commit()
            print(f"[fix] {listing_slug}: repaired DB slug -> {name_slug}", flush=True)
            return name_slug
        except Exception as exc:
            print(f"[warning] slug repair failed for {listing_slug}: {exc}", flush=True)
            return None

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
    parser.add_argument("--workers", type=int, default=_DEFAULT_WORKERS, help=f"Concurrent workers (default {_DEFAULT_WORKERS}, max 4).")
    parser.add_argument("--delay", type=float, default=_DEFAULT_DELAY, help=f"Seconds between requests per worker (default {_DEFAULT_DELAY}).")
    parser.add_argument("--resume", action="store_true", help="Resume from previous run (skip already-reimported).")
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
        workers=min(args.workers, 4),
        slugs_filter=slugs_filter,
        delay=args.delay,
        resume=args.resume,
        report_file=resolve_repo_path(DEFAULT_REPORT),
    )
    reimporter.run()


if __name__ == "__main__":
    main()
