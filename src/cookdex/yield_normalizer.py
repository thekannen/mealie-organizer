"""Recipe Yield Normalizer.

Fills in the three sides of Mealie's yield fields so they stay consistent:

  recipeYield (text)         e.g. "6 servings"
  recipeYieldQuantity (float) e.g. 6.0
  recipeServings (float)     e.g. 6.0

Three gap patterns are detected and repaired:

  set_text     -- recipe has a numeric servings value but no yield text.
                  -> generates "N servings" text from the number and syncs
                     both numeric fields.

  set_servings -- recipe has yield text but no numeric value.
                  -> parses the text with regex and writes the number back.

  sync_qty     -- recipe has recipeServings and yield text, but
                  recipeYieldQuantity is 0.
                  -> copies recipeServings into recipeYieldQuantity so both
                     numeric fields agree.

Write modes
-----------
  API mode (default, --apply)
    Concurrent PATCH calls via Mealie HTTP API (8 workers).
  DB mode (--use-db, --apply)
    Direct UPDATE against Mealie's PostgreSQL/SQLite -- all rows in a
    single transaction; orders of magnitude faster for large libraries.
    Requires MEALIE_DB_TYPE and connection vars in .env.
    For remote PostgreSQL set up an SSH tunnel first:
        ssh -N -L 5432:127.0.0.1:5432 user@mealie-host
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import unicodedata
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from .api_client import MealieApiClient
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url, resolve_repo_path, to_bool
from .db_client import resolve_db_client

DEFAULT_REPORT = "reports/yield_normalize_report.json"
DEFAULT_WORKERS = 8
_DOZEN = 12

# ---------------------------------------------------------------------------
# Vulgar-fraction mapping (matches Mealie's cleaner.py)
# ---------------------------------------------------------------------------
_VULGAR_MAP: dict[str, str] = {
    "\u00bc": " 1/4", "\u00bd": " 1/2", "\u00be": " 3/4",
    "\u2150": " 1/7", "\u2151": " 1/9", "\u2152": " 1/10",
    "\u2153": " 1/3", "\u2154": " 2/3", "\u2155": " 1/5",
    "\u2156": " 2/5", "\u2157": " 3/5", "\u2158": " 4/5",
    "\u2159": " 1/6", "\u215a": " 5/6", "\u215b": " 1/8",
    "\u215c": " 3/8", "\u215d": " 5/8", "\u215e": " 7/8",
}

# ---------------------------------------------------------------------------
# Numeric extraction (mirrors Mealie's extract_quantity_from_string)
# ---------------------------------------------------------------------------
_RE_MIXED = re.compile(r"(\d+)\s+(\d+)/(\d+)")       # "1 1/2"
_RE_FRAC = re.compile(r"(\d+)/(\d+)")                  # "1/2"
_RE_DECIMAL = re.compile(r"\d+(?:\.\d+)?")              # "2.5" or "6"


def _extract_number(text: str) -> float:
    """Extract the leading numeric quantity from *text*, handling fractions.

    Mirrors Mealie's ``extract_quantity_from_string`` to stay consistent.
    Returns 0.0 when nothing parseable is found.
    """
    # Normalise vulgar fractions first (space-prefixed like Mealie).
    for vf, rep in _VULGAR_MAP.items():
        text = text.replace(vf, rep)

    m = _RE_MIXED.search(text)
    if m:
        return int(m.group(1)) + float(Fraction(int(m.group(2)), int(m.group(3))))

    m = _RE_FRAC.search(text)
    if m:
        return float(Fraction(int(m.group(1)), int(m.group(2))))

    m = _RE_DECIMAL.search(text)
    if m:
        return float(m.group())

    return 0.0


# ---------------------------------------------------------------------------
# Yield-text parsing (regex patterns, most to least specific)
# ---------------------------------------------------------------------------
_YIELD_PATTERNS: list[re.Pattern[str]] = [
    # "makes 6", "serves 4", "yields about 12", with optional fractions
    re.compile(r"(?:makes?|serves?|yields?|about)\s+(\d+(?:\.\d+)?)", re.IGNORECASE),
    # "6 servings", "4 portions", "12 cookies", "1 loaf", ...
    re.compile(
        r"^(\d+(?:\.\d+)?)(?:\s*[-\u2013]\s*\d+(?:\.\d+)?)?\s+"
        r"(?:serving|portion|piece|cookie|muffin|cup|loaf|slice|biscuit|"
        r"pancake|waffle|roll|bar|tart|scone|brownie|cake|cupcake|bun|"
        r"burger|pita|tortilla|wrap|taco|crepe|donut|doughnut|fritter|"
        r"dumpling|person|people|ball|patty|skewer|kabob)",
        re.IGNORECASE,
    ),
    # bare number at start: "6" or "4-6" or "2.5"
    re.compile(r"^(\d+(?:\.\d+)?)(?:\s*[-\u2013]\s*\d+(?:\.\d+)?)?$"),
]


def _parse_yield_text(text: str) -> float | None:
    """Parse a yield string into a numeric value.

    Returns the parsed number (int or float) or None if unparseable.
    Handles vulgar fractions, mixed fractions, decimals, dozens, and common
    yield patterns to stay aligned with Mealie's own quantity extraction.
    """
    text = text.strip()
    if not text:
        return None

    # Normalise vulgar fractions for pattern matching.
    normalized = text
    for vf, rep in _VULGAR_MAP.items():
        normalized = normalized.replace(vf, rep)

    # "1 dozen", "2 dozen cookies" -> multiply
    m = re.search(r"(\d+)\s+dozen", normalized, re.IGNORECASE)
    if m:
        return int(m.group(1)) * _DOZEN
    if re.search(r"\bdozen\b", normalized, re.IGNORECASE):
        return float(_DOZEN)

    # Try structured patterns first (they are more specific).
    for pat in _YIELD_PATTERNS:
        m = pat.search(normalized)
        if m:
            return float(m.group(1))

    # Fallback: extract any leading number (handles fractions, vulgar, etc.)
    val = _extract_number(normalized)
    return val if val > 0 else None


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


def _safe_print(text: str) -> None:
    """Print text safely on Windows terminals that choke on Unicode."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode(), flush=True)


@dataclass
class YieldAction:
    slug: str
    name: str
    action: str        # "set_text" | "set_servings" | "sync_qty"
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

    # Case 1: has numeric value but no text -> generate text + sync both numerics
    if not yield_text and numeric > 0:
        new_text = _build_yield_text(numeric)
        return YieldAction(
            slug=slug, name=name, action="set_text",
            old_yield="", new_yield=new_text,
            old_servings=numeric, new_servings=numeric,
            payload={
                "recipeYield": new_text,
                "recipeYieldQuantity": numeric,
                "recipeServings": numeric,
            },
        )

    # Case 2: has text but no numeric -> parse text to number
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

    # Case 3: has text + servings but recipeYieldQuantity is 0 -> sync qty
    if yield_text and servings > 0 and qty == 0:
        return YieldAction(
            slug=slug, name=name, action="sync_qty",
            old_yield=yield_text, new_yield=yield_text,
            old_servings=servings, new_servings=servings,
            payload={
                "recipeYieldQuantity": servings,
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
        use_db: bool = False,
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.apply = apply
        self.report_file = Path(report_file)
        self.workers = workers
        self.use_db = use_db

    def _apply_concurrent(self, actions: list[YieldAction]) -> tuple[list[dict], int, int]:
        action_log: list[dict] = []
        applied = 0
        failed = 0
        total = len(actions)
        # Track completion order for idx/total counter.
        counter = 0

        def _patch(action: YieldAction) -> tuple[YieldAction, bool, str]:
            try:
                self.client.patch_recipe(action.slug, action.payload)
                return action, True, ""
            except Exception as exc:
                return action, False, str(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(_patch, a): a for a in actions}
            for fut in concurrent.futures.as_completed(futures):
                counter += 1
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
                    _safe_print(
                        f"[ok] {counter}/{total} {action.slug} "
                        f"{action.action}='{action.new_yield}' servings={action.new_servings}"
                    )
                else:
                    failed += 1
                    action_log.append({"status": "error", "slug": action.slug, "error": err})
                    _safe_print(f"[error] {action.slug}: {err}")

        return action_log, applied, failed

    def _apply_db(
        self,
        actions: list[YieldAction],
        group_id: str | None,
        db_client: Any,
    ) -> tuple[list[dict], int, int]:
        """Bulk-update all yield fields via a single DB transaction."""
        updates = []
        for action in actions:
            p = action.payload
            u: dict[str, Any] = {"slug": action.slug}
            if "recipeYield" in p:
                u["recipe_yield"] = p["recipeYield"]
            if "recipeYieldQuantity" in p:
                u["recipe_yield_quantity"] = p["recipeYieldQuantity"]
            if "recipeServings" in p:
                u["recipe_servings"] = p["recipeServings"]
            updates.append(u)

        applied, failed = db_client.bulk_update_yield(updates, group_id=group_id)

        # DB mode is a single atomic transaction — emit one summary [ok]
        # line instead of per-row output (avoids stdout pipe stalls on
        # large batches).
        _safe_print(f"[ok] 1/1 db-transaction applied={applied} failed={failed}")

        action_log: list[dict] = [
            {
                "status": "ok",
                "slug": a.slug,
                "action": a.action,
                "new_yield": a.new_yield,
                "new_servings": a.new_servings,
                "mode": "db",
            }
            for a in actions
        ]
        return action_log, applied, failed

    def run(self) -> dict[str, Any]:
        executable = self.apply and not self.dry_run

        db_client = None
        group_id = None
        if self.use_db:
            db_client = resolve_db_client()
            if db_client is None:
                _safe_print("[warn] --use-db requested but MEALIE_DB_TYPE is not set; falling back to API.")
                self.use_db = False
            else:
                group_id = db_client.get_group_id()

        if self.use_db and db_client is not None:
            _safe_print("[start] Fetching recipes from DB ...")
            recipes = db_client.get_recipe_rows(group_id)
        else:
            _safe_print("[start] Fetching all recipes from API ...")
            recipes = self.client.get_recipes()

        total = len(recipes)

        actions: list[YieldAction] = []
        skipped: list[dict[str, str]] = []
        for r in recipes:
            action = _analyze_recipe(r)
            if action:
                actions.append(action)
            else:
                # Track unparseable set_servings candidates for visibility.
                yield_text = str(_gs(r, "recipeYield", "") or "").strip()
                qty = _float_field(r, "recipeYieldQuantity")
                servings = _float_field(r, "recipeServings")
                if yield_text and (qty == 0 and servings == 0):
                    skipped.append({
                        "slug": str(r.get("slug") or ""),
                        "yield_text": yield_text,
                    })

        set_text = sum(1 for a in actions if a.action == "set_text")
        set_servings = sum(1 for a in actions if a.action == "set_servings")
        sync_qty = sum(1 for a in actions if a.action == "sync_qty")
        _safe_print(
            f"[info] {total} recipes scanned -> {len(actions)} yield gaps "
            f"({set_text} need text, {set_servings} need numeric, {sync_qty} need qty sync)"
        )
        if skipped:
            _safe_print(f"[info] {len(skipped)} recipes have yield text but couldn't be parsed")

        action_log: list[dict] = []
        applied = 0
        failed = 0

        if executable:
            if self.use_db and db_client is not None:
                _safe_print(f"[info] Applying {len(actions)} yield patches via DB (single transaction) ...")
                action_log, applied, failed = self._apply_db(actions, group_id, db_client)
                _safe_print(f"[info] DB transaction committed: {applied} applied, {failed} failed.")
                db_client.close()
            else:
                _safe_print(f"[info] Applying {len(actions)} yield patches via API (workers={self.workers}) ...")
                action_log, applied, failed = self._apply_concurrent(actions)
        else:
            if db_client is not None:
                db_client.close()
            ntotal = len(actions)
            for idx, action in enumerate(actions, 1):
                action_log.append({
                    "status": "planned",
                    "slug": action.slug,
                    "name": action.name,
                    "action": action.action,
                    "new_yield": action.new_yield,
                    "new_servings": action.new_servings,
                })
                _safe_print(
                    f"[plan] {idx}/{ntotal} {action.slug} "
                    f"{action.action}='{action.new_yield}' servings={action.new_servings}"
                )
            for s in skipped:
                _safe_print(f"[skip] {s['slug']}: unparseable yield text '{s['yield_text']}'")

        report: dict[str, Any] = {
            "summary": {
                "total_recipes": total,
                "yield_gaps": len(actions),
                "set_text_actions": set_text,
                "set_servings_actions": set_servings,
                "sync_qty_actions": sync_qty,
                "skipped_unparseable": len(skipped),
                "applied": applied,
                "failed": failed,
                "mode": "apply" if executable else "audit",
                "workers": self.workers if executable else 1,
            },
            "actions": action_log,
        }

        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        self.report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        mode = "apply" if executable else "audit"
        _safe_print(
            f"[done] {len(actions)} yield gap(s) found in {total} recipes -- "
            f"{applied} applied ({mode} mode)"
        )
        summary: dict[str, Any] = {
            "__title__": "Yield Normalizer",
            "Total Recipes": total,
            "Yield Gaps": len(actions),
            "Set Yield Text": set_text,
            "Set Servings": set_servings,
            "Sync Qty": sync_qty,
            "Applied": applied,
            "Failed": failed,
            "Mode": mode,
        }
        if skipped:
            summary["Skipped (unparseable)"] = len(skipped)
        _safe_print("[summary] " + json.dumps(summary))
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize recipe yield and servings fields.")
    parser.add_argument("--apply", action="store_true", help="Apply yield patches to Mealie.")
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Concurrent workers when applying patches via API (ignored with --use-db).",
    )
    parser.add_argument(
        "--use-db",
        action="store_true",
        help=(
            "Write directly to Mealie's PostgreSQL/SQLite in a single transaction "
            "instead of individual API PATCH calls.  Requires MEALIE_DB_TYPE and "
            "MEALIE_PG_* (or MEALIE_SQLITE_PATH) in .env."
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    if dry_run:
        _safe_print("[start] runtime.dry_run=true (writes disabled; planning only).")
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
        use_db=bool(args.use_db),
    )
    manager.run()


if __name__ == "__main__":
    main()
