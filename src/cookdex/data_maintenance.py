from __future__ import annotations

import argparse
import subprocess
import sys
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


def stage_command(stage: str, *, apply_cleanups: bool) -> list[str]:
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
        return python_cmd + ["cookdex.recipe_quality_audit"]
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


def run_stage(stage: str, *, apply_cleanups: bool, skip_ai: bool = False) -> StageResult:
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

    cmd = stage_command(stage, apply_cleanups=apply_cleanups)
    print(f"[stage] {stage}: {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, check=False)
    return StageResult(stage=stage, command=cmd, exit_code=completed.returncode)


def run_pipeline(
    stages: Sequence[str],
    *,
    continue_on_error: bool,
    apply_cleanups: bool,
    skip_ai: bool = False,
) -> list[StageResult]:
    results: list[StageResult] = []
    for stage in stages:
        result = run_stage(stage, apply_cleanups=apply_cleanups, skip_ai=skip_ai)
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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    stages = parse_stage_list(str(args.stages))
    skip_ai = bool(args.skip_ai)
    print(
        f"[start] data-maintenance stages={','.join(stages)} "
        f"apply_cleanups={bool(args.apply_cleanups)} skip_ai={skip_ai}",
        flush=True,
    )
    results = run_pipeline(
        stages,
        continue_on_error=bool(args.continue_on_error),
        apply_cleanups=bool(args.apply_cleanups),
        skip_ai=skip_ai,
    )
    failed = [item for item in results if item.exit_code != 0]
    if failed:
        print(
            "[summary] failed_stages="
            + ",".join(f"{item.stage}({item.exit_code})" for item in failed),
            flush=True,
        )
        return 1
    print("[summary] all stages completed successfully.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
