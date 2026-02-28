"""Unit tests for yield_normalizer parsing, analysis, and action logic."""
from __future__ import annotations

import pytest

from cookdex.yield_normalizer import (
    YieldAction,
    _analyze_recipe,
    _build_yield_text,
    _extract_number,
    _parse_yield_text,
)


# ---------------------------------------------------------------------------
# _extract_number — mirrors Mealie's extract_quantity_from_string
# ---------------------------------------------------------------------------

class TestExtractNumber:
    def test_integer(self) -> None:
        assert _extract_number("6") == 6.0

    def test_decimal(self) -> None:
        assert _extract_number("2.5") == 2.5

    def test_mixed_fraction(self) -> None:
        assert _extract_number("1 1/2 cups") == 1.5

    def test_simple_fraction(self) -> None:
        assert _extract_number("1/2 batch") == 0.5

    def test_vulgar_half(self) -> None:
        assert _extract_number("\u00bd batch") == 0.5

    def test_vulgar_three_quarters(self) -> None:
        assert _extract_number("\u00be cup") == 0.75

    def test_vulgar_third(self) -> None:
        assert abs(_extract_number("\u2153 recipe") - 1 / 3) < 0.01

    def test_mixed_with_vulgar(self) -> None:
        # "1½" -> "1 1/2" after vulgar replacement
        assert _extract_number("1\u00bd cups") == 1.5

    def test_empty(self) -> None:
        assert _extract_number("") == 0.0

    def test_no_number(self) -> None:
        assert _extract_number("servings") == 0.0


# ---------------------------------------------------------------------------
# _parse_yield_text — pattern matching
# ---------------------------------------------------------------------------

class TestParseYieldText:
    def test_makes_n(self) -> None:
        assert _parse_yield_text("makes 6") == 6.0

    def test_serves_n(self) -> None:
        assert _parse_yield_text("serves 4") == 4.0

    def test_yields_n(self) -> None:
        assert _parse_yield_text("yields about 12") == 12.0

    def test_n_servings(self) -> None:
        assert _parse_yield_text("6 servings") == 6.0

    def test_n_cookies(self) -> None:
        assert _parse_yield_text("12 cookies") == 12.0

    def test_n_loaf(self) -> None:
        assert _parse_yield_text("1 loaf") == 1.0

    def test_n_people(self) -> None:
        assert _parse_yield_text("4 people") == 4.0

    def test_bare_number(self) -> None:
        assert _parse_yield_text("6") == 6.0

    def test_range(self) -> None:
        # "4-6" captures lower bound
        assert _parse_yield_text("4-6") == 4.0

    def test_range_with_unit(self) -> None:
        assert _parse_yield_text("4-6 servings") == 4.0

    def test_dozen(self) -> None:
        assert _parse_yield_text("1 dozen") == 12

    def test_two_dozen(self) -> None:
        assert _parse_yield_text("2 dozen cookies") == 24

    def test_bare_dozen(self) -> None:
        assert _parse_yield_text("dozen") == 12.0

    def test_decimal_yield(self) -> None:
        assert _parse_yield_text("2.5 cups") is not None

    def test_fraction_yield(self) -> None:
        # "1/2 batch" — fallback to _extract_number
        val = _parse_yield_text("1/2 batch")
        assert val == 0.5

    def test_vulgar_fraction(self) -> None:
        val = _parse_yield_text("\u00bd batch")
        assert val == 0.5

    def test_unparseable_bare_word(self) -> None:
        assert _parse_yield_text("servings") is None

    def test_unparseable_description(self) -> None:
        assert _parse_yield_text("large servings") is None

    def test_unparseable_unit_only(self) -> None:
        assert _parse_yield_text("cup") is None

    def test_empty(self) -> None:
        assert _parse_yield_text("") is None

    def test_whitespace_only(self) -> None:
        assert _parse_yield_text("   ") is None


# ---------------------------------------------------------------------------
# _build_yield_text
# ---------------------------------------------------------------------------

class TestBuildYieldText:
    def test_singular(self) -> None:
        assert _build_yield_text(1.0) == "1 serving"

    def test_plural(self) -> None:
        assert _build_yield_text(6.0) == "6 servings"

    def test_truncates_float(self) -> None:
        assert _build_yield_text(4.7) == "4 servings"


# ---------------------------------------------------------------------------
# _analyze_recipe — gap detection
# ---------------------------------------------------------------------------

class TestAnalyzeRecipe:
    def test_set_text_from_servings(self) -> None:
        r = {"slug": "test", "name": "Test", "recipeYield": "",
             "recipeYieldQuantity": 0, "recipeServings": 6}
        action = _analyze_recipe(r)
        assert action is not None
        assert action.action == "set_text"
        assert action.new_yield == "6 servings"
        # Payload must sync all 3 fields.
        assert action.payload["recipeYield"] == "6 servings"
        assert action.payload["recipeYieldQuantity"] == 6.0
        assert action.payload["recipeServings"] == 6.0

    def test_set_text_from_qty(self) -> None:
        r = {"slug": "test", "name": "Test", "recipeYield": None,
             "recipeYieldQuantity": 4, "recipeServings": 0}
        action = _analyze_recipe(r)
        assert action is not None
        assert action.action == "set_text"
        assert action.payload["recipeYieldQuantity"] == 4.0
        assert action.payload["recipeServings"] == 4.0

    def test_set_servings_from_text(self) -> None:
        r = {"slug": "test", "name": "Test", "recipeYield": "makes 12",
             "recipeYieldQuantity": 0, "recipeServings": 0}
        action = _analyze_recipe(r)
        assert action is not None
        assert action.action == "set_servings"
        assert action.new_servings == 12.0
        assert action.payload["recipeYieldQuantity"] == 12.0
        assert action.payload["recipeServings"] == 12.0

    def test_sync_qty_when_servings_set_but_qty_zero(self) -> None:
        """The most common gap: has text + servings but qty is 0."""
        r = {"slug": "test", "name": "Test", "recipeYield": "6 servings",
             "recipeYieldQuantity": 0, "recipeServings": 6}
        action = _analyze_recipe(r)
        assert action is not None
        assert action.action == "sync_qty"
        assert action.payload == {"recipeYieldQuantity": 6.0}

    def test_no_action_when_all_synced(self) -> None:
        r = {"slug": "test", "name": "Test", "recipeYield": "6 servings",
             "recipeYieldQuantity": 6, "recipeServings": 6}
        assert _analyze_recipe(r) is None

    def test_no_action_when_all_zero(self) -> None:
        r = {"slug": "test", "name": "Test", "recipeYield": "",
             "recipeYieldQuantity": 0, "recipeServings": 0}
        assert _analyze_recipe(r) is None

    def test_unparseable_text_returns_none(self) -> None:
        """Text with no number should return None (tracked as skipped)."""
        r = {"slug": "test", "name": "Test", "recipeYield": "servings",
             "recipeYieldQuantity": 0, "recipeServings": 0}
        assert _analyze_recipe(r) is None

    def test_set_text_singular(self) -> None:
        r = {"slug": "test", "name": "Test", "recipeYield": "",
             "recipeYieldQuantity": 0, "recipeServings": 1}
        action = _analyze_recipe(r)
        assert action is not None
        assert action.new_yield == "1 serving"
