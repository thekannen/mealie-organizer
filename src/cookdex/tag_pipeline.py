"""Two-layer recipe tagging pipeline.

Layer 1 — Rule-based (deterministic, free, always available)
    Derives regex patterns from taxonomy item names and matches against
    recipe title/description.  Works without any AI provider.

Layer 2 — LLM-based (semantic, optional)
    Sends batches of recipes to an AI provider for richer classification.
    Only runs when an AI provider is configured (or forced via --provider).

Both layers assign Categories, Tags, and Tools.  Layer 2 fills gaps that
simple name-matching cannot reach.

Usage
-----
    # Preview both layers (rules + AI if configured)
    python -m cookdex.tag_pipeline

    # Rules only (no AI)
    python -m cookdex.tag_pipeline --skip-ai

    # AI only (skip rules)
    python -m cookdex.tag_pipeline --skip-rules

    # Override AI provider
    python -m cookdex.tag_pipeline --provider anthropic
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

from .config import env_or_config, to_bool


def _categorizer_provider_active() -> bool:
    """Return True when a usable AI provider is configured."""
    provider = str(
        env_or_config("CATEGORIZER_PROVIDER", "categorizer.provider", "chatgpt")
    ).strip().lower()
    return bool(provider) and provider not in {"none", "off", "false", "0", "disabled"}


def _fmt_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(round(seconds - (minutes * 60)))
    if secs == 60:
        minutes += 1
        secs = 0
    return f"{minutes}m {secs}s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Two-layer recipe tagging: rules first, then optional AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--provider",
        choices=["chatgpt", "ollama", "anthropic"],
        default=None,
        help="Override AI provider for Layer 2.",
    )
    parser.add_argument(
        "--skip-ai",
        action="store_true",
        help="Skip the AI layer entirely (rules only).",
    )
    parser.add_argument(
        "--skip-rules",
        action="store_true",
        help="Skip the rules layer entirely (AI only).",
    )
    parser.add_argument(
        "--use-db",
        action="store_true",
        help="Use direct DB queries for the rules layer.",
    )
    parser.add_argument(
        "--missing-targets",
        choices=["skip", "create"],
        default="skip",
        help="How to handle missing rule targets: 'skip' (default) or 'create'.",
    )
    parser.add_argument(
        "--config",
        default="",
        metavar="FILE",
        help="Custom rules file for Layer 1 (overrides taxonomy derivation).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    results: list[tuple[str, int]] = []

    # Layer 1: Rule-based tagging
    if not args.skip_rules:
        cmd = [sys.executable, "-m", "cookdex.rule_tagger"]
        if not dry_run:
            cmd.append("--apply")
        if args.use_db:
            cmd.append("--use-db")
        cmd.extend(["--missing-targets", args.missing_targets])
        if args.config:
            cmd.extend(["--config", args.config])
        else:
            cmd.append("--from-taxonomy")

        print("[info] -------- Layer 1: Rule-based tagging --------", flush=True)
        t0 = time.monotonic()
        completed = subprocess.run(cmd, check=False)
        elapsed = time.monotonic() - t0
        status = "done" if completed.returncode == 0 else "error"
        print(f"[{status}] Layer 1 ({_fmt_elapsed(elapsed)})", flush=True)
        results.append(("rules", completed.returncode))

    # Layer 2: AI categorization
    if not args.skip_ai:
        if args.provider or _categorizer_provider_active():
            cmd = [sys.executable, "-m", "cookdex.recipe_categorizer"]
            if args.provider:
                cmd.extend(["--provider", args.provider])

            print("[info] -------- Layer 2: AI categorization --------", flush=True)
            t0 = time.monotonic()
            completed = subprocess.run(cmd, check=False)
            elapsed = time.monotonic() - t0
            status = "done" if completed.returncode == 0 else "error"
            print(f"[{status}] Layer 2 ({_fmt_elapsed(elapsed)})", flush=True)
            results.append(("ai", completed.returncode))
        else:
            print(
                "[skip] Layer 2: no AI provider configured "
                "(set CATEGORIZER_PROVIDER or pass --provider)",
                flush=True,
            )

    if not results:
        print("[warn] Both layers skipped — nothing to do.", flush=True)
        return 0

    failed = [name for name, code in results if code != 0]
    if failed:
        print(f"[done] {len(results)} layer(s) run — failed: {', '.join(failed)}", flush=True)
        return 1

    print(f"[done] {len(results)} layer(s) run — all passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
