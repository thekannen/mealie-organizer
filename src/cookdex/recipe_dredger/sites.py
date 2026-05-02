"""Default curated recipe sites for the dredger.

Loaded from configs/default_sites.json at runtime and seeded into the
dredger_sites table on first use.  Managed from Settings > Recipe Sources UI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_SITES_JSON = Path(__file__).resolve().parents[3] / "configs" / "default_sites.json"


def _candidate_sites_json_paths() -> list[Path]:
    paths: list[Path] = []
    env_root = os.environ.get("COOKDEX_ROOT", "").strip()
    if env_root:
        paths.append(Path(env_root).expanduser().resolve() / "configs" / "default_sites.json")
    paths.append(_SITES_JSON)
    return paths


def load_default_sites() -> list[dict[str, str]]:
    """Load default sites from the bundled JSON file."""
    for path in _candidate_sites_json_paths():
        if path.is_file():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return []


# Backwards-compatible alias — existing code imports DEFAULT_SITES directly.
DEFAULT_SITES: list[dict[str, str]] = load_default_sites()
