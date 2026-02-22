"""Recipe Source URL Deduplicator.

Finds recipes in Mealie that share the same canonical source URL and keeps
only the best one, deleting the duplicates.

Canonical URL normalization:
  - Lowercase scheme and host, strip "www."
  - Normalize path (collapse // slashes, strip trailing /)
  - Remove common tracking query parameters (utm_*, fbclid, gclid, ref, etc.)
  - Sort remaining query parameters alphabetically

"Best" recipe selection (when multiple share a URL):
  - Prefer the one whose name does NOT end with a numeric suffix like "(2)"
  - Among ties, prefer the longest (most-complete) name
  - Among ties, prefer the longest slug (usually more descriptive)

Write mode: DELETE calls via Mealie HTTP API.
Use DRY_RUN=true (the default) to preview without deleting.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api_client import MealieApiClient
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url, resolve_repo_path, to_bool

DEFAULT_REPORT = "reports/recipe_dedup_report.json"

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "igshid", "mc_cid", "mc_eid",
    "ref", "ref_src", "ref_url", "s", "spm",
})

_NUMERIC_SUFFIX_RE = re.compile(r"\s*\(\d+\)$")

_SOURCE_FIELDS = ("orgURL", "originalURL", "source")


def canonicalize_url(url: str) -> str:
    """Return a normalized URL suitable for duplicate comparison."""
    url = url.strip()
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        scheme = (parsed.scheme or "https").lower()
        host = (parsed.netloc or "").lower()
        host = host.lstrip("www.")
        path = re.sub(r"/+", "/", parsed.path or "/")
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        params = {
            k: v
            for k, v in urllib.parse.parse_qsl(parsed.query)
            if k.lower() not in _TRACKING_PARAMS
        }
        query = urllib.parse.urlencode(sorted(params.items()))
        return urllib.parse.urlunparse((scheme, host, path, "", query, ""))
    except Exception:
        return url.lower()


def _extract_source(recipe: dict[str, Any]) -> str:
    for field in _SOURCE_FIELDS:
        val = recipe.get(field)
        if val and str(val).strip():
            return str(val).strip()
    return ""


def _has_numeric_suffix(name: str) -> bool:
    return bool(_NUMERIC_SUFFIX_RE.search(name))


def _recipe_score(recipe: dict[str, Any]) -> tuple[int, int, int]:
    """Higher is better. Used to pick the keeper from a duplicate group."""
    name = str(recipe.get("name") or "")
    slug = str(recipe.get("slug") or "")
    has_suffix = _has_numeric_suffix(name)
    return (0 if has_suffix else 1, len(name), len(slug))


@dataclass
class DedupGroup:
    canonical_url: str
    keeper: dict[str, Any]
    duplicates: list[dict[str, Any]]


def _group_duplicates(recipes: list[dict[str, Any]]) -> list[DedupGroup]:
    by_url: dict[str, list[dict[str, Any]]] = {}
    for recipe in recipes:
        src = _extract_source(recipe)
        if not src:
            continue
        canon = canonicalize_url(src)
        if not canon:
            continue
        by_url.setdefault(canon, []).append(recipe)

    groups: list[DedupGroup] = []
    for canon_url, group in by_url.items():
        if len(group) < 2:
            continue
        sorted_group = sorted(group, key=_recipe_score, reverse=True)
        groups.append(DedupGroup(
            canonical_url=canon_url,
            keeper=sorted_group[0],
            duplicates=sorted_group[1:],
        ))
    return groups


class RecipeDeduplicator:
    def __init__(
        self,
        client: MealieApiClient,
        *,
        dry_run: bool = True,
        apply: bool = False,
        report_file: Path | str = DEFAULT_REPORT,
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.apply = apply
        self.report_file = Path(report_file)

    def run(self) -> dict[str, Any]:
        executable = self.apply and not self.dry_run

        print("[start] Fetching all recipes from API ...", flush=True)
        recipes = self.client.get_recipes()
        total = len(recipes)

        groups = _group_duplicates(recipes)
        total_dupes = sum(len(g.duplicates) for g in groups)
        print(
            f"[start] {total} recipes scanned → {len(groups)} duplicate groups, "
            f"{total_dupes} recipes to remove",
            flush=True,
        )

        action_log: list[dict] = []
        deleted = 0
        failed = 0
        action_idx = 0

        for group in groups:
            keeper_slug = str(group.keeper.get("slug") or "")
            keeper_name = str(group.keeper.get("name") or "")
            for dupe in group.duplicates:
                dupe_slug = str(dupe.get("slug") or "")
                dupe_name = str(dupe.get("name") or "")
                action_idx += 1
                entry: dict[str, Any] = {
                    "canonical_url": group.canonical_url,
                    "keeper_slug": keeper_slug,
                    "keeper_name": keeper_name,
                    "removed_slug": dupe_slug,
                    "removed_name": dupe_name,
                }
                if executable:
                    try:
                        self.client.delete_recipe(dupe_slug)
                        entry["status"] = "deleted"
                        deleted += 1
                        print(f"[ok] {action_idx}/{total_dupes} {dupe_slug} kept={keeper_slug}", flush=True)
                    except Exception as exc:
                        entry["status"] = "error"
                        entry["error"] = str(exc)
                        failed += 1
                        print(f"[error] {dupe_slug}: {exc}", flush=True)
                else:
                    entry["status"] = "planned"
                    print(f"[plan] {dupe_slug}: would delete '{dupe_name}', keeping '{keeper_name}'", flush=True)
                action_log.append(entry)

        report: dict[str, Any] = {
            "summary": {
                "total_recipes": total,
                "duplicate_groups": len(groups),
                "duplicates_found": total_dupes,
                "deleted": deleted,
                "failed": failed,
                "mode": "apply" if executable else "audit",
            },
            "actions": action_log,
        }

        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        self.report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[done] Dedup report written to {self.report_file}", flush=True)
        print(
            f'[summary] {{"total": {total}, "groups": {len(groups)}, '
            f'"duplicates": {total_dupes}, "deleted": {deleted}, "failed": {failed}, '
            f'"mode": "{"apply" if executable else "audit"}"}}',
            flush=True,
        )
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deduplicate recipes by canonical source URL.")
    parser.add_argument("--apply", action="store_true", help="Delete duplicate recipes from Mealie.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    if dry_run:
        print("[start] runtime.dry_run=true (writes disabled; planning only).", flush=True)
    deduplicator = RecipeDeduplicator(
        MealieApiClient(
            base_url=resolve_mealie_url(),
            api_key=resolve_mealie_api_key(required=True),
            timeout_seconds=60,
            retries=3,
            backoff_seconds=0.4,
        ),
        dry_run=dry_run,
        apply=bool(args.apply),
        report_file=resolve_repo_path(DEFAULT_REPORT),
    )
    deduplicator.run()


if __name__ == "__main__":
    main()
