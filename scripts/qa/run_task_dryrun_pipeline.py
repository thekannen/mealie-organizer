#!/usr/bin/env python3
"""Dry-run task execution pipeline.

Runs every registered task (and key mode variants) against the live Mealie
instance with DRY_RUN=true and reports PASS / SKIP / FAIL per variant.

Variants include:
  - Default (API) mode for all tasks
  - DB mode variants — skipped if MEALIE_DB_TYPE is not configured
  - LLM categorize (tag-categorize/ai) — skipped unless --include-all + LLM configured

Usage:
    python scripts/qa/run_task_dryrun_pipeline.py [--tasks task1,task2,...] [--timeout 120]

Defaults:
    Runs all registered tasks plus DB-mode variants.  Pass --include-all to also
    run the AI categorization variant.
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
# ---------------------------------------------------------------------------

@dataclass
class Variant:
    task_id: str
    label: str          # display label, e.g. "health-check (quality/db)"
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
    """Build the full list of QA variants covering all task IDs and option paths."""
    variants: list[Variant] = []

    # ── data-maintenance ────────────────────────────────────────────────────
    # Quick subset: audit stages only (no writes needed)
    variants.append(Variant(
        task_id="data-maintenance",
        label="data-maintenance (quality+audit)",
        options={"stages": "quality,audit", "skip_ai": True},
    ))
    # Multi-stage subset: fast stages covering different sub-modules
    variants.append(Variant(
        task_id="data-maintenance",
        label="data-maintenance (multi-stage)",
        options={"stages": "dedup,names,yield,quality,audit", "skip_ai": True},
    ))
    # continue_on_error path
    variants.append(Variant(
        task_id="data-maintenance",
        label="data-maintenance (continue-on-error)",
        options={"stages": "quality,audit", "skip_ai": True, "continue_on_error": True},
    ))

    # ── clean-recipes ────────────────────────────────────────────────────────
    # All three ops together (routes through data_maintenance)
    variants.append(Variant(
        task_id="clean-recipes",
        label="clean-recipes (all-ops)",
        options={"run_dedup": True, "run_junk": True, "run_names": True},
    ))
    # Dedup only (calls recipe_deduplicator directly)
    variants.append(Variant(
        task_id="clean-recipes",
        label="clean-recipes (dedup-only)",
        options={"run_dedup": True, "run_junk": False, "run_names": False},
    ))
    # Junk filter only — keyword-based reasons (how_to, listicle, digest, keyword, utility)
    variants.append(Variant(
        task_id="clean-recipes",
        label="clean-recipes (junk/keyword)",
        options={"run_dedup": False, "run_junk": True, "run_names": False, "reason": "keyword"},
    ))
    # Name normalizer only with force_all
    variants.append(Variant(
        task_id="clean-recipes",
        label="clean-recipes (names/force-all)",
        options={"run_dedup": False, "run_junk": False, "run_names": True, "force_all": True},
    ))

    # ── ingredient-parse ─────────────────────────────────────────────────────
    variants.append(Variant(
        task_id="ingredient-parse",
        label="ingredient-parse (max=5)",
        options={"max_recipes": 5},
    ))
    # Higher confidence threshold
    variants.append(Variant(
        task_id="ingredient-parse",
        label="ingredient-parse (conf=90, max=5)",
        options={"max_recipes": 5, "confidence_threshold": 90},
    ))

    # ── yield-normalize ──────────────────────────────────────────────────────
    variants.append(Variant(
        task_id="yield-normalize",
        label="yield-normalize (api)",
        options={},
    ))
    variants.append(Variant(
        task_id="yield-normalize",
        label="yield-normalize (db)",
        options={"use_db": True},
        skip_reason=_db_skip(),
    ))

    # ── cleanup-duplicates ────────────────────────────────────────────────────
    variants.append(Variant(
        task_id="cleanup-duplicates",
        label="cleanup-duplicates (both)",
        options={"target": "both"},
    ))
    variants.append(Variant(
        task_id="cleanup-duplicates",
        label="cleanup-duplicates (foods)",
        options={"target": "foods"},
    ))
    variants.append(Variant(
        task_id="cleanup-duplicates",
        label="cleanup-duplicates (units)",
        options={"target": "units"},
    ))

    # ── tag-categorize ────────────────────────────────────────────────────────
    # Rule-based via API
    variants.append(Variant(
        task_id="tag-categorize",
        label="tag-categorize (rules/api)",
        options={"method": "rules"},
    ))
    # Rule-based via DB
    variants.append(Variant(
        task_id="tag-categorize",
        label="tag-categorize (rules/db)",
        options={"method": "rules", "use_db": True},
        skip_reason=_db_skip(),
    ))
    # AI categorization — opt-in only
    variants.append(Variant(
        task_id="tag-categorize",
        label="tag-categorize (ai)",
        options={"method": "ai"},
        skip_reason="skipped by default — pass --include-all to enable",
    ))

    # ── taxonomy-refresh ──────────────────────────────────────────────────────
    # Default: sync labels + tools via data_maintenance
    variants.append(Variant(
        task_id="taxonomy-refresh",
        label="taxonomy-refresh (labels+tools)",
        options={"sync_labels": True, "sync_tools": True},
    ))
    # Labels only
    variants.append(Variant(
        task_id="taxonomy-refresh",
        label="taxonomy-refresh (labels-only)",
        options={"sync_labels": True, "sync_tools": False},
    ))
    # Tools only
    variants.append(Variant(
        task_id="taxonomy-refresh",
        label="taxonomy-refresh (tools-only)",
        options={"sync_labels": False, "sync_tools": True},
    ))
    # Direct taxonomy_manager call with replace mode (no labels/tools)
    variants.append(Variant(
        task_id="taxonomy-refresh",
        label="taxonomy-refresh (direct/replace)",
        options={"sync_labels": False, "sync_tools": False, "mode": "replace"},
    ))

    # ── cookbook-sync ─────────────────────────────────────────────────────────
    variants.append(Variant(
        task_id="cookbook-sync",
        label="cookbook-sync",
        options={},
    ))

    # ── health-check ──────────────────────────────────────────────────────────
    # Both scopes, small nutrition sample for speed
    variants.append(Variant(
        task_id="health-check",
        label="health-check (both, sample=10)",
        options={"scope_quality": True, "scope_taxonomy": True, "nutrition_sample": 10},
    ))
    # Quality audit only via API
    variants.append(Variant(
        task_id="health-check",
        label="health-check (quality/api, sample=10)",
        options={"scope_quality": True, "scope_taxonomy": False, "nutrition_sample": 10},
    ))
    # Quality audit via DB (exact nutrition, no sampling)
    variants.append(Variant(
        task_id="health-check",
        label="health-check (quality/db)",
        options={"scope_quality": True, "scope_taxonomy": False, "use_db": True},
        skip_reason=_db_skip(),
    ))
    # Taxonomy audit only
    variants.append(Variant(
        task_id="health-check",
        label="health-check (taxonomy-only)",
        options={"scope_quality": False, "scope_taxonomy": True},
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
        help="Include opt-in tasks like tag-categorize (AI).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Per-task timeout in seconds (default 180).",
    )
    args = parser.parse_args()

    registry = TaskRegistry()
    all_variants = _build_variants()

    if args.tasks:
        wanted = {t.strip() for t in args.tasks.split(",") if t.strip()}
        variants = [v for v in all_variants if v.task_id in wanted]
    elif args.include_all:
        # Reveal the AI categorization variant
        variants = []
        for v in all_variants:
            if v.task_id == "tag-categorize" and v.options.get("method") == "ai" and v.skip_reason and "pass --include-all" in v.skip_reason:
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
