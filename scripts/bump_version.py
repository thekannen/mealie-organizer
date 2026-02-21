#!/usr/bin/env python3
"""CalVer bump script — year.month.build

Reads VERSION, increments the build number (resets if year/month changed),
writes back to VERSION and syncs web/package.json.

Usage:
    python scripts/bump_version.py              # auto-bump build
    python scripts/bump_version.py --dry-run    # preview without writing
    python scripts/bump_version.py --set 2026.3.1  # force a specific version
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"
PACKAGE_JSON = REPO_ROOT / "web" / "package.json"

CALVER_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d+)$")


def read_current() -> tuple[int, int, int]:
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    m = CALVER_RE.match(raw)
    if not m:
        print(f"[error] VERSION must be year.month.build — found: {raw}", file=sys.stderr)
        sys.exit(1)
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def next_version(cur_year: int, cur_month: int, cur_build: int) -> str:
    now = datetime.now()
    if now.year == cur_year and now.month == cur_month:
        return f"{cur_year}.{cur_month}.{cur_build + 1}"
    return f"{now.year}.{now.month}.1"


def write_version(version: str) -> None:
    VERSION_FILE.write_text(version + "\n", encoding="utf-8")


def sync_package_json(version: str) -> None:
    if not PACKAGE_JSON.exists():
        return
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    data["version"] = version
    PACKAGE_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="CalVer version bump (year.month.build)")
    parser.add_argument("--dry-run", action="store_true", help="Print new version without writing")
    parser.add_argument("--set", dest="force", metavar="X.Y.Z", help="Force a specific version")
    args = parser.parse_args()

    cur_year, cur_month, cur_build = read_current()
    current = f"{cur_year}.{cur_month}.{cur_build}"

    if args.force:
        if not CALVER_RE.match(args.force):
            print(f"[error] --set must be year.month.build — got: {args.force}", file=sys.stderr)
            sys.exit(1)
        new = args.force
    else:
        new = next_version(cur_year, cur_month, cur_build)

    if args.dry_run:
        print(f"{current} -> {new} (dry run)")
        return

    write_version(new)
    sync_package_json(new)
    print(f"[ok] {current} -> {new}")


if __name__ == "__main__":
    main()
