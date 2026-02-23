from pathlib import Path

from cookdex.recipe_name_normalizer import RecipeNameNormalizer, normalize_recipe_name


class _DummyClient:
    def get_recipes(self) -> list[dict[str, str]]:
        return [{"slug": "bbq-ribs", "name": "bbq's best ribs"}]

    def patch_recipe(self, slug: str, data: dict[str, str]) -> None:
        raise AssertionError("patch_recipe should not be called in audit mode")


def test_normalize_recipe_name_handles_gaelic_apostrophe() -> None:
    assert normalize_recipe_name("o'brien potato salad") == "O'Brien Potato Salad"


def test_normalize_recipe_name_handles_acronym_possessive() -> None:
    assert normalize_recipe_name("bbq's best ribs") == "BBQ's Best Ribs"


def test_audit_scope_uses_lowercase_only_label(tmp_path: Path) -> None:
    report_path = tmp_path / "normalize_report.json"
    normalizer = RecipeNameNormalizer(
        _DummyClient(),
        dry_run=True,
        apply=False,
        force_all=False,
        report_file=report_path,
    )

    report = normalizer.run()

    assert report["summary"]["scope"] == "lowercase-only"
