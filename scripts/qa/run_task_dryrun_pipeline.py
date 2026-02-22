#!/usr/bin/env python3
"""Dry-run task execution pipeline.

Runs every registered task (and key mode variants) against the live Mealie
instance with DRY_RUN=true and reports PASS / SKIP / FAIL per variant.

Variants include:
  - Default (API) mode for all tasks
  - DB mode (use_db=True) for tasks that support it — skipped if DB not configured
  - LLM categorize — skipped if no AI provider is configured

Usage:
    python scripts/qa/run_task_dryrun_pipeline.py [--tasks task1,task2,...] [--timeout 120]

Defaults:
    Runs all registered tasks plus DB-mode variants.  Pass --include-all to also
    run the categorize (LLM) task.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Ensure we can import from src/
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cookdex.webui_server.tasks import TaskRegistry  # noqa: E402
from cookdex.config import load_env_file, ENV_FILE  # noqa: E402
from cookdex.db_client import is_db_enabled  # noqa: E402

load_env_file(ENV_FILE)


# ---------------------------------------------------------------------------
# Variant definitions
# Each variant is a named test case: (task_id, label_suffix, options, skip_reason_fn)
# ---------------------------------------------------------------------------

@dataclass
class Variant:
    task_id: str
    label: str          # display label, e.g. "rule-tag (api)" or "rule-tag (db)"
    options: dict
    skip_reason: Optional[str] = None  # non-None → skip with this message


def _db_skip() -> Optional[str]:
    if not is_db_enabled():
        return "no DB configured (set MEALIE_DB_TYPE in .env)"
    return None


def _llm_skip() -> Optional[str]:
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("OLLAMA_BASE_URL"):
        return "no LLM configured (set OPENAI_API_KEY or OLLAMA_BASE_URL)"
    return None


def _build_variants() -> list[Variant]:
    """Build the full list of QA variants."""
    variants: list[Variant] = []

    # Tasks that are always safe and have no interesting mode splits
    simple_tasks = [
        "cookbook-sync",
        "foods-cleanup",
        "labels-sync",
        "taxonomy-audit",
        "taxonomy-refresh",
        "tools-sync",
        "units-cleanup",
    ]
    for tid in simple_tasks:
        variants.append(Variant(task_id=tid, label=tid, options={}))

    # ingredient-parse: limit to 5 recipes for speed
    variants.append(Variant(
        task_id="ingredient-parse",
        label="ingredient-parse",
        options={"max_recipes": 5},
    ))

    # data-maintenance: skip AI stage, limit stages
    variants.append(Variant(
        task_id="data-maintenance",
        label="data-maintenance",
        options={"stages": "taxonomy,cookbooks,yield,quality,audit", "skip_ai": True},
    ))

    # recipe-quality — API mode
    variants.append(Variant(
        task_id="recipe-quality",
        label="recipe-quality (api)",
        options={"nutrition_sample": 10},
    ))
    # recipe-quality — DB mode
    variants.append(Variant(
        task_id="recipe-quality",
        label="recipe-quality (db)",
        options={"nutrition_sample": 10, "use_db": True},
        skip_reason=_db_skip(),
    ))

    # yield-normalize — API mode
    variants.append(Variant(
        task_id="yield-normalize",
        label="yield-normalize (api)",
        options={},
    ))
    # yield-normalize — DB mode
    variants.append(Variant(
        task_id="yield-normalize",
        label="yield-normalize (db)",
        options={"use_db": True},
        skip_reason=_db_skip(),
    ))

    # rule-tag — API mode (text_tags only)
    variants.append(Variant(
        task_id="rule-tag",
        label="rule-tag (api)",
        options={},
    ))
    # rule-tag — DB mode (ingredient + text + tool)
    variants.append(Variant(
        task_id="rule-tag",
        label="rule-tag (db)",
        options={"use_db": True},
        skip_reason=_db_skip(),
    ))

    # categorize — LLM mode (opt-in via --include-all)
    variants.append(Variant(
        task_id="categorize",
        label="categorize (llm)",
        options={},
        skip_reason="skipped by default — pass --include-all to enable",
    ))

    return variants


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DRY_RUN"] = "true"
    return env


def run_variant(
    variant: Variant,
    registry: TaskRegistry,
    *,
    timeout: int,
) -> tuple[str, float, str]:
    """Returns (status, elapsed_seconds, output_snippet).  Status: PASS | FAIL | SKIP."""
    if variant.skip_reason:
        return "SKIP", 0.0, variant.skip_reason

    options = {**variant.options, "dry_run": True}

    try:
        execution = registry.build_execution(variant.task_id, options)
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
        help="Comma-separated task IDs to run (filters variants by task_id).",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include opt-in tasks like categorize (LLM).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Per-task timeout in seconds (default 120).",
    )
    args = parser.parse_args()

    registry = TaskRegistry()
    all_variants = _build_variants()

    if args.tasks:
        wanted = {t.strip() for t in args.tasks.split(",") if t.strip()}
        variants = [v for v in all_variants if v.task_id in wanted]
    elif args.include_all:
        # Reveal the categorize variant (clear its default skip)
        variants = []
        for v in all_variants:
            if v.task_id == "categorize" and v.skip_reason and "pass --include-all" in v.skip_reason:
                variants.append(Variant(
                    task_id=v.task_id,
                    label=v.label,
                    options=v.options,
                    skip_reason=_llm_skip(),
                ))
            else:
                variants.append(v)
    else:
        variants = all_variants

    col_w = max(len(v.label) for v in variants) + 2
    header = f"{'VARIANT':<{col_w}}  {'STATUS':<6}  {'TIME':>7}  DETAILS"
    print("\n" + "=" * (len(header) + 4))
    print(f"  CookDex Dry-Run Pipeline  ({len(variants)} variants)")
    print("=" * (len(header) + 4))
    print(f"  {header}")
    print("-" * (len(header) + 4))

    passed = failed = skipped = 0

    for variant in variants:
        print(f"  {variant.label:<{col_w}}  {'...':<6}", end="\r", flush=True)
        status, elapsed, snippet = run_variant(variant, registry, timeout=args.timeout)

        if status == "PASS":
            passed += 1
            display = "\033[32mPASS\033[0m"
        elif status == "SKIP":
            skipped += 1
            display = "\033[33mSKIP\033[0m"
        else:
            failed += 1
            display = "\033[31mFAIL\033[0m"

        time_str = f"{elapsed:>6.1f}s" if elapsed > 0 else "      -"
        print(f"  {variant.label:<{col_w}}  {display:<6}  {time_str}  {snippet[:80]}")

    print("-" * (len(header) + 4))
    total = len(variants)
    overall = "\033[32mOK\033[0m" if failed == 0 else "\033[31mFAILED\033[0m"
    print(
        f"  Result: {overall}  "
        f"({passed} passed, {skipped} skipped, {failed} failed, {total} total)\n"
    )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
