from __future__ import annotations

import argparse
import json
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .api_client import MealieApiClient
from .config import (
    env_or_config,
    resolve_mealie_api_key,
    resolve_mealie_url,
    resolve_repo_path,
    to_bool,
)


@dataclass
class FoodMergeAction:
    source_id: str
    source_name: str
    target_id: str
    target_name: str
    group_id: str
    normalized_name: str
    source_usage: int
    target_usage: int


class FoodsCleanupManager:
    def __init__(
        self,
        client: MealieApiClient,
        *,
        dry_run: bool = False,
        apply: bool = False,
        max_actions: int = 250,
        report_file: Path | str = "reports/foods_cleanup_report.json",
        checkpoint_dir: Path | str = "cache/maintenance",
        allow_fuzzy: bool = False,
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.apply = apply
        self.max_actions = max(1, int(max_actions))
        self.report_file = Path(report_file)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.allow_fuzzy = allow_fuzzy
        self.checkpoint_path = self.checkpoint_dir / "foods_cleanup_checkpoint.json"

    @staticmethod
    def normalize_name(name: str) -> str:
        text = unicodedata.normalize("NFKC", str(name or ""))
        text = " ".join(text.strip().casefold().split())
        return text

    def load_checkpoint(self) -> set[str]:
        if not self.checkpoint_path.exists():
            return set()
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            return set()
        merged = payload.get("merged_source_ids", [])
        if not isinstance(merged, list):
            return set()
        return {str(item) for item in merged if str(item).strip()}

    def save_checkpoint(self, merged_source_ids: set[str]) -> None:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        payload = {"merged_source_ids": sorted(merged_source_ids)}
        self.checkpoint_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def build_food_usage(self, recipes: list[dict[str, Any]]) -> dict[str, int]:
        usage: dict[str, int] = {}
        for recipe in recipes:
            recipe_ingredients = recipe.get("recipeIngredient")
            if isinstance(recipe_ingredients, list):
                for item in recipe_ingredients:
                    if not isinstance(item, dict):
                        continue
                    food = item.get("food")
                    if not isinstance(food, dict):
                        continue
                    food_id = str(food.get("id") or "").strip()
                    if not food_id:
                        continue
                    usage[food_id] = usage.get(food_id, 0) + 1
            ingredients = recipe.get("ingredients")
            if isinstance(ingredients, list):
                for item in ingredients:
                    if not isinstance(item, dict):
                        continue
                    food = item.get("food")
                    if not isinstance(food, dict):
                        continue
                    food_id = str(food.get("id") or "").strip()
                    if not food_id:
                        continue
                    usage[food_id] = usage.get(food_id, 0) + 1
        return usage

    def build_duplicate_groups(self, foods: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for food in foods:
            food_id = str(food.get("id") or "").strip()
            name = str(food.get("name") or "").strip()
            if not food_id or not name:
                continue
            group_id = str(food.get("groupId") or "").strip()
            normalized = self.normalize_name(name)
            if not normalized:
                continue
            key = (group_id, normalized)
            groups.setdefault(key, []).append(food)
        return {key: value for key, value in groups.items() if len(value) > 1}

    @staticmethod
    def choose_canonical(candidates: list[dict[str, Any]], usage: dict[str, int]) -> dict[str, Any]:
        ranked = sorted(
            candidates,
            key=lambda item: (
                -usage.get(str(item.get("id") or ""), 0),
                str(item.get("id") or ""),
            ),
        )
        return ranked[0]

    def build_merge_plan(self, foods: list[dict[str, Any]], usage: dict[str, int]) -> list[FoodMergeAction]:
        plan: list[FoodMergeAction] = []
        groups = self.build_duplicate_groups(foods)
        for (group_id, normalized_name), candidates in groups.items():
            canonical = self.choose_canonical(candidates, usage)
            target_id = str(canonical.get("id") or "")
            target_name = str(canonical.get("name") or "")
            target_usage = usage.get(target_id, 0)
            for item in candidates:
                source_id = str(item.get("id") or "")
                if source_id == target_id:
                    continue
                source_name = str(item.get("name") or "")
                source_usage = usage.get(source_id, 0)
                plan.append(
                    FoodMergeAction(
                        source_id=source_id,
                        source_name=source_name,
                        target_id=target_id,
                        target_name=target_name,
                        group_id=group_id,
                        normalized_name=normalized_name,
                        source_usage=source_usage,
                        target_usage=target_usage,
                    )
                )
        return sorted(plan, key=lambda action: (action.normalized_name, action.group_id, action.source_id))

    def build_fuzzy_candidates(self, foods: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.allow_fuzzy:
            return []
        by_group: dict[str, list[dict[str, Any]]] = {}
        for food in foods:
            name = str(food.get("name") or "").strip()
            food_id = str(food.get("id") or "").strip()
            if not name or not food_id:
                continue
            group_id = str(food.get("groupId") or "").strip()
            by_group.setdefault(group_id, []).append(food)

        results: list[dict[str, Any]] = []
        for group_id, values in by_group.items():
            normalized_pairs = [
                (str(item.get("id") or ""), str(item.get("name") or ""), self.normalize_name(str(item.get("name") or "")))
                for item in values
            ]
            for i in range(len(normalized_pairs)):
                id_a, name_a, norm_a = normalized_pairs[i]
                if not norm_a:
                    continue
                for j in range(i + 1, len(normalized_pairs)):
                    id_b, name_b, norm_b = normalized_pairs[j]
                    if not norm_b or norm_a == norm_b:
                        continue
                    ratio = SequenceMatcher(a=norm_a, b=norm_b).ratio()
                    if ratio >= 0.92:
                        results.append(
                            {
                                "group_id": group_id,
                                "food_a_id": id_a,
                                "food_a_name": name_a,
                                "food_b_id": id_b,
                                "food_b_name": name_b,
                                "similarity": round(ratio, 4),
                            }
                        )
        return sorted(results, key=lambda item: (-item["similarity"], item["food_a_name"], item["food_b_name"]))

    def run(self) -> dict[str, Any]:
        foods = self.client.list_foods(per_page=1000)
        recipes = self.client.get_recipes(per_page=1000)
        usage = self.build_food_usage(recipes)
        plan = self.build_merge_plan(foods, usage)
        fuzzy_candidates = self.build_fuzzy_candidates(foods)

        checkpoint = self.load_checkpoint()
        applied = 0
        failed = 0
        skipped_checkpoint = 0
        applied_source_ids = set(checkpoint)
        attempted: list[dict[str, Any]] = []

        executable = self.apply and not self.dry_run
        for action in plan:
            if action.source_id in checkpoint:
                skipped_checkpoint += 1
                continue
            if executable and applied >= self.max_actions:
                break

            entry = {
                "source_id": action.source_id,
                "source_name": action.source_name,
                "target_id": action.target_id,
                "target_name": action.target_name,
                "group_id": action.group_id,
                "normalized_name": action.normalized_name,
                "source_usage": action.source_usage,
                "target_usage": action.target_usage,
                "mode": "apply" if executable else "plan",
            }

            if executable:
                try:
                    self.client.merge_food(action.source_id, action.target_id)
                    applied += 1
                    applied_source_ids.add(action.source_id)
                    entry["status"] = "merged"
                    self.save_checkpoint(applied_source_ids)
                except Exception as exc:
                    failed += 1
                    entry["status"] = "failed"
                    entry["error"] = str(exc)
            else:
                entry["status"] = "planned"
            attempted.append(entry)

        report = {
            "summary": {
                "foods_total": len(foods),
                "duplicate_groups": len(self.build_duplicate_groups(foods)),
                "merge_candidates_total": len(plan),
                "actions_attempted": len(attempted),
                "actions_applied": applied,
                "actions_failed": failed,
                "checkpoint_skipped": skipped_checkpoint,
                "mode": "apply" if executable else "audit",
                "allow_fuzzy": self.allow_fuzzy,
            },
            "attempted_actions": attempted,
            "fuzzy_candidates": fuzzy_candidates,
            "checkpoint_file": str(self.checkpoint_path),
        }

        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        self.report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[done] Foods cleanup report written to {self.report_file}", flush=True)
        print(f"[summary] {json.dumps(report['summary'], indent=2)}", flush=True)
        return report


def require_int(value: object, field: str) -> int:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mealie foods cleanup manager.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    cleanup = subparsers.add_parser("cleanup", help="Audit/apply foods dedupe merge actions.")
    cleanup.add_argument("--apply", action="store_true", help="Apply merge actions.")
    cleanup.add_argument(
        "--max-actions",
        type=int,
        default=require_int(
            env_or_config("MAX_ACTIONS_PER_STAGE", "maintenance.max_actions_per_stage", 250, int),
            "maintenance.max_actions_per_stage",
        ),
    )
    cleanup.add_argument(
        "--report-file",
        default=str(env_or_config("FOODS_REPORT_FILE", "foods.report_file", "reports/foods_cleanup_report.json")),
    )
    cleanup.add_argument(
        "--checkpoint-dir",
        default=str(env_or_config("CHECKPOINT_DIR", "maintenance.checkpoint_dir", "cache/maintenance")),
    )
    cleanup.add_argument(
        "--allow-fuzzy",
        action="store_true",
        default=bool(env_or_config("FOODS_ALLOW_FUZZY", "foods.allow_fuzzy", False, to_bool)),
        help="Report fuzzy candidates in addition to exact duplicates.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "cleanup":
        raise RuntimeError(f"Unsupported command: {args.command}")

    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    if dry_run:
        print("[start] runtime.dry_run=true (writes disabled; planning only).", flush=True)

    client = MealieApiClient(
        base_url=resolve_mealie_url(),
        api_key=resolve_mealie_api_key(required=True),
        timeout_seconds=60,
        retries=3,
        backoff_seconds=0.4,
    )

    manager = FoodsCleanupManager(
        client,
        dry_run=dry_run,
        apply=bool(args.apply),
        max_actions=require_int(args.max_actions, "--max-actions"),
        report_file=resolve_repo_path(args.report_file),
        checkpoint_dir=resolve_repo_path(args.checkpoint_dir),
        allow_fuzzy=bool(args.allow_fuzzy),
    )
    manager.run()


if __name__ == "__main__":
    main()
