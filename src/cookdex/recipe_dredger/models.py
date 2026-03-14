from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RecipeCandidate:
    url: str

    def __hash__(self) -> int:
        return hash(self.url)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, RecipeCandidate):
            return self.url == other.url
        return self.url == other
