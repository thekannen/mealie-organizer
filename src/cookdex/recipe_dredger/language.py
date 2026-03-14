"""Language detection for recipe pages and payloads.

Uses declared HTML/JSON-LD attributes first, then falls back to
statistical detection via langdetect.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional, Tuple

from bs4 import BeautifulSoup
from langdetect import DetectorFactory, LangDetectException, detect_langs

# Make detection deterministic between runs.
DetectorFactory.seed = 0

WHITESPACE_RE = re.compile(r"\s+")


def normalize_language_code(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower().replace("_", "-")
    if not cleaned or cleaned == "x-default":
        return None
    primary = cleaned.split("-", 1)[0]
    if len(primary) < 2:
        return None
    return primary


def _coerce_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _iter_strings(values: Iterable[object]) -> Iterable[str]:
    for value in values:
        text = _coerce_text(value).strip()
        if text:
            yield text


def detect_language_from_text(text: str, min_confidence: float = 0.70) -> Tuple[Optional[str], float]:
    normalized_text = WHITESPACE_RE.sub(" ", _coerce_text(text)).strip()
    if not normalized_text:
        return None, 0.0

    try:
        detections = detect_langs(normalized_text[:12000])
    except LangDetectException:
        return None, 0.0
    except Exception:
        return None, 0.0

    if not detections:
        return None, 0.0

    top_detection = detections[0]
    language = normalize_language_code(top_detection.lang)
    confidence = float(top_detection.prob)
    if not language:
        return None, confidence
    if confidence < min_confidence:
        return None, confidence
    return language, confidence


def _extract_declared_language_from_jsonld(soup: BeautifulSoup) -> Optional[str]:
    def find_in_language(payload: Any) -> Optional[str]:
        if isinstance(payload, dict):
            if "inLanguage" in payload:
                value = payload["inLanguage"]
                if isinstance(value, list):
                    for item in value:
                        normalized = normalize_language_code(item)
                        if normalized:
                            return normalized
                else:
                    normalized = normalize_language_code(value)
                    if normalized:
                        return normalized
            for nested in payload.values():
                found = find_in_language(nested)
                if found:
                    return found
        if isinstance(payload, list):
            for nested in payload:
                found = find_in_language(nested)
                if found:
                    return found
        return None

    for script in soup.find_all("script", type=lambda v: isinstance(v, str) and "ld+json" in v):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        found = find_in_language(data)
        if found:
            return found
    return None


def _extract_declared_language_from_soup(soup: BeautifulSoup) -> Optional[str]:
    html_tag = soup.find("html")
    if html_tag:
        lang_attr = html_tag.attrs.get("lang")
        normalized = normalize_language_code(lang_attr)
        if normalized:
            return normalized

    for selector in [
        {"name": "meta", "attrs": {"http-equiv": re.compile(r"content-language", re.IGNORECASE)}},
        {"name": "meta", "attrs": {"name": re.compile(r"language", re.IGNORECASE)}},
        {"name": "meta", "attrs": {"property": re.compile(r"og:locale", re.IGNORECASE)}},
    ]:
        tag = soup.find(selector["name"], attrs=selector["attrs"])
        if tag:
            normalized = normalize_language_code(tag.attrs.get("content"))
            if normalized:
                return normalized

    return _extract_declared_language_from_jsonld(soup)


def _extract_text_from_soup(soup: BeautifulSoup) -> str:
    parts: list[str] = []
    if soup.title and soup.title.string:
        parts.append(soup.title.string)

    description = soup.find("meta", attrs={"name": re.compile(r"description", re.IGNORECASE)})
    if description and description.attrs.get("content"):
        parts.append(_coerce_text(description.attrs.get("content")))

    for tag in soup.find_all(["h1", "h2", "p"], limit=35):
        text = tag.get_text(" ", strip=True)
        if text:
            parts.append(text)

    return WHITESPACE_RE.sub(" ", " ".join(parts)).strip()


def detect_language_from_html(
    soup: BeautifulSoup,
    response_text: str = "",
    min_confidence: float = 0.70,
) -> Tuple[Optional[str], str, float]:
    declared = _extract_declared_language_from_soup(soup)
    if declared:
        return declared, "declared", 1.0

    merged_text = " ".join(
        filter(
            None,
            [
                _extract_text_from_soup(soup),
                _coerce_text(response_text)[:12000],
            ],
        )
    )
    detected, confidence = detect_language_from_text(merged_text, min_confidence=min_confidence)
    if detected:
        return detected, "text", confidence

    return None, "unknown", confidence
