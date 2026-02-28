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
import sys
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


def scan_mismatches(client: MealieApiClient) -> list[dict[str, Any]]:
    """Fetch all recipes and return those whose slug doesn't match their name."""
    _safe_print("[scan] Fetching all recipes ...")
    recipes = client.get_recipes()
    _safe_print(f"[scan] Checking {len(recipes)} recipes for slug mismatches ...")

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

    return mismatches


def print_sql(mismatches: list[dict[str, Any]]) -> None:
    """Print SQL UPDATE statements to fix mismatched slugs."""
    if not mismatches:
        _safe_print("[ok] No slug mismatches found.")
        return

    _safe_print(f"\n-- {len(mismatches)} recipes have slug mismatches.")
    _safe_print("-- Run these SQL statements against your Mealie database:\n")
    _safe_print("BEGIN;")
    for m in mismatches:
        safe_id = m["id"].replace("'", "''")
        safe_slug = m["expected_slug"].replace("'", "''")
        _safe_print(f"UPDATE recipes SET slug = '{safe_slug}' WHERE id = '{safe_id}';")
    _safe_print("COMMIT;")
    _safe_print(f"\n-- Total: {len(mismatches)} updates")


def apply_db_fixes(mismatches: list[dict[str, Any]]) -> tuple[int, int]:
    """Apply slug fixes directly via DB connection."""
    from .db_client import MealieDBClient

    applied = 0
    failed = 0

    with MealieDBClient() as db:
        p = db._db.placeholder
        for m in mismatches:
            try:
                db._db.execute(
                    f"UPDATE recipes SET slug = {p} WHERE id = {p}",
                    (m["expected_slug"], m["id"]),
                )
                applied += 1
                _safe_print(f"[fix] {m['db_slug']} -> {m['expected_slug']}")
            except Exception as exc:
                failed += 1
                _safe_print(f"[error] {m['db_slug']}: {exc}")

    return applied, failed


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

    mealie_url = resolve_mealie_url()
    api_key = resolve_mealie_api_key()
    if not mealie_url or not api_key:
        print("[error] MEALIE_URL and MEALIE_API_KEY must be set.", file=sys.stderr, flush=True)
        sys.exit(1)

    client = MealieApiClient(mealie_url, api_key, timeout_seconds=60, retries=3, backoff_seconds=0.4)
    mismatches = scan_mismatches(client)

    if not mismatches:
        _safe_print("[ok] No slug mismatches found. All recipes are clean.")
        return

    _safe_print(f"\n[result] Found {len(mismatches)} slug mismatches:")
    for m in mismatches:
        _safe_print(f"  {m['db_slug']} -> {m['expected_slug']}  ({m['name']})")

    if args.apply and args.use_db:
        _safe_print(f"\n[fix] Applying {len(mismatches)} slug fixes via direct DB ...")
        applied, failed = apply_db_fixes(mismatches)
        _safe_print(f"\n[done] Applied: {applied}, Failed: {failed}")
    elif args.apply and not args.use_db:
        _safe_print("\n[error] --apply requires --use-db (Mealie's API rejects PATCH on these recipes).")
        _safe_print("  Configure MEALIE_DB_TYPE and connection vars in .env, then re-run.")
        _safe_print("  Or copy the SQL below and run it manually:\n")
        print_sql(mismatches)
    else:
        print_sql(mismatches)


if __name__ == "__main__":
    main()
