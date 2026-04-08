"""Mealie Backup Manager.

Create and prune Mealie backups via the admin API.

Usage:
    python -m cookdex.mealie_backup                  # create a backup
    python -m cookdex.mealie_backup --prune 5        # create + keep only newest 5
    python -m cookdex.mealie_backup --prune-only 5   # prune without creating
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .api_client import MealieApiClient
from .config import resolve_mealie_api_key, resolve_mealie_url


def create_backup(client: MealieApiClient) -> bool:
    """Create a new Mealie backup. Returns True on success."""
    print("[start] Creating Mealie backup...", flush=True)
    try:
        data = client.request_json("POST", "/admin/backups", timeout=900)
        msg = data.get("message", "") if isinstance(data, dict) else str(data)
        print(f"[ok] Backup created: {msg}", flush=True)
        return True
    except Exception as exc:
        print(f"[error] Backup failed: {exc}", flush=True)
        return False


def list_backups(client: MealieApiClient) -> list[dict[str, Any]]:
    """List all existing backups, newest first."""
    data = client.request_json("GET", "/admin/backups", timeout=30)
    imports = data.get("imports", []) if isinstance(data, dict) else []
    # Sort by name descending (names are timestamped: mealie_YYYY.MM.DD.HH.MM.SS.zip)
    imports.sort(key=lambda b: b.get("name", ""), reverse=True)
    return imports


def prune_backups(client: MealieApiClient, keep: int) -> int:
    """Delete oldest backups, keeping the newest *keep*. Returns count deleted."""
    backups = list_backups(client)
    if len(backups) <= keep:
        print(f"[info] {len(backups)} backup(s) exist, keep={keep} — nothing to prune.", flush=True)
        return 0

    to_delete = backups[keep:]
    deleted = 0
    for backup in to_delete:
        name = backup.get("name", "")
        if not name:
            continue
        try:
            client.request_json("DELETE", f"/admin/backups/{name}", timeout=30)
            print(f"[ok] Deleted backup: {name}", flush=True)
            deleted += 1
        except Exception as exc:
            print(f"[warn] Failed to delete {name}: {exc}", flush=True)

    print(f"[done] Pruned {deleted} backup(s), {min(len(backups), keep)} remaining.", flush=True)
    return deleted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and prune Mealie backups via the admin API.")
    parser.add_argument(
        "--prune",
        type=int,
        metavar="N",
        help="After creating a backup, delete oldest backups keeping only the newest N.",
    )
    parser.add_argument(
        "--prune-only",
        type=int,
        metavar="N",
        help="Skip backup creation and only prune, keeping the newest N.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List existing backups and exit.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    client = MealieApiClient(
        base_url=resolve_mealie_url(),
        api_key=resolve_mealie_api_key(required=True),
        timeout_seconds=60,
        retries=0,
        backoff_seconds=0,
    )

    if args.list:
        backups = list_backups(client)
        if not backups:
            print("[info] No backups found.", flush=True)
        else:
            print(f"[info] {len(backups)} backup(s):", flush=True)
            for b in backups:
                print(f"  {b.get('name', '?')}  ({b.get('size', '?')})", flush=True)
        return 0

    if args.prune_only is not None:
        prune_backups(client, args.prune_only)
        summary = {"__title__": "Mealie Backup", "Created": 0, "Pruned to": args.prune_only}
        print("[summary] " + json.dumps(summary), flush=True)
        return 0

    ok = create_backup(client)
    if not ok:
        return 1

    pruned_to = None
    if args.prune is not None:
        prune_backups(client, args.prune)
        pruned_to = args.prune

    summary: dict[str, Any] = {"__title__": "Mealie Backup", "Created": 1}
    if pruned_to is not None:
        summary["Pruned to"] = pruned_to
    print("[summary] " + json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
