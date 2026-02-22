#!/usr/bin/env python3
"""Dry-run task execution pipeline.

Runs every registered task against the live Mealie instance with DRY_RUN=true
and reports PASS / SKIP / FAIL per task.

Usage:
    python scripts/qa/run_task_dryrun_pipeline.py [--tasks task1,task2,...] [--timeout 120]

Defaults:
    Runs all tasks except `categorize` and `data-maintenance` (which orchestrates
    the others and would duplicate work).  Pass --include-all to run everything.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure we can import from src/
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cookdex.webui_server.tasks import TaskRegistry  # noqa: E402

# Load .env so MEALIE_URL etc. are available when subprocesses start.
from cookdex.config import load_env_file, ENV_FILE  # noqa: E402
load_env_file(ENV_FILE)

# ---------------------------------------------------------------------------
# Task-specific dry-run options (all safe; no apply/write flags)
# ---------------------------------------------------------------------------

TASK_OPTIONS: dict[str, dict] = {
    "ingredient-parse": {"max_recipes": 5},   # limit to 5 recipes – fast verification
    "recipe-quality":   {"nutrition_sample": 10},  # small sample for speed
    "data-maintenance": {"stages": "taxonomy,cookbooks,yield,quality,audit", "skip_ai": True},
}

# Tasks skipped by default (they either call AI or are covered by data-maintenance)
DEFAULT_SKIP = {"categorize"}


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DRY_RUN"] = "true"
    return env


def run_task(
    task_id: str,
    registry: TaskRegistry,
    *,
    timeout: int,
) -> tuple[str, float, str]:
    """Returns (status, elapsed_seconds, output_snippet)."""
    options = TASK_OPTIONS.get(task_id, {})
    options = {**options, "dry_run": True}

    try:
        execution = registry.build_execution(task_id, options)
    except Exception as exc:
        return "FAIL", 0.0, f"build error: {exc}"

    env = _build_env()
    env.update(execution.env)

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            execution.command,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "FAIL", time.monotonic() - t0, f"timed out after {timeout}s"
    except Exception as exc:
        return "FAIL", time.monotonic() - t0, str(exc)

    elapsed = time.monotonic() - t0
    combined = (result.stdout + result.stderr).strip()
    # Last 3 non-empty lines are usually the most informative
    snippet_lines = [ln for ln in combined.splitlines() if ln.strip()][-3:]
    snippet = " | ".join(snippet_lines)

    if result.returncode == 0:
        return "PASS", elapsed, snippet
    return "FAIL", elapsed, snippet


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run all registered tasks against live Mealie.")
    parser.add_argument(
        "--tasks",
        default="",
        help="Comma-separated task IDs to run. Defaults to all non-skipped tasks.",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include tasks in DEFAULT_SKIP (categorize, data-maintenance).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Per-task timeout in seconds (default 120).",
    )
    args = parser.parse_args()

    registry = TaskRegistry()
    all_ids = sorted(registry.task_ids)

    if args.tasks:
        task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
    else:
        task_ids = [t for t in all_ids if args.include_all or t not in DEFAULT_SKIP]

    col_w = max(len(t) for t in task_ids) + 2
    header = f"{'TASK':<{col_w}}  {'STATUS':<6}  {'TIME':>7}  DETAILS"
    print("\n" + "=" * (len(header) + 4))
    print(f"  CookDex Dry-Run Pipeline  ({len(task_ids)} tasks)")
    print("=" * (len(header) + 4))
    print(f"  {header}")
    print("-" * (len(header) + 4))

    results: list[tuple[str, str, float, str]] = []
    passed = 0
    failed = 0

    for task_id in task_ids:
        print(f"  {task_id:<{col_w}}  {'...':<6}", end="\r", flush=True)
        status, elapsed, snippet = run_task(task_id, registry, timeout=args.timeout)
        if status == "PASS":
            passed += 1
        else:
            failed += 1
        results.append((task_id, status, elapsed, snippet))
        status_display = status if status != "PASS" else "\033[32mPASS\033[0m"
        fail_display   = status if status == "PASS"  else "\033[31mFAIL\033[0m"
        display = status_display if status == "PASS" else fail_display
        print(f"  {task_id:<{col_w}}  {display:<6}  {elapsed:>6.1f}s  {snippet[:80]}")

    print("-" * (len(header) + 4))
    total = len(task_ids)
    overall = "\033[32mOK\033[0m" if failed == 0 else "\033[31mFAILED\033[0m"
    print(f"  Result: {overall}  ({passed}/{total} passed, {failed} failed)\n")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
