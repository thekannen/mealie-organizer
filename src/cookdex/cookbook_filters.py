from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass

from lark import Lark, Transformer
from lark.exceptions import UnexpectedInput, VisitError


class CookbookFilterParseError(ValueError):
    def __init__(self, message: str, *, code: str = "cookbook_invalid_filter") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CookbookFilterClause:
    resource: str
    field: str
    identifier: str
    operator: str
    values: tuple[str, ...]


_GRAMMAR = r"""
start: clause (_AND clause)*
clause: FIELD operator value_list

operator: NOT IN -> not_in
        | CONTAINS ALL -> contains_all
        | IN -> in_

value_list: "[" [string ("," string)*] "]"
string: ESCAPED_STRING | SINGLE_QUOTED_STRING

FIELD: /[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+/
NOT: /NOT/i
CONTAINS: /CONTAINS/i
ALL: /ALL/i
IN: /IN/i
_AND: /AND/i
SINGLE_QUOTED_STRING: /'([^'\\]|\\.)*'/

%import common.ESCAPED_STRING
%import common.WS
%ignore WS
"""

_PARSER = Lark(_GRAMMAR, parser="lalr")

_FIELD_MAP: dict[str, tuple[str, str, str]] = {
    "recipecategory.name": ("categories", "recipeCategory.name", "name"),
    "recipe_category.name": ("categories", "recipeCategory.name", "name"),
    "recipecategory.id": ("categories", "recipe_category.id", "id"),
    "recipe_category.id": ("categories", "recipe_category.id", "id"),
    "tags.name": ("tags", "tags.name", "name"),
    "tags.id": ("tags", "tags.id", "id"),
    "tools.name": ("tools", "tools.name", "name"),
    "tools.id": ("tools", "tools.id", "id"),
    "recipeingredient.food.name": ("foods", "recipeIngredient.food.name", "name"),
    "recipe_ingredient.food.name": ("foods", "recipeIngredient.food.name", "name"),
    "recipeingredient.food.id": ("foods", "recipeIngredient.food.id", "id"),
    "recipe_ingredient.food.id": ("foods", "recipeIngredient.food.id", "id"),
}


def _decode_string(token: object) -> str:
    text = str(token)
    if text.startswith("'") and text.endswith("'"):
        try:
            value = ast.literal_eval(text)
            if isinstance(value, str):
                return value
        except (SyntaxError, ValueError):
            pass
        return text[1:-1].replace("\\'", "'").replace("\\\\", "\\")
    value = json.loads(text)
    return str(value)


class _FilterTransformer(Transformer):
    def start(self, items: list[object]) -> list[CookbookFilterClause]:
        return [item for item in items if isinstance(item, CookbookFilterClause)]

    def clause(self, items: list[object]) -> CookbookFilterClause:
        raw_field = str(items[0])
        field = _FIELD_MAP.get(raw_field.lower())
        if field is None:
            raise CookbookFilterParseError(f"Unsupported query field: {raw_field}", code="cookbook_invalid_field")
        resource, canonical_field, identifier = field
        return CookbookFilterClause(
            resource=resource,
            field=canonical_field,
            identifier=identifier,
            operator=str(items[1]),
            values=tuple(str(item) for item in items[2]),
        )

    def in_(self, _items: list[object]) -> str:
        return "IN"

    def not_in(self, _items: list[object]) -> str:
        return "NOT IN"

    def contains_all(self, _items: list[object]) -> str:
        return "CONTAINS ALL"

    def value_list(self, items: list[object]) -> tuple[str, ...]:
        return tuple(str(item) for item in items if item is not None)

    def string(self, items: list[object]) -> str:
        return _decode_string(items[0])


def normalize_query_filter_string(value: str) -> str:
    text = re.sub(r"\bCONTAINS[_ ]ANY\b", "IN", str(value or "").strip(), flags=re.IGNORECASE)
    if not text:
        return ""
    try:
        return serialize_cookbook_filter(parse_cookbook_filter(text))
    except CookbookFilterParseError:
        return re.sub(r"\s+", " ", text).strip()


def parse_cookbook_filter(query_filter: str) -> list[CookbookFilterClause]:
    text = re.sub(r"\bCONTAINS[_ ]ANY\b", "IN", str(query_filter or "").strip(), flags=re.IGNORECASE)
    if not text:
        return []
    try:
        tree = _PARSER.parse(text)
        parsed = _FilterTransformer().transform(tree)
    except VisitError as exc:
        if isinstance(exc.orig_exc, CookbookFilterParseError):
            raise exc.orig_exc from exc
        raise CookbookFilterParseError("Cookbook query filter is invalid.") from exc
    except UnexpectedInput as exc:
        raise CookbookFilterParseError("Cookbook query filter is invalid.") from exc
    if not isinstance(parsed, list):
        raise CookbookFilterParseError("Cookbook query filter is invalid.")
    return parsed


def serialize_cookbook_filter(clauses: list[CookbookFilterClause], *, compact_lists: bool = False) -> str:
    separator = "," if compact_lists else ", "
    parts: list[str] = []
    for clause in clauses:
        values = separator.join(json.dumps(value) for value in clause.values)
        parts.append(f"{clause.field} {clause.operator} [{values}]")
    return " AND ".join(parts)
