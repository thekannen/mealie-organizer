"""Default curated recipe sites for the dredger.

Loaded from configs/default_sites.json at runtime and seeded into the
dredger_sites table on first use.  Managed from Settings > Recipe Sources UI.
"""

from __future__ import annotations

import json
from pathlib import Path

_SITES_JSON = Path(__file__).resolve().parents[3] / "configs" / "default_sites.json"


def load_default_sites() -> list[dict[str, str]]:
    """Load default sites from the bundled JSON file."""
    if not _SITES_JSON.is_file():
        return []
    with open(_SITES_JSON, encoding="utf-8") as f:
        return json.load(f)


# Backwards-compatible alias — existing code imports DEFAULT_SITES directly.
DEFAULT_SITES: list[dict[str, str]] = load_default_sites()
