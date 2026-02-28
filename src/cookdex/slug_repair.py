"""Repair recipe slug mismatches in Mealie's database.

When CookDex normalizes recipe names via PATCH without including the slug
field, Mealie keeps the old slug in the database while the Pydantic model
regenerates a different slug from the new name.  This breaks subsequent
PATCH calls (403 Permission Denied) because Mealie's ``can_update()``
permission check queries by the regenerated slug, which no longer matches
any row.

This module detects the mismatches and fixes them.

Usage
-----
    # Scan via API, print SQL fixes (no DB credentials needed)
    python -m cookdex.slug_repair

    # Scan and apply fixes directly via DB
    python -m cookdex.slug_repair --use-db --apply
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from slugify import slugify

from .api_client import MealieApiClient
from .config import resolve_mealie_api_key, resolve_mealie_url


def _make_slug(name: str) -> str:
    """Generate a slug matching Mealie's create_recipe_slug()."""
    s = slugify(name)
    if len(s) > 250:
        s = s[:250]
    return s


def _safe_print(text: str) -> None:
    """Print text safely on Windows terminals that choke on Unicode."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode(), flush=True)


def scan_mismatches(client: MealieApiClient) -> tuple[int, list[dict[str, Any]]]:
    """Fetch all recipes and return (total_count, mismatches)."""
    _safe_print("[info] Fetching all recipes from Mealie...")
    recipes = client.get_recipes()
    total = len(recipes)
    _safe_print(f"[info] Scanning {total} recipes for slug mismatches...")

    mismatches: list[dict[str, Any]] = []
    for r in recipes:
        name = str(r.get("name") or "").strip()
        db_slug = str(r.get("slug") or "").strip()
        recipe_id = str(r.get("id") or "").strip()
        if not name or not db_slug:
            continue

        expected_slug = _make_slug(name)
        if expected_slug and expected_slug != db_slug:
            mismatches.append({
                "id": recipe_id,
                "name": name,
                "db_slug": db_slug,
                "expected_slug": expected_slug,
            })

    return total, mismatches


def apply_db_fixes(mismatches: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Apply slug fixes directly via DB connection, emitting progress.

    Returns (applied, skipped, failed).  Uses SAVEPOINTs so one failure
    does not abort the entire transaction.
    """
    from .db_client import MealieDBClient

    applied = 0
    skipped = 0
    failed = 0
    total = len(mismatches)

    with MealieDBClient() as db:
        p = db._db.placeholder
        is_pg = db._db._type == "postgres"

        # Build a set of existing slugs so we can skip collisions upfront.
        db._db.execute("SELECT slug FROM recipes")
        existing_slugs = {row[0] for row in db._db.fetchall()}

        for idx, m in enumerate(mismatches, 1):
            expected = m["expected_slug"]
            # Skip if the target slug already belongs to a different recipe.
            if expected in existing_slugs and expected != m["db_slug"]:
                skipped += 1
                _safe_print(
                    f"[skip] {idx}/{total} {expected} "
                    f"already exists (collision with another recipe)"
                )
                continue

            t0 = time.monotonic()
            try:
                if is_pg:
                    db._db.execute("SAVEPOINT slug_fix")
                db._db.execute(
                    f"UPDATE recipes SET slug = {p} WHERE id = {p}",
                    (expected, m["id"]),
                )
                if is_pg:
                    db._db.execute("RELEASE SAVEPOINT slug_fix")
                # Update the lookup set so subsequent iterations see the change.
                existing_slugs.discard(m["db_slug"])
                existing_slugs.add(expected)
                applied += 1
                elapsed = time.monotonic() - t0
                _safe_print(
                    f"[ok] {idx}/{total} {expected} "
                    f"was={m['db_slug']} duration={elapsed:.2f}s"
                )
            except Exception as exc:
                if is_pg:
                    db._db.execute("ROLLBACK TO SAVEPOINT slug_fix")
                failed += 1
                _safe_print(f"[error] {m['db_slug']}: {exc}")

    return applied, skipped, failed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Detect and repair recipe slug mismatches in Mealie's database.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply fixes (requires --use-db). Without this flag, only scans and prints SQL.",
    )
    parser.add_argument(
        "--use-db", action="store_true",
        help="Connect directly to Mealie's database to apply fixes.",
    )
    args = parser.parse_args(argv)

    dry_run = not args.apply

    _safe_print(
        f"[start] Slug Repair -- dry_run={dry_run}"
        + (f" use_db={args.use_db}" if args.use_db else "")
    )

    mealie_url = resolve_mealie_url()
    api_key = resolve_mealie_api_key()
    if not mealie_url or not api_key:
        _safe_print("[error] MEALIE_URL and MEALIE_API_KEY must be set.")
        sys.exit(1)

    client = MealieApiClient(mealie_url, api_key, timeout_seconds=60, retries=3, backoff_seconds=0.4)
    total_recipes, mismatches = scan_mismatches(client)

    if not mismatches:
        _safe_print("[ok] 1/1 all-clean duration=0.00s")
        _safe_print("[summary] " + json.dumps({
            "__title__": "Slug Repair",
            "Recipes Scanned": total_recipes,
            "Mismatches": 0,
        }))
        return

    _safe_print(f"[info] Found {len(mismatches)} slug mismatches out of {total_recipes} recipes")

    if args.apply and args.use_db:
        _safe_print(f"[info] Applying {len(mismatches)} fixes via direct database...")
        try:
            applied, skipped, failed = apply_db_fixes(mismatches)
        except Exception as exc:
            _safe_print(f"[error] Database connection failed: {exc}")
            _safe_print("[summary] " + json.dumps({
                "__title__": "Slug Repair",
                "Recipes Scanned": total_recipes,
                "Mismatches": len(mismatches),
                "Status": "Database connection failed",
            }))
            sys.exit(1)
        summary: dict[str, Any] = {
            "__title__": "Slug Repair",
            "Recipes Scanned": total_recipes,
            "Mismatches": len(mismatches),
            "Applied": applied,
        }
        if skipped:
            summary["Skipped (collision)"] = skipped
        if failed:
            summary["Failed"] = failed
        _safe_print("[summary] " + json.dumps(summary))
    elif args.apply and not args.use_db:
        _safe_print("[error] --apply requires --use-db (Mealie's API cannot update these recipes).")
        _safe_print("[info] Enable 'Use Direct DB' in advanced options, or run SQL manually.")
        _safe_print("[summary] " + json.dumps({
            "__title__": "Slug Repair",
            "Recipes Scanned": total_recipes,
            "Mismatches": len(mismatches),
            "Status": "Cannot apply — use-db not enabled",
        }))
    else:
        # Dry run: report each mismatch as an [ok] event for progress tracking
        for idx, m in enumerate(mismatches, 1):
            _safe_print(
                f"[ok] {idx}/{len(mismatches)} {m['expected_slug']} "
                f"was={m['db_slug']} duration=0.00s"
            )
        _safe_print("[summary] " + json.dumps({
            "__title__": "Slug Repair",
            "Recipes Scanned": total_recipes,
            "Mismatches": len(mismatches),
            "Mode": "Scan only (dry run)",
        }))


if __name__ == "__main__":
    main()
