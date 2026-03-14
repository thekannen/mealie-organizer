"""Shared taxonomy store — reads/writes taxonomy collections from state.db.

CLI modules and the web UI both use this to access taxonomy data.
On first access, seeds empty collections from legacy JSON files if present.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import REPO_ROOT

_DEFAULT_DB_PATH = REPO_ROOT / "cache" / "webui" / "state.db"
_TAXONOMY_DIR = REPO_ROOT / "configs" / "taxonomy"

COLLECTION_FILES: dict[str, str] = {
    "categories": "categories.json",
    "tags": "tags.json",
    "cookbooks": "cookbooks.json",
    "labels": "labels.json",
    "tools": "tools.json",
    "units_aliases": "units_aliases.json",
}


@contextmanager
def _connect(db_path: Path | None = None, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    path = db_path or _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    try:
        yield conn
        if not readonly:
            conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taxonomy (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          collection TEXT NOT NULL,
          name TEXT NOT NULL,
          data_json TEXT NOT NULL DEFAULT '{}',
          position INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL
        );
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_taxonomy_collection_name
        ON taxonomy(collection, name);
    """)


def read_collection(collection: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    """Read all entries for a taxonomy collection from state.db.

    Falls back to the legacy JSON file if the DB collection is empty
    (auto-seeds on first read).
    """
    with _connect(db_path, readonly=True) as conn:
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT name, data_json FROM taxonomy WHERE collection = ? ORDER BY position, id;",
            (collection,),
        ).fetchall()

    if rows:
        result: list[dict[str, Any]] = []
        for row in rows:
            entry = json.loads(row["data_json"])
            entry["name"] = row["name"]
            result.append(entry)
        return result

    # Empty collection — try seeding from legacy JSON file.
    json_file = _TAXONOMY_DIR / COLLECTION_FILES.get(collection, "")
    if not json_file.exists():
        return []
    try:
        raw = json.loads(json_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []

    entries = _normalize(raw)
    if entries:
        write_collection(collection, entries, db_path=db_path)
    return entries


def write_collection(collection: str, entries: list[dict[str, Any]], *, db_path: Path | None = None) -> None:
    """Replace all entries for a taxonomy collection in state.db."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with _connect(db_path) as conn:
        _ensure_table(conn)
        conn.execute("DELETE FROM taxonomy WHERE collection = ?;", (collection,))
        for pos, entry in enumerate(entries):
            name = entry.get("name", "")
            data = {k: v for k, v in entry.items() if k != "name"}
            conn.execute(
                "INSERT INTO taxonomy(collection, name, data_json, position, updated_at) VALUES(?, ?, ?, ?, ?);",
                (collection, name, json.dumps(data, ensure_ascii=False), pos, now),
            )


def _normalize(raw: list) -> list[dict[str, Any]]:
    """Normalize raw JSON entries: strings become {\"name\": str}."""
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            result.append({"name": item})
        elif isinstance(item, dict) and item.get("name"):
            result.append(item)
    return result
