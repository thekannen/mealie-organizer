"""Focused tests for recipe reimport patch construction."""

from __future__ import annotations

from typing import Any

from cookdex.recipe_reimporter import RecipeReimporter


class _FakeClient:
    def __init__(self) -> None:
        self.patch: dict[str, Any] | None = None
        self.patch_slug: str | None = None

    def get_recipe(self, _slug: str) -> dict[str, Any]:
        return {
            "tags": [{"name": "Dinner"}],
            "recipeCategory": [{"name": "Main"}],
            "orgURL": "https://old.example/recipe",
        }

    def patch_recipe(self, slug: str, patch: dict[str, Any]) -> None:
        self.patch_slug = slug
        self.patch = patch


def test_reimporter_builds_mealie_patch_from_recipe_scrapers_output(tmp_path):
    client = _FakeClient()
    reimporter = RecipeReimporter(client, dry_run=False, report_file=tmp_path / "report.json")

    def _scrape_with_retry(_slug: str, _url: str) -> dict[str, Any]:
        return {
            "description": " Freshly scraped ",
            "ingredients": ["1 cup flour", "2 eggs"],
            "instructions": "Mix the batter.\nBake until set.",
            "nutrients": {"@type": "NutritionInformation", "calories": "200 kcal"},
            "total_time": "45",
            "prep_time": 15,
            "cook_time": 30,
            "yields": "8 servings",
        }

    reimporter._scrape_with_retry = _scrape_with_retry  # type: ignore[method-assign]

    result = reimporter._process_one(1, 1, "cake", "Cake", "https://source.example/cake")

    assert result["status"] == "reimported"
    assert client.patch_slug == "cake"
    assert client.patch is not None
    assert [item["display"] for item in client.patch["recipeIngredient"]] == ["1 cup flour", "2 eggs"]
    assert [step["text"] for step in client.patch["recipeInstructions"]] == [
        "Mix the batter.",
        "Bake until set.",
    ]
    assert client.patch["nutrition"] == {"calories": "200 kcal"}
    assert client.patch["totalTime"] == "PT45M"
    assert client.patch["prepTime"] == "PT15M"
    assert client.patch["cookTime"] == "PT30M"
    assert client.patch["recipeYield"] == "8 servings"
    assert client.patch["orgURL"] == "https://source.example/cake"
    assert client.patch["tags"] == [{"name": "Dinner"}]
    assert client.patch["recipeCategory"] == [{"name": "Main"}]
