from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .api_client import MealieApiClient
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url, to_bool

DEFAULT_PARSER_STRATEGIES = ("nlp", "openai")
SERVING_PHRASES = {"for serving", "for garnish", "for dipping"}
NON_INGREDIENT_PREFIX_RE = re.compile(r"^(for|to)\s+", re.IGNORECASE)
ZERO_QTY_ALLOWED_UNITS = {"pinch", "dash"}
FRACTION_TEXT_REPLACEMENTS = {
    "1/2": "1/2",
    "1/4": "1/4",
    "3/4": "3/4",
    "1/3": "1/3",
    "2/3": "2/3",
    "1/8": "1/8",
    "3/8": "3/8",
    "5/8": "5/8",
    "7/8": "7/8",
}


class AlreadyParsed(Exception):
    pass


@dataclass(frozen=True)
class ParserRunConfig:
    confidence_threshold: float
    parser_strategies: tuple[str, ...]
    force_parser: str | None
    page_size: int
    delay_seconds: float
    timeout_seconds: int
    request_retries: int
    request_backoff_seconds: float
    max_recipes: int | None
    after_slug: str | None
    dry_run: bool
    output_dir: Path
    low_confidence_filename: str
    success_log_filename: str


@dataclass
class ParserRunSummary:
    total_candidates: int = 0
    parsed_successfully: int = 0
    requires_review: int = 0
    skipped_empty: int = 0
    skipped_already_parsed: int = 0
    dropped_blank_ingredients: int = 0


def _short_text(value: str, max_len: int = 220) -> str:
    text = value.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return int(text)


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            return int(text)
    raise ValueError(f"Invalid value for '{field}': expected integer-like, got {type(value).__name__}")


def _require_float(value: object, field: str) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            return float(text)
    raise ValueError(f"Invalid value for '{field}': expected float-like, got {type(value).__name__}")


def _parse_parser_strategies(raw: str, force_parser: str | None) -> tuple[str, ...]:
    if force_parser:
        return (force_parser,)
    parts = tuple(item.strip() for item in raw.split(",") if item.strip())
    ordered: list[str] = []
    for item in (*parts, *DEFAULT_PARSER_STRATEGIES):
        if item not in ordered:
            ordered.append(item)
    return tuple(ordered)


def parser_run_config() -> ParserRunConfig:
    force_parser = _str_or_none(env_or_config("FORCE_PARSER", "parser.force_parser", None))
    parser_strategies = _parse_parser_strategies(
        str(env_or_config("PARSER_STRATEGIES", "parser.strategies", ",".join(DEFAULT_PARSER_STRATEGIES))),
        force_parser,
    )

    return ParserRunConfig(
        confidence_threshold=_require_float(
            env_or_config("CONFIDENCE_THRESHOLD", "parser.confidence_threshold", 0.80, float),
            "parser.confidence_threshold",
        ),
        parser_strategies=parser_strategies,
        force_parser=force_parser,
        page_size=_require_int(env_or_config("PAGE_SIZE", "parser.page_size", 200, int), "parser.page_size"),
        delay_seconds=_require_float(
            env_or_config("DELAY_SECONDS", "parser.delay_seconds", 0.10, float),
            "parser.delay_seconds",
        ),
        timeout_seconds=_require_int(
            env_or_config("REQUEST_TIMEOUT_SECONDS", "parser.request_timeout_seconds", 30, int),
            "parser.request_timeout_seconds",
        ),
        request_retries=_require_int(
            env_or_config("REQUEST_RETRIES", "parser.request_retries", 3, int),
            "parser.request_retries",
        ),
        request_backoff_seconds=_require_float(
            env_or_config("REQUEST_BACKOFF_SECONDS", "parser.request_backoff_seconds", 0.4, float),
            "parser.request_backoff_seconds",
        ),
        max_recipes=_int_or_none(env_or_config("MAX_RECIPES", "parser.max_recipes_per_run", None)),
        after_slug=_str_or_none(env_or_config("AFTER_SLUG", "parser.after_slug", None)),
        dry_run=bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool)),
        output_dir=Path(str(env_or_config("OUTPUT_DIR", "parser.output_dir", "reports"))),
        low_confidence_filename=str(
            env_or_config("LOW_CONFIDENCE_FILE", "parser.low_confidence_file", "review_low_confidence.json")
        ),
        success_log_filename=str(env_or_config("SUCCESS_FILE", "parser.success_file", "parsed_success.log")),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bulk parse unparsed Mealie recipe ingredients with parser fallback."
    )
    parser.add_argument("--conf", type=float, help="confidence threshold 0-1")
    parser.add_argument("--max", dest="max_recipes", type=int, help="parse at most N recipes")
    parser.add_argument("--after-slug", help="skip recipes through this slug and resume after")
    parser.add_argument("--parsers", help="comma-separated parser order, e.g. nlp,openai")
    parser.add_argument("--force-parser", help="force a single parser strategy")
    parser.add_argument("--page-size", type=int, help="recipes per page when listing candidates")
    parser.add_argument("--delay", type=float, help="delay between successful recipe patches")
    parser.add_argument("--timeout", type=int, help="HTTP timeout seconds")
    parser.add_argument("--retries", type=int, help="HTTP retry count")
    parser.add_argument("--backoff", type=float, help="HTTP retry backoff factor")
    parser.add_argument("--dry-run", action="store_true", help="do not PATCH recipes")
    parser.add_argument("--output-dir", help="directory for output artifacts")
    return parser


def apply_cli_overrides(config: ParserRunConfig, args: argparse.Namespace) -> ParserRunConfig:
    force_parser = config.force_parser
    parser_strategies = config.parser_strategies
    if args.parsers:
        parser_strategies = _parse_parser_strategies(args.parsers, force_parser=None)
    if args.force_parser:
        force_parser = args.force_parser
        parser_strategies = (args.force_parser,)

    return ParserRunConfig(
        confidence_threshold=args.conf if args.conf is not None else config.confidence_threshold,
        parser_strategies=parser_strategies,
        force_parser=force_parser,
        page_size=args.page_size if args.page_size is not None else config.page_size,
        delay_seconds=args.delay if args.delay is not None else config.delay_seconds,
        timeout_seconds=args.timeout if args.timeout is not None else config.timeout_seconds,
        request_retries=args.retries if args.retries is not None else config.request_retries,
        request_backoff_seconds=args.backoff if args.backoff is not None else config.request_backoff_seconds,
        max_recipes=args.max_recipes if args.max_recipes is not None else config.max_recipes,
        after_slug=args.after_slug if args.after_slug is not None else config.after_slug,
        dry_run=True if args.dry_run else config.dry_run,
        output_dir=Path(args.output_dir) if args.output_dir else config.output_dir,
        low_confidence_filename=config.low_confidence_filename,
        success_log_filename=config.success_log_filename,
    )


def slim_entity(entity: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(entity, dict):
        return None
    entity_id = str(entity.get("id") or "").strip()
    if not entity_id:
        return None
    return {"id": entity_id, "name": str(entity.get("name") or "").strip()}


def _quantity_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _has_entity(entity: Any) -> bool:
    if entity is None:
        return False
    if isinstance(entity, dict):
        return bool(str(entity.get("id") or "").strip() or str(entity.get("name") or "").strip())
    return True


def _entity_name(entity: Any) -> str:
    if not isinstance(entity, dict):
        return ""
    return str(entity.get("name") or "").strip().lower()


def _is_blank_ingredient(ingredient: dict[str, Any]) -> bool:
    note = str(ingredient.get("note", "")).strip()
    quantity = _quantity_value(ingredient.get("quantity"))
    has_food = _has_entity(ingredient.get("food"))
    has_unit = _has_entity(ingredient.get("unit"))
    return not note and quantity == 0 and not has_food and not has_unit


def _suspicion_reason(ingredient: dict[str, Any]) -> str | None:
    if _is_blank_ingredient(ingredient):
        return None

    note = str(ingredient.get("note", "")).strip().lower()
    if any(phrase in note for phrase in SERVING_PHRASES):
        return None

    quantity = _quantity_value(ingredient.get("quantity"))
    unit = ingredient.get("unit")
    unit_name = _entity_name(unit)
    if quantity == 0 and unit is not None:
        if unit_name in ZERO_QTY_ALLOWED_UNITS or "to taste" in note:
            return None
        return "zero_qty_with_unit"

    if ingredient.get("food") is None and not note:
        return "missing_food_no_note"
    return None


def _confidence(parsed_line: dict[str, Any]) -> float:
    confidence = parsed_line.get("confidence") or {}
    value = confidence.get("average", 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def extract_raw_lines(recipe_json: dict[str, Any]) -> list[str]:
    if "recipeIngredient" in recipe_json:
        items = recipe_json.get("recipeIngredient") or []
        if not items:
            return []
        first = items[0]
        if isinstance(first, str):
            return [line.strip() for line in items if isinstance(line, str) and line.strip()]
        if isinstance(first, dict):
            all_food_null = all(item.get("food") is None for item in items if isinstance(item, dict))
            if not all_food_null:
                raise AlreadyParsed
            lines: list[str] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                line = (
                    item.get("originalText")
                    or item.get("rawText")
                    or item.get("note")
                    or str(item.get("display") or "")
                )
                text = str(line).strip()
                if text:
                    lines.append(text)
            return lines

    if "ingredients" in recipe_json:
        return [
            str(item.get("rawText", "")).strip()
            for item in recipe_json["ingredients"]
            if isinstance(item, dict) and str(item.get("rawText", "")).strip()
        ]
    return []


def _normalize_line_text(line: str) -> str:
    normalized = str(line).strip()
    for old, new in FRACTION_TEXT_REPLACEMENTS.items():
        normalized = normalized.replace(old, new)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _is_non_ingredient_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.endswith(":") and len(stripped.split()) <= 8 and not re.search(r"\d", stripped):
        return True
    if NON_INGREDIENT_PREFIX_RE.match(stripped) and len(stripped.split()) <= 8 and not re.search(r"\d", stripped):
        return True
    return False


def sanitize_raw_lines(lines: list[str]) -> tuple[list[str], int]:
    cleaned: list[str] = []
    dropped = 0
    for raw in lines:
        line = _normalize_line_text(raw)
        if not line:
            dropped += 1
            continue
        if _is_non_ingredient_header(line):
            dropped += 1
            continue
        cleaned.append(line)
    return cleaned, dropped


def _is_duplicate_food_error(message: str) -> bool:
    lowered = message.lower()
    return "duplicate key value violates unique constraint" in lowered and "ingredient_foods_name_group_id_key" in lowered


def ensure_food_object(client: MealieApiClient, food: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(food, dict):
        return None
    if food.get("id"):
        return slim_entity(food)
    name = str(food.get("name") or "").strip()
    if not name:
        return None
    try:
        created = client.create_food(name, group_id=_str_or_none(food.get("groupId")))
    except requests.RequestException as exc:
        if _is_duplicate_food_error(str(exc)):
            print(f"[warn] food create duplicate for '{name}', keeping for review", flush=True)
            return None
        print(f"[warn] food create failed '{name}': {_short_text(str(exc))}", flush=True)
        return None
    return slim_entity(created)


def parse_with_fallback(
    client: MealieApiClient,
    lines: list[str],
    parser_strategies: tuple[str, ...],
    confidence_threshold: float,
) -> tuple[list[dict[str, Any]], str | None, list[dict[str, str]]]:
    attempts: list[dict[str, str]] = []
    for strategy in parser_strategies:
        try:
            parsed = client.parse_ingredients(lines, strategy=strategy)
        except requests.RequestException as exc:
            attempts.append({"strategy": strategy, "error": _short_text(str(exc))})
            continue
        if not parsed:
            attempts.append({"strategy": strategy, "error": "empty parser response"})
            continue
        if not all(_confidence(item) >= confidence_threshold for item in parsed):
            attempts.append({"strategy": strategy, "error": "below confidence threshold"})
            continue
        return parsed, strategy, attempts
    return [], None, attempts


def normalize_parsed_block(
    client: MealieApiClient,
    parsed_block: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    normalized: list[dict[str, Any]] = []
    suspicious_reasons: dict[str, int] = {}
    dropped_blank = 0

    for item in parsed_block:
        ingredient = dict(item.get("ingredient") or {})
        ingredient["food"] = ensure_food_object(client, ingredient.get("food"))
        ingredient["unit"] = slim_entity(ingredient.get("unit"))
        ingredient.pop("confidence", None)
        ingredient.pop("display", None)

        if _is_blank_ingredient(ingredient):
            dropped_blank += 1
            continue

        reason = _suspicion_reason(ingredient)
        if reason:
            suspicious_reasons[reason] = suspicious_reasons.get(reason, 0) + 1
        normalized.append(ingredient)

    return normalized, suspicious_reasons, dropped_blank


def run_parser(client: MealieApiClient, config: ParserRunConfig) -> ParserRunSummary:
    if not 0 < config.confidence_threshold <= 1:
        raise ValueError("confidence threshold must be between 0 and 1")

    config.output_dir.mkdir(parents=True, exist_ok=True)

    all_recipes = client.get_recipes(per_page=config.page_size)
    slugs = [r["slug"] for r in all_recipes if r.get("slug") and not r.get("hasParsedIngredients")]

    if config.after_slug:
        if config.after_slug in slugs:
            slugs = slugs[slugs.index(config.after_slug) + 1 :]
            print(f"[info] Resuming after '{config.after_slug}'", flush=True)
        else:
            print(f"[warn] AFTER_SLUG '{config.after_slug}' not found; starting from beginning.", flush=True)

    if config.max_recipes is not None:
        slugs = slugs[: config.max_recipes]

    summary = ParserRunSummary(total_candidates=len(slugs))
    if not slugs:
        print("[done] No unparsed recipes found.", flush=True)
        return summary

    reviews: list[dict[str, Any]] = []
    successes: list[str] = []

    for idx, slug in enumerate(slugs, start=1):
        started = time.monotonic()
        try:
            recipe = client.get_recipe(slug)
        except requests.RequestException as exc:
            reviews.append({"slug": slug, "name": "<unknown>", "reason": "recipe_fetch_failed", "error": str(exc)})
            continue

        recipe_name = str(recipe.get("name") or slug)
        try:
            raw_lines = extract_raw_lines(recipe)
        except AlreadyParsed:
            summary.skipped_already_parsed += 1
            continue

        if not raw_lines:
            summary.skipped_empty += 1
            continue

        raw_lines, dropped_input = sanitize_raw_lines(raw_lines)
        if dropped_input:
            print(f"[info] {slug}: dropped {dropped_input} non-ingredient lines.", flush=True)
        if not raw_lines:
            summary.skipped_empty += 1
            continue

        parsed_block, parser_used, attempts = parse_with_fallback(
            client,
            raw_lines,
            config.parser_strategies,
            config.confidence_threshold,
        )
        if parser_used is None:
            reviews.append(
                {
                    "slug": slug,
                    "name": recipe_name,
                    "reason": "parser_failed_threshold",
                    "raw_lines": raw_lines,
                    "attempts": attempts,
                }
            )
            continue

        normalized, suspicious_reasons, dropped_blank = normalize_parsed_block(client, parsed_block)
        if dropped_blank:
            summary.dropped_blank_ingredients += dropped_blank
        if not normalized:
            reviews.append(
                {
                    "slug": slug,
                    "name": recipe_name,
                    "reason": "no_usable_ingredients_after_cleanup",
                    "parser": parser_used,
                    "raw_lines": raw_lines,
                }
            )
            continue
        if suspicious_reasons:
            reviews.append(
                {
                    "slug": slug,
                    "name": recipe_name,
                    "reason": "suspicious_result",
                    "parser": parser_used,
                    "raw_lines": raw_lines,
                    "parsed": normalized,
                    "suspicious_reasons": suspicious_reasons,
                }
            )
            continue

        if config.dry_run:
            print(f"[plan] {slug}: parser={parser_used} ingredients={len(normalized)}", flush=True)
        else:
            try:
                client.patch_recipe_ingredients(slug, normalized)
            except requests.RequestException as exc:
                reviews.append(
                    {
                        "slug": slug,
                        "name": recipe_name,
                        "reason": "patch_failed",
                        "parser": parser_used,
                        "error": str(exc),
                        "parsed": normalized,
                    }
                )
                continue

        successes.append(recipe_name)
        summary.parsed_successfully += 1
        print(
            f"[ok] {idx}/{summary.total_candidates} {slug} parser={parser_used} duration={time.monotonic() - started:.2f}s",
            flush=True,
        )
        if config.delay_seconds > 0:
            time.sleep(config.delay_seconds)

    if successes:
        success_path = config.output_dir / config.success_log_filename
        success_path.write_text("\n".join(successes), encoding="utf-8")
        print(f"[done] Parsed {len(successes)} recipes. Wrote {success_path}", flush=True)
    if reviews:
        review_path = config.output_dir / config.low_confidence_filename
        review_path.write_text(json.dumps(reviews, indent=2), encoding="utf-8")
        summary.requires_review = len(reviews)
        print(f"[warn] {len(reviews)} recipes need review. Wrote {review_path}", flush=True)
    return summary


def main() -> int:
    args = build_parser().parse_args()
    config = apply_cli_overrides(parser_run_config(), args)
    mealie_url = resolve_mealie_url()
    mealie_api_key = resolve_mealie_api_key(required=True)

    client = MealieApiClient(
        base_url=mealie_url,
        api_key=mealie_api_key,
        timeout_seconds=config.timeout_seconds,
        retries=config.request_retries,
        backoff_seconds=config.request_backoff_seconds,
    )
    summary = run_parser(client, config)
    print(
        "[summary] " + json.dumps({
            "candidates": summary.total_candidates,
            "parsed": summary.parsed_successfully,
            "review": summary.requires_review,
            "skipped_empty": summary.skipped_empty,
            "skipped_parsed": summary.skipped_already_parsed,
            "dropped_blank": summary.dropped_blank_ingredients,
        }),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
