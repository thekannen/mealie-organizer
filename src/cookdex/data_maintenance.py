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


@dataclass(frozen=True)
class StageRuntimeOptions:
    provider: str | None = None
    junk_reason: str | None = None
    names_force_all: bool = False
    parse_confidence: float | None = None
    parse_max_recipes: int | None = None
    parse_after_slug: str | None = None
    parse_parsers: str | None = None
    parse_force_parser: str | None = None
    parse_page_size: int | None = None
    parse_delay_seconds: float | None = None
    parse_timeout_seconds: int | None = None
    parse_retries: int | None = None
    parse_backoff_seconds: float | None = None
    taxonomy_mode: str | None = None


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


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def stage_command(
    stage: str,
    *,
    apply_cleanups: bool,
    use_db: bool = False,
    nutrition_sample: int | None = None,
    stage_options: StageRuntimeOptions | None = None,
) -> list[str]:
    opts = stage_options or StageRuntimeOptions()
    python_cmd = [sys.executable, "-m"]
    if stage == "parse":
        cmd = python_cmd + ["cookdex.ingredient_parser"]
        if opts.parse_confidence is not None:
            cmd.extend(["--conf", str(opts.parse_confidence)])
        if opts.parse_max_recipes is not None:
            cmd.extend(["--max", str(opts.parse_max_recipes)])
        if opts.parse_after_slug:
            cmd.extend(["--after-slug", opts.parse_after_slug])
        if opts.parse_parsers:
            cmd.extend(["--parsers", opts.parse_parsers])
        if opts.parse_force_parser:
            cmd.extend(["--force-parser", opts.parse_force_parser])
        if opts.parse_page_size is not None:
            cmd.extend(["--page-size", str(opts.parse_page_size)])
        if opts.parse_delay_seconds is not None:
            cmd.extend(["--delay", str(opts.parse_delay_seconds)])
        if opts.parse_timeout_seconds is not None:
            cmd.extend(["--timeout", str(opts.parse_timeout_seconds)])
        if opts.parse_retries is not None:
            cmd.extend(["--retries", str(opts.parse_retries)])
        if opts.parse_backoff_seconds is not None:
            cmd.extend(["--backoff", str(opts.parse_backoff_seconds)])
        return cmd
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
        taxonomy_mode = opts.taxonomy_mode or str(
            env_or_config("TAXONOMY_REFRESH_MODE", "taxonomy.refresh.mode", "merge")
        )
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
        cmd = python_cmd + ["cookdex.recipe_categorizer"]
        if opts.provider:
            cmd.extend(["--provider", opts.provider])
        return cmd
    if stage == "cookbooks":
        return python_cmd + ["cookdex.cookbook_manager", "sync"]
    if stage == "yield":
        cmd = python_cmd + ["cookdex.yield_normalizer"]
        if apply_cleanups:
            cmd.append("--apply")
        if use_db:
            cmd.append("--use-db")
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
        if opts.names_force_all:
            cmd.append("--all")
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
        if opts.junk_reason:
            cmd.extend(["--reason", opts.junk_reason])
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
    secs = int(round(seconds - (minutes * 60)))
    if secs == 60:
        minutes += 1
        secs = 0
    return f"{minutes}m {secs}s"


def run_stage(
    stage: str,
    *,
    apply_cleanups: bool,
    skip_ai: bool = False,
    use_db: bool = False,
    nutrition_sample: int | None = None,
    stage_options: StageRuntimeOptions | None = None,
) -> StageResult:
    opts = stage_options or StageRuntimeOptions()
    if stage == "categorize":
        if skip_ai:
            print(f"[skip] {stage}: skipped (--skip-ai flag set)", flush=True)
            return StageResult(stage=stage, command=[], exit_code=0)
        if not opts.provider and not _categorizer_provider_active():
            print(
                f"[skip] {stage}: no AI provider configured "
                "(set CATEGORIZER_PROVIDER or pass --provider)",
                flush=True,
            )
            return StageResult(stage=stage, command=[], exit_code=0)

    cmd = stage_command(
        stage,
        apply_cleanups=apply_cleanups,
        use_db=use_db,
        nutrition_sample=nutrition_sample,
        stage_options=opts,
    )
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
    stage_options: StageRuntimeOptions | None = None,
) -> list[StageResult]:
    results: list[StageResult] = []
    for stage in stages:
        result = run_stage(
            stage,
            apply_cleanups=apply_cleanups,
            skip_ai=skip_ai,
            use_db=use_db,
            nutrition_sample=nutrition_sample,
            stage_options=stage_options,
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
        "--provider",
        choices=["chatgpt", "ollama"],
        default=None,
        help="Override AI provider for the categorize stage.",
    )
    parser.add_argument(
        "--use-db",
        action="store_true",
        help="Use direct DB mode for quality and yield stages instead of API calls.",
    )
    parser.add_argument(
        "--nutrition-sample",
        type=int,
        default=None,
        help="Number of recipes to sample for nutrition coverage (quality stage, API mode only).",
    )
    parser.add_argument(
        "--junk-reason",
        choices=["how_to", "listicle", "digest", "keyword", "utility", "bad_instructions"],
        default=None,
        help="Filter the junk stage to a single category.",
    )
    parser.add_argument(
        "--names-force-all",
        action="store_true",
        help="Normalize all recipe names when the names stage runs.",
    )
    parser.add_argument("--parse-conf", type=float, default=None, help="Ingredient parser confidence threshold (0-1).")
    parser.add_argument("--parse-max", type=int, default=None, help="Ingredient parser max recipes.")
    parser.add_argument("--parse-after-slug", default=None, help="Ingredient parser resume cursor.")
    parser.add_argument("--parse-parsers", default=None, help="Ingredient parser strategy list.")
    parser.add_argument("--parse-force-parser", default=None, help="Force ingredient parser strategy.")
    parser.add_argument("--parse-page-size", type=int, default=None, help="Ingredient parser page size.")
    parser.add_argument("--parse-delay", type=float, default=None, help="Ingredient parser delay in seconds.")
    parser.add_argument("--parse-timeout", type=int, default=None, help="Ingredient parser HTTP timeout.")
    parser.add_argument("--parse-retries", type=int, default=None, help="Ingredient parser retry count.")
    parser.add_argument("--parse-backoff", type=float, default=None, help="Ingredient parser retry backoff.")
    parser.add_argument(
        "--taxonomy-mode",
        choices=["merge", "replace"],
        default=None,
        help="Override taxonomy refresh mode for the taxonomy stage.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    stages = parse_stage_list(str(args.stages))
    skip_ai = bool(args.skip_ai)
    use_db = bool(args.use_db)
    nutrition_sample: int | None = args.nutrition_sample
    stage_options = StageRuntimeOptions(
        provider=_str_or_none(args.provider),
        junk_reason=_str_or_none(args.junk_reason),
        names_force_all=bool(args.names_force_all),
        parse_confidence=args.parse_conf,
        parse_max_recipes=args.parse_max,
        parse_after_slug=_str_or_none(args.parse_after_slug),
        parse_parsers=_str_or_none(args.parse_parsers),
        parse_force_parser=_str_or_none(args.parse_force_parser),
        parse_page_size=args.parse_page_size,
        parse_delay_seconds=args.parse_delay,
        parse_timeout_seconds=args.parse_timeout,
        parse_retries=args.parse_retries,
        parse_backoff_seconds=args.parse_backoff,
        taxonomy_mode=_str_or_none(args.taxonomy_mode),
    )
    print(
        f"[start] data-maintenance stages={','.join(stages)} "
        f"apply_cleanups={bool(args.apply_cleanups)} skip_ai={skip_ai} "
        f"use_db={use_db} provider={stage_options.provider or 'default'}",
        flush=True,
    )
    results = run_pipeline(
        stages,
        continue_on_error=bool(args.continue_on_error),
        apply_cleanups=bool(args.apply_cleanups),
        skip_ai=skip_ai,
        use_db=use_db,
        nutrition_sample=nutrition_sample,
        stage_options=stage_options,
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
