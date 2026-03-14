"""Regex patterns and constants for recipe verification and filtering."""

from __future__ import annotations

import re

NON_RECIPE_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico",
    ".pdf", ".zip", ".mp4", ".webm", ".mov", ".avi", ".mkv",
)

NON_RECIPE_PATH_HINTS = (
    "/wp-content/uploads/",
    "/wp-json/",
    "/category/",
    "/tag/",
    "/author/",
    "/feed/",
)

TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}

LISTICLE_REGEX = re.compile(
    r"\b(top|best)\b.*\b(recipes|meals|dishes|ideas|desserts|appetizers|snacks|soups|salads|sides|cocktails|drinks)\b",
    re.IGNORECASE,
)

NUMBERED_COLLECTION_REGEX = re.compile(
    r"^\s*\d{1,3}\b.*\b(recipes|meals|dishes|ideas|desserts|appetizers|snacks|soups|salads|sides|cocktails|drinks)\b",
    re.IGNORECASE,
)

LISTICLE_TITLE_REGEX = re.compile(
    r"(\b(top|best)\b|\b\d{1,3}\b).*\b(recipes|meals|dishes|ideas|desserts|appetizers|snacks|soups|salads|sides|cocktails|drinks)\b",
    re.IGNORECASE,
)

NON_RECIPE_DIGEST_REGEX = re.compile(
    r"\b("
    r"friday\s*finds?|"
    r"sunday\s*stuff|"
    r"monthly\s*report|"
    r"coming\s*soon|"
    r"adventures?|"
    r"food\s*guide|"
    r"what\s*and\s*where\s*to\s*eat|"
    r"totoro\s*week"
    r")\b",
    re.IGNORECASE,
)

HOW_TO_COOK_REGEX = re.compile(
    r"^how\s+to\s+(cook|make)\b",
    re.IGNORECASE,
)

RECIPE_CLASS_PATTERN = re.compile(
    r"(wp-recipe-maker|tasty-recipes|mv-create-card|recipe-card)"
)

BAD_KEYWORDS = [
    "roundup", "collection", "guide", "review",
    "giveaway", "shop", "store", "product",
]
