"""Recipe Gold Medallion Quality Auditor.

Scores every recipe across six summary-level dimensions:
  category, tags, tools, description, time, yield

Plus estimates nutrition coverage via a configurable random sample of full recipes.

Tiers:
  Gold   = 5-6 / 6  (publication-ready)
  Silver = 3-4 / 6  (mostly complete)
  Bronze = 0-2 / 6  (needs work)

No writes are performed; this is a read-only audit.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .api_client import MealieApiClient
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url, resolve_repo_path

GOLD_DIMS = ["category", "tags", "tools", "description", "time", "yield"]
MAX_SCORE = len(GOLD_DIMS)  # 6

DEFAULT_REPORT = "reports/quality_audit_report.json"
DEFAULT_NUTRITION_SAMPLE = 200
DEFAULT_WORKERS = 8


def _tier(score: int) -> str:
    if score >= 5:
        return "gold"
    if score >= 3:
        return "silver"
    return "bronze"


def _gs(d: dict, key: str, default: Any = None) -> Any:
    v = d.get(key)
    return v if v is not None else default


def _has_time(r: dict) -> bool:
    for key in ("prepTime", "totalTime", "performTime", "cookTime"):
        if str(_gs(r, key, "") or "").strip():
            return True
    return False


def _has_yield(r: dict) -> bool:
    if str(_gs(r, "recipeYield", "") or "").strip():
        return True
    try:
        if float(_gs(r, "recipeYieldQuantity", 0) or 0) > 0:
            return True
        if float(_gs(r, "recipeServings", 0) or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return False


def _score_recipe(r: dict) -> tuple[int, dict[str, bool]]:
    dims: dict[str, bool] = {
        "category": bool(r.get("recipeCategory")),
        "tags": bool(r.get("tags")),
        "tools": bool(r.get("tools")),
        "description": bool(str(_gs(r, "description", "") or "").strip()),
        "time": _has_time(r),
        "yield": _has_yield(r),
    }
    return sum(dims.values()), dims


def _check_nutrition(client: MealieApiClient, slug: str) -> bool:
    try:
        full = client.get_recipe(slug)
        nutr = full.get("nutrition") or {}
        return any(v for v in nutr.values() if v)
    except Exception:
        return False


@dataclass
class RecipeScore:
    slug: str
    name: str
    score: int
    missing: list[str] = field(default_factory=list)


class RecipeQualityAuditor:
    def __init__(
        self,
        client: MealieApiClient,
        *,
        report_file: Path | str = DEFAULT_REPORT,
        nutrition_sample_size: int = DEFAULT_NUTRITION_SAMPLE,
        workers: int = DEFAULT_WORKERS,
    ) -> None:
        self.client = client
        self.report_file = Path(report_file)
        self.nutrition_sample_size = nutrition_sample_size
        self.workers = workers

    def run(self) -> dict[str, Any]:
        print("[start] Fetching all recipes ...", flush=True)
        recipes = self.client.get_recipes()
        total = len(recipes)
        print(f"[start] Scoring {total} recipes on {MAX_SCORE} gold medallion dimensions ...", flush=True)

        tier_counts: dict[str, int] = {"bronze": 0, "silver": 0, "gold": 0}
        score_dist: dict[int, int] = {i: 0 for i in range(MAX_SCORE + 1)}
        dim_hits: dict[str, int] = {d: 0 for d in GOLD_DIMS}
        recipe_scores: list[RecipeScore] = []

        for r in recipes:
            pts, dims = _score_recipe(r)
            score_dist[pts] += 1
            tier_counts[_tier(pts)] += 1
            for d, ok in dims.items():
                if ok:
                    dim_hits[d] += 1
            recipe_scores.append(RecipeScore(
                slug=str(r.get("slug") or ""),
                name=str(r.get("name") or ""),
                score=pts,
                missing=[d for d, ok in dims.items() if not ok],
            ))

        # Estimate nutrition coverage concurrently via sampling
        sample_n = min(self.nutrition_sample_size, total)
        print(f"[start] Sampling {sample_n} full recipes for nutrition coverage (workers={self.workers}) ...", flush=True)
        sample_slugs = [recipes[i]["slug"] for i in random.sample(range(total), sample_n)]
        nutr_hits = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(_check_nutrition, self.client, slug): slug for slug in sample_slugs}
            for fut in concurrent.futures.as_completed(futures):
                if fut.result():
                    nutr_hits += 1

        nutrition_pct = round(nutr_hits / sample_n * 100, 1) if sample_n else 0.0
        estimated_no_nutrition = int((1.0 - nutr_hits / max(sample_n, 1)) * total)

        # Gap ranking (most impactful = most missing)
        gaps = sorted(
            [
                {
                    "dimension": d,
                    "missing": total - dim_hits[d],
                    "pct_missing": round((total - dim_hits[d]) / max(total, 1) * 100, 1),
                }
                for d in GOLD_DIMS
            ],
            key=lambda x: -x["missing"],
        )

        # Worst and almost-gold
        sorted_scores = sorted(recipe_scores, key=lambda x: x.score)
        worst_20 = [
            {"slug": r.slug, "name": r.name, "score": r.score, "missing": r.missing}
            for r in sorted_scores[:20]
        ]
        almost_gold = [
            {"slug": r.slug, "name": r.name, "score": r.score, "missing": r.missing}
            for r in sorted_scores
            if r.score == MAX_SCORE - 1
        ][:50]

        gold_pct = round(tier_counts["gold"] / max(total, 1) * 100, 1)

        report: dict[str, Any] = {
            "summary": {
                "total": total,
                "gold": tier_counts["gold"],
                "silver": tier_counts["silver"],
                "bronze": tier_counts["bronze"],
                "gold_pct": gold_pct,
                "tiers": "gold=5-6, silver=3-4, bronze=0-2",
                "nutrition_sample_size": sample_n,
                "nutrition_pct_estimated": nutrition_pct,
                "estimated_no_nutrition": estimated_no_nutrition,
            },
            "score_distribution": {str(k): v for k, v in score_dist.items()},
            "dimension_coverage": {
                d: {
                    "have": dim_hits[d],
                    "missing": total - dim_hits[d],
                    "pct_have": round(dim_hits[d] / max(total, 1) * 100, 1),
                }
                for d in GOLD_DIMS
            },
            "nutrition_coverage": {
                "sample_size": sample_n,
                "have_pct": nutrition_pct,
                "estimated_missing": estimated_no_nutrition,
            },
            "gaps_ranked": gaps,
            "worst_20_recipes": worst_20,
            "almost_gold_recipes": almost_gold,
        }

        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        self.report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[done] Quality audit report written to {self.report_file}", flush=True)

        g = tier_counts["gold"]
        s = tier_counts["silver"]
        b = tier_counts["bronze"]
        print(f'[summary] {{"total": {total}, "gold": {g} ({gold_pct}%), "silver": {s}, "bronze": {b}}}', flush=True)
        print("[summary] gaps ranked by impact:", flush=True)
        for gap in gaps:
            print(f"  [{gap['dimension']:12s}] missing {gap['missing']:5d} ({gap['pct_missing']:5.1f}%)", flush=True)
        print(f"[summary] nutrition_pct_estimated={nutrition_pct}%  (sample_n={sample_n})", flush=True)

        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit recipe gold medallion completeness.")
    parser.add_argument(
        "--output",
        default=env_or_config("QUALITY_AUDIT_OUTPUT", "quality.audit_report", DEFAULT_REPORT),
        help="Output path for the JSON report.",
    )
    parser.add_argument(
        "--nutrition-sample",
        type=int,
        default=int(env_or_config("QUALITY_NUTRITION_SAMPLE", "quality.nutrition_sample", DEFAULT_NUTRITION_SAMPLE)),
        help="Number of full recipes to fetch for nutrition coverage estimate.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Concurrent workers for nutrition sampling.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manager = RecipeQualityAuditor(
        MealieApiClient(
            base_url=resolve_mealie_url(),
            api_key=resolve_mealie_api_key(required=True),
            timeout_seconds=60,
            retries=3,
            backoff_seconds=0.4,
        ),
        report_file=resolve_repo_path(args.output),
        nutrition_sample_size=args.nutrition_sample,
        workers=args.workers,
    )
    manager.run()


if __name__ == "__main__":
    main()
