from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Sequence

from .config import env_or_config

VALID_STAGES = {
    "parse", "foods", "units", "labels", "tools",
    "taxonomy", "categorize", "cookbooks",
    "yield", "quality", "audit",
    "names", "dedup", "junk",
}
DEFAULT_STAGE_ORDER = [
    "dedup", "junk", "names",
    "parse", "foods", "units", "labels", "tools",
    "taxonomy", "categorize", "cookbooks", "yield", "quality", "audit",
]


@dataclass
class StageResult:
    stage: str
    command: list[str]
    exit_code: int
    elapsed_seconds: float = 0.0


def parse_stage_list(raw: str) -> list[str]:
    stages = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not stages:
        raise ValueError("Stage list cannot be empty.")
    unknown = [stage for stage in stages if stage not in VALID_STAGES]
    if unknown:
        raise ValueError(f"Unknown stage(s): {', '.join(unknown)}")
    return stages


def _categorizer_provider_active() -> bool:
    """Return True when a usable AI provider is configured."""
    provider = str(
        env_or_config("CATEGORIZER_PROVIDER", "categorizer.provider", "")
    ).strip().lower()
    return bool(provider) and provider not in {"none", "off", "false", "0", "disabled"}


def stage_command(
    stage: str,
    *,
    apply_cleanups: bool,
    use_db: bool = False,
    nutrition_sample: int | None = None,
) -> list[str]:
    python_cmd = [sys.executable, "-m"]
    if stage == "parse":
        return python_cmd + ["cookdex.ingredient_parser"]
    if stage == "foods":
        cmd = python_cmd + ["cookdex.foods_manager", "cleanup"]
        if apply_cleanups:
            cmd.append("--apply")
        return cmd
    if stage == "units":
        cmd = python_cmd + ["cookdex.units_manager", "cleanup"]
        if apply_cleanups:
            cmd.append("--apply")
        return cmd
    if stage == "labels":
        cmd = python_cmd + ["cookdex.labels_manager"]
        if apply_cleanups:
            cmd.append("--apply")
        return cmd
    if stage == "tools":
        cmd = python_cmd + ["cookdex.tools_manager"]
        if apply_cleanups:
            cmd.append("--apply")
        return cmd
    if stage == "taxonomy":
        taxonomy_mode = str(env_or_config("TAXONOMY_REFRESH_MODE", "taxonomy.refresh.mode", "merge"))
        cmd = python_cmd + [
            "cookdex.taxonomy_manager",
            "refresh",
            "--mode",
            taxonomy_mode,
            "--categories-file",
            "configs/taxonomy/categories.json",
            "--tags-file",
            "configs/taxonomy/tags.json",
            "--cleanup",
            "--cleanup-only-unused",
            "--cleanup-delete-noisy",
        ]
        if apply_cleanups:
            cmd.append("--cleanup-apply")
        return cmd
    if stage == "categorize":
        return python_cmd + ["cookdex.recipe_categorizer"]
    if stage == "cookbooks":
        return python_cmd + ["cookdex.cookbook_manager", "sync"]
    if stage == "yield":
        cmd = python_cmd + ["cookdex.yield_normalizer"]
        if apply_cleanups:
            cmd.append("--apply")
        return cmd
    if stage == "quality":
        cmd = python_cmd + ["cookdex.recipe_quality_audit"]
        if nutrition_sample is not None:
            cmd.extend(["--nutrition-sample", str(nutrition_sample)])
        if use_db:
            cmd.append("--use-db")
        return cmd
    if stage == "audit":
        return python_cmd + ["cookdex.audit_taxonomy"]
    if stage == "names":
        cmd = python_cmd + ["cookdex.recipe_name_normalizer"]
        if apply_cleanups:
            cmd.append("--apply")
        return cmd
    if stage == "dedup":
        cmd = python_cmd + ["cookdex.recipe_deduplicator"]
        if apply_cleanups:
            cmd.append("--apply")
        return cmd
    if stage == "junk":
        cmd = python_cmd + ["cookdex.recipe_junk_filter"]
        if apply_cleanups:
            cmd.append("--apply")
        return cmd
    raise ValueError(f"Unsupported stage: {stage}")


def default_stage_string() -> str:
    raw = env_or_config("MAINTENANCE_STAGES", "maintenance.default_stages", DEFAULT_STAGE_ORDER)
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return ",".join(str(item).strip() for item in raw if str(item).strip())
    return ",".join(DEFAULT_STAGE_ORDER)


def _fmt_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


def run_stage(
    stage: str,
    *,
    apply_cleanups: bool,
    skip_ai: bool = False,
    use_db: bool = False,
    nutrition_sample: int | None = None,
) -> StageResult:
    if stage == "categorize":
        if skip_ai:
            print(f"[skip] {stage}: skipped (--skip-ai flag set)", flush=True)
            return StageResult(stage=stage, command=[], exit_code=0)
        if not _categorizer_provider_active():
            print(
                f"[skip] {stage}: no AI provider configured "
                "(set CATEGORIZER_PROVIDER to enable)",
                flush=True,
            )
            return StageResult(stage=stage, command=[], exit_code=0)

    cmd = stage_command(stage, apply_cleanups=apply_cleanups, use_db=use_db, nutrition_sample=nutrition_sample)
    print(f"{'=' * 60}", flush=True)
    print(f"[start] {stage}", flush=True)
    t0 = time.monotonic()
    completed = subprocess.run(cmd, check=False)
    elapsed = time.monotonic() - t0
    if completed.returncode == 0:
        print(f"[done] {stage} ({_fmt_elapsed(elapsed)})", flush=True)
    else:
        print(
            f"[error] {stage}: exit code {completed.returncode} ({_fmt_elapsed(elapsed)})",
            flush=True,
        )
    return StageResult(stage=stage, command=cmd, exit_code=completed.returncode, elapsed_seconds=elapsed)


def run_pipeline(
    stages: Sequence[str],
    *,
    continue_on_error: bool,
    apply_cleanups: bool,
    skip_ai: bool = False,
    use_db: bool = False,
    nutrition_sample: int | None = None,
) -> list[StageResult]:
    results: list[StageResult] = []
    for stage in stages:
        result = run_stage(
            stage,
            apply_cleanups=apply_cleanups,
            skip_ai=skip_ai,
            use_db=use_db,
            nutrition_sample=nutrition_sample,
        )
        results.append(result)
        if result.exit_code != 0 and not continue_on_error:
            print(f"[error] Stage '{stage}' failed with exit code {result.exit_code}. Failing fast.", flush=True)
            break
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run CookDex data maintenance pipeline.")
    parser.add_argument(
        "--stages",
        default=default_stage_string(),
        help="Comma-separated stage order.",
    )
    parser.add_argument("--continue-on-error", action="store_true", help="Continue pipeline after stage failures.")
    parser.add_argument(
        "--apply-cleanups",
        action="store_true",
        help="Apply cleanup writes for foods/units/labels/tools/taxonomy/yield cleanup.",
    )
    parser.add_argument(
        "--skip-ai",
        action="store_true",
        help="Skip the categorize stage regardless of provider configuration.",
    )
    parser.add_argument(
        "--use-db",
        action="store_true",
        help="Use direct DB queries for the quality stage instead of the API.",
    )
    parser.add_argument(
        "--nutrition-sample",
        type=int,
        default=None,
        help="Number of recipes to sample for nutrition coverage (quality stage, API mode only).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    stages = parse_stage_list(str(args.stages))
    skip_ai = bool(args.skip_ai)
    use_db = bool(args.use_db)
    nutrition_sample: int | None = args.nutrition_sample
    print(
        f"[start] data-maintenance stages={','.join(stages)} "
        f"apply_cleanups={bool(args.apply_cleanups)} skip_ai={skip_ai} use_db={use_db}",
        flush=True,
    )
    results = run_pipeline(
        stages,
        continue_on_error=bool(args.continue_on_error),
        apply_cleanups=bool(args.apply_cleanups),
        skip_ai=skip_ai,
        use_db=use_db,
        nutrition_sample=nutrition_sample,
    )
    failed = [item for item in results if item.exit_code != 0]
    all_stages = [r.stage for r in results]
    failed_stages = [r.stage for r in failed]
    passed_count = len(results) - len(failed)
    total_elapsed = sum(r.elapsed_seconds for r in results)
    print(f"{'=' * 60}", flush=True)
    print(
        f"[done] {len(results)} stage(s) run — {passed_count} passed"
        + (f", {len(failed)} failed: {', '.join(failed_stages)}" if failed else "")
        + f" ({_fmt_elapsed(total_elapsed)} total)",
        flush=True,
    )
    if failed:
        for r in failed:
            print(
                f"  FAILED: {r.stage} (exit code {r.exit_code}, {_fmt_elapsed(r.elapsed_seconds)})",
                flush=True,
            )
    print("[summary] " + json.dumps({
        "Stages Run": len(results),
        "Passed": passed_count,
        "Failed": len(failed),
        "Failed Stages": ", ".join(failed_stages) if failed_stages else "none",
        "All Stages": ", ".join(all_stages),
        "Elapsed": _fmt_elapsed(total_elapsed),
    }), flush=True)
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
