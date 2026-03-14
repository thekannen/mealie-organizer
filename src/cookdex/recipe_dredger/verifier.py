"""Recipe verification — checks whether a URL contains a real recipe."""

from __future__ import annotations

import json
import re
from typing import Any, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .language import detect_language_from_html
from .patterns import (
    BAD_KEYWORDS,
    HOW_TO_COOK_REGEX,
    LISTICLE_REGEX,
    LISTICLE_TITLE_REGEX,
    NON_RECIPE_DIGEST_REGEX,
    NON_RECIPE_EXTENSIONS,
    NON_RECIPE_PATH_HINTS,
    NUMBERED_COLLECTION_REGEX,
    RECIPE_CLASS_PATTERN,
    TRANSIENT_HTTP_CODES,
)


class RecipeVerifier:
    def __init__(
        self,
        session: requests.Session,
        target_language: str = "en",
        language_filter_enabled: bool = True,
        language_detection_strict: bool = True,
        language_min_confidence: float = 0.70,
    ) -> None:
        self.session = session
        self.target_language = target_language
        self.language_filter_enabled = language_filter_enabled
        self.language_detection_strict = language_detection_strict
        self.language_min_confidence = language_min_confidence

    def pre_filter_candidate(self, url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
            path = parsed.path.lower()

            if path.endswith(NON_RECIPE_EXTENSIONS):
                return "Non-HTML media URL"
            if any(marker in path for marker in NON_RECIPE_PATH_HINTS):
                return "Non-recipe path"
            if path in ("/blog", "/blog/"):
                return "Blog index path"
        except Exception:
            pass
        return None

    def is_paranoid_skip(self, url: str, soup: Optional[BeautifulSoup] = None) -> Optional[str]:
        try:
            path = urlparse(url).path
            slug = path.strip("/").split("/")[-1].lower()
            normalized_slug = re.sub(r"[-_]+", " ", slug)

            if HOW_TO_COOK_REGEX.search(normalized_slug):
                return "How-to article"
            if NON_RECIPE_DIGEST_REGEX.search(normalized_slug):
                return "Digest/non-recipe post"
            if LISTICLE_REGEX.search(normalized_slug) or NUMBERED_COLLECTION_REGEX.search(normalized_slug):
                return f"Listicle detected: {slug}"
            for keyword in BAD_KEYWORDS:
                if keyword in normalized_slug:
                    return f"Bad keyword: {keyword}"

            if soup:
                title = soup.title.string.lower() if soup.title and soup.title.string else ""
                if HOW_TO_COOK_REGEX.search(title):
                    return "How-to title"
                if NON_RECIPE_DIGEST_REGEX.search(title):
                    return "Digest/non-recipe title"
                if (
                    LISTICLE_TITLE_REGEX.search(title)
                    or NUMBERED_COLLECTION_REGEX.search(title)
                    or "best recipes" in title
                    or "top 10" in title
                ):
                    return "Listicle title"
        except Exception:
            pass
        return None

    def _is_recipe_type(self, value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() == "recipe"
        if isinstance(value, list):
            return any(self._is_recipe_type(item) for item in value)
        return False

    def _iter_json_ld_items(self, value: Any):
        if isinstance(value, dict):
            graph = value.get("@graph")
            if isinstance(graph, list):
                for entry in graph:
                    yield from self._iter_json_ld_items(entry)
            else:
                yield value
            return
        if isinstance(value, list):
            for entry in value:
                yield from self._iter_json_ld_items(entry)

    def _has_ingredients(self, value: Any) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return any(isinstance(item, str) and item.strip() for item in value)
        return False

    def _has_instructions(self, value: Any) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return True
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        return True
                    nested = item.get("itemListElement")
                    if self._has_instructions(nested):
                        return True
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str) and text.strip():
                return True
            nested = value.get("itemListElement")
            if self._has_instructions(nested):
                return True
        return False

    def _recipe_schema_signal(self, soup: BeautifulSoup) -> Tuple[bool, bool]:
        """Return (has_recipe_type, has_strong_recipe_payload)."""
        has_recipe_type = False
        strong_payload = False

        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or script.get_text() or ""
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue

            for item in self._iter_json_ld_items(payload):
                if not isinstance(item, dict):
                    continue
                if not self._is_recipe_type(item.get("@type")):
                    continue
                has_recipe_type = True
                if self._has_ingredients(item.get("recipeIngredient")) or self._has_instructions(item.get("recipeInstructions")):
                    strong_payload = True
                    return has_recipe_type, strong_payload

        return has_recipe_type, strong_payload

    def verify_recipe(self, url: str) -> Tuple[bool, Optional[str], bool]:
        """Verify whether a URL contains a real recipe.

        Returns (is_recipe, error_reason, is_transient_error).
        """
        pre_filtered_reason = self.pre_filter_candidate(url)
        if pre_filtered_reason:
            return False, pre_filtered_reason, False

        try:
            response = self.session.get(url, timeout=10)
            if response.status_code != 200:
                is_transient = response.status_code in TRANSIENT_HTTP_CODES
                return False, f"HTTP {response.status_code}", is_transient

            soup = BeautifulSoup(response.content, "lxml")
            has_recipe_type, strong_recipe_payload = self._recipe_schema_signal(soup)
            has_recipe_card = bool(soup.find(class_=RECIPE_CLASS_PATTERN))

            if not strong_recipe_payload and not has_recipe_card:
                if has_recipe_type:
                    return False, "Weak recipe schema", False
                return False, "No recipe detected", False

            if self.language_filter_enabled and self.target_language:
                detected_language, _source, _confidence = detect_language_from_html(
                    soup,
                    response_text=response.text,
                    min_confidence=self.language_min_confidence,
                )
                if detected_language and detected_language != self.target_language:
                    return False, f"Language mismatch: {detected_language}", False
                if self.language_detection_strict and not detected_language:
                    return False, "Language unknown", False

            skip_reason = self.is_paranoid_skip(url, soup)
            if skip_reason:
                return False, skip_reason, False

            return True, None, False

        except requests.exceptions.Timeout as exc:
            return False, f"Timeout: {exc}", True
        except requests.exceptions.ConnectionError as exc:
            return False, f"Connection error: {exc}", True
        except requests.exceptions.RequestException as exc:
            return False, f"Request error: {exc}", True
        except Exception as exc:
            return False, f"Exception: {exc}", False
