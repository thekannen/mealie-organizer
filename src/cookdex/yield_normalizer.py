"""Recipe Yield Normalizer.

Fills in the two sides of Mealie's yield fields so they stay consistent:

  recipeYield (text)         e.g. "6 servings"
  recipeYieldQuantity (float) e.g. 6.0
  recipeServings (float)     e.g. 6.0

Two gap patterns are detected and repaired:

  set_text     – recipe has a numeric servings value but no yield text.
                 → generates "N servings" text from the number.

  set_servings – recipe has yield text but no numeric value.
                 → parses the text with regex and writes the number back.

Concurrent writes are used when --apply is set so bulk patching is fast.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .api_client import MealieApiClient
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url, resolve_repo_path, to_bool

DEFAULT_REPORT = "reports/yield_normalize_report.json"
DEFAULT_WORKERS = 8
_DOZEN = 12

# Ordered from most to least specific.  Each captures the numeric count
# in group 1 (the lower bound of a range like "4-6" is captured).
_YIELD_PATTERNS: list[re.Pattern] = [
    # "makes 6", "serves 4", "yields about 12"
    re.compile(r"(?:makes?|serves?|yields?|about)\s+(\d+)", re.IGNORECASE),
    # "6 servings", "4 portions", "12 cookies", "1 loaf", …
    re.compile(
        r"^(\d+)(?:\s*[-–]\s*\d+)?\s+"
        r"(?:serving|portion|piece|cookie|muffin|cup|loaf|slice|biscuit|"
        r"pancake|waffle|roll|bar|tart|scone|brownie|cake|cupcake|bun|"
        r"burger|pita|tortilla|wrap|taco|crepe|donut|doughnut|fritter|"
        r"dumpling|person|people|ball|patty|skewer|kabob)",
        re.IGNORECASE,
    ),
    # bare number at start: "6" or "4-6"
    re.compile(r"^(\d+)(?:\s*[-–]\s*\d+)?$"),
]


def _parse_yield_text(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    # "1 dozen", "2 dozen cookies" → multiply
    m = re.search(r"(\d+)\s+dozen", text, re.IGNORECASE)
    if m:
        return int(m.group(1)) * _DOZEN
    if re.search(r"\bdozen\b", text, re.IGNORECASE):
        return _DOZEN
    for pat in _YIELD_PATTERNS:
        m = pat.search(text)
        if m:
            return int(m.group(1))
    return None


def _build_yield_text(n: float) -> str:
    count = int(n)
    return f"{count} serving" if count == 1 else f"{count} servings"


def _gs(d: dict, key: str, default: Any = None) -> Any:
    v = d.get(key)
    return v if v is not None else default


def _float_field(d: dict, key: str) -> float:
    try:
        return float(_gs(d, key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class YieldAction:
    slug: str
    name: str
    action: str        # "set_text" | "set_servings"
    old_yield: str
    new_yield: str
    old_servings: float
    new_servings: float
    payload: dict = field(default_factory=dict)


def _analyze_recipe(r: dict) -> YieldAction | None:
    slug = str(r.get("slug") or "")
    name = str(r.get("name") or "")
    yield_text = str(_gs(r, "recipeYield", "") or "").strip()
    qty = _float_field(r, "recipeYieldQuantity")
    servings = _float_field(r, "recipeServings")
    numeric = qty or servings  # prefer non-zero

    # Case 1: has numeric value but no text  →  generate text
    if not yield_text and numeric > 0:
        new_text = _build_yield_text(numeric)
        return YieldAction(
            slug=slug, name=name, action="set_text",
            old_yield="", new_yield=new_text,
            old_servings=numeric, new_servings=numeric,
            payload={"recipeYield": new_text},
        )

    # Case 2: has text but no numeric  →  parse text to number
    if yield_text and numeric == 0:
        parsed = _parse_yield_text(yield_text)
        if parsed and parsed > 0:
            return YieldAction(
                slug=slug, name=name, action="set_servings",
                old_yield=yield_text, new_yield=yield_text,
                old_servings=0.0, new_servings=float(parsed),
                payload={
                    "recipeYield": yield_text,
                    "recipeYieldQuantity": float(parsed),
                    "recipeServings": float(parsed),
                },
            )

    return None


class YieldNormalizer:
    def __init__(
        self,
        client: MealieApiClient,
        *,
        dry_run: bool = True,
        apply: bool = False,
        report_file: Path | str = DEFAULT_REPORT,
        workers: int = DEFAULT_WORKERS,
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.apply = apply
        self.report_file = Path(report_file)
        self.workers = workers

    def _apply_concurrent(self, actions: list[YieldAction]) -> tuple[list[dict], int, int]:
        action_log: list[dict] = []
        applied = 0
        failed = 0

        def _patch(action: YieldAction) -> tuple[YieldAction, bool, str]:
            try:
                self.client.patch_recipe(action.slug, action.payload)
                return action, True, ""
            except Exception as exc:
                return action, False, str(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(_patch, a): a for a in actions}
            for fut in concurrent.futures.as_completed(futures):
                action, ok, err = fut.result()
                if ok:
                    applied += 1
                    action_log.append({
                        "status": "ok",
                        "slug": action.slug,
                        "action": action.action,
                        "new_yield": action.new_yield,
                        "new_servings": action.new_servings,
                    })
                    print(
                        f"[ok] {action.slug}: {action.action} → '{action.new_yield}' (servings={action.new_servings})",
                        flush=True,
                    )
                else:
                    failed += 1
                    action_log.append({"status": "error", "slug": action.slug, "error": err})
                    print(f"[error] {action.slug}: {err}", flush=True)

        return action_log, applied, failed

    def run(self) -> dict[str, Any]:
        executable = self.apply and not self.dry_run
        print("[start] Fetching all recipes ...", flush=True)
        recipes = self.client.get_recipes()
        total = len(recipes)

        actions: list[YieldAction] = []
        for r in recipes:
            action = _analyze_recipe(r)
            if action:
                actions.append(action)

        set_text = sum(1 for a in actions if a.action == "set_text")
        set_servings = sum(1 for a in actions if a.action == "set_servings")
        print(
            f"[start] {total} recipes scanned → {len(actions)} yield gaps "
            f"({set_text} need text, {set_servings} need numeric)",
            flush=True,
        )

        action_log: list[dict] = []
        applied = 0
        failed = 0

        if executable:
            print(f"[start] Applying {len(actions)} yield patches (workers={self.workers}) ...", flush=True)
            action_log, applied, failed = self._apply_concurrent(actions)
        else:
            for action in actions:
                action_log.append({
                    "status": "planned",
                    "slug": action.slug,
                    "name": action.name,
                    "action": action.action,
                    "new_yield": action.new_yield,
                    "new_servings": action.new_servings,
                })
                print(
                    f"[plan] {action.slug}: {action.action} → '{action.new_yield}' (servings={action.new_servings})",
                    flush=True,
                )

        report: dict[str, Any] = {
            "summary": {
                "total_recipes": total,
                "yield_gaps": len(actions),
                "set_text_actions": set_text,
                "set_servings_actions": set_servings,
                "applied": applied,
                "failed": failed,
                "mode": "apply" if executable else "audit",
                "workers": self.workers if executable else 1,
            },
            "actions": action_log,
        }

        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        self.report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[done] Yield normalize report written to {self.report_file}", flush=True)
        print(
            f'[summary] {{"total": {total}, "gaps": {len(actions)}, '
            f'"applied": {applied}, "failed": {failed}, '
            f'"mode": "{"apply" if executable else "audit"}"}}',
            flush=True,
        )
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize recipe yield and servings fields.")
    parser.add_argument("--apply", action="store_true", help="Apply yield patches to Mealie.")
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Concurrent workers when applying patches.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    if dry_run:
        print("[start] runtime.dry_run=true (writes disabled; planning only).", flush=True)
    manager = YieldNormalizer(
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
        workers=args.workers,
    )
    manager.run()


if __name__ == "__main__":
    main()
