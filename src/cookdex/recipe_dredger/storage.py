"""SQLite-backed persistent state for the recipe dredger.

Stores imported/rejected URLs, retry queue, sitemap cache, and the
user-managed sites list.  Uses the same state.db as the rest of CookDex.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from ..config import REPO_ROOT
from .url_utils import canonicalize_url

_DEFAULT_DB_PATH = REPO_ROOT / "cache" / "webui" / "state.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


class DredgerStore:
    """All dredger persistent state backed by SQLite."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _DEFAULT_DB_PATH
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with _connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS dredger_imported (
                    url TEXT PRIMARY KEY,
                    imported_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dredger_rejects (
                    url TEXT PRIMARY KEY,
                    reason TEXT DEFAULT '',
                    rejected_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dredger_retry_queue (
                    url TEXT PRIMARY KEY,
                    reason TEXT DEFAULT '',
                    attempts INTEGER DEFAULT 0,
                    last_attempt TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dredger_sitemap_cache (
                    site_url TEXT PRIMARY KEY,
                    sitemap_url TEXT NOT NULL,
                    urls_json TEXT NOT NULL,
                    cached_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dredger_sites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    label TEXT DEFAULT '',
                    region TEXT DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    added_at TEXT NOT NULL
                );
            """)

    # ------------------------------------------------------------------
    # Imported URLs
    # ------------------------------------------------------------------

    def is_imported(self, url: str) -> bool:
        key = canonicalize_url(url) or url
        with _connect(self.db_path, readonly=True) as conn:
            row = conn.execute("SELECT 1 FROM dredger_imported WHERE url = ?", (key,)).fetchone()
            return row is not None

    def add_imported(self, url: str) -> None:
        key = canonicalize_url(url) or url
        with _connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO dredger_imported (url, imported_at) VALUES (?, ?)",
                (key, _utc_now()),
            )
            conn.execute("DELETE FROM dredger_retry_queue WHERE url = ?", (key,))

    def imported_count(self) -> int:
        with _connect(self.db_path, readonly=True) as conn:
            row = conn.execute("SELECT COUNT(*) FROM dredger_imported").fetchone()
            return row[0] if row else 0

    # ------------------------------------------------------------------
    # Rejected URLs
    # ------------------------------------------------------------------

    def is_rejected(self, url: str) -> bool:
        key = canonicalize_url(url) or url
        with _connect(self.db_path, readonly=True) as conn:
            row = conn.execute("SELECT 1 FROM dredger_rejects WHERE url = ?", (key,)).fetchone()
            return row is not None

    def add_reject(self, url: str, reason: str = "") -> None:
        key = canonicalize_url(url) or url
        with _connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO dredger_rejects (url, reason, rejected_at) VALUES (?, ?, ?)",
                (key, reason, _utc_now()),
            )
            conn.execute("DELETE FROM dredger_retry_queue WHERE url = ?", (key,))

    def rejected_count(self) -> int:
        with _connect(self.db_path, readonly=True) as conn:
            row = conn.execute("SELECT COUNT(*) FROM dredger_rejects").fetchone()
            return row[0] if row else 0

    # ------------------------------------------------------------------
    # Retry queue
    # ------------------------------------------------------------------

    def is_in_retry(self, url: str) -> bool:
        key = canonicalize_url(url) or url
        with _connect(self.db_path, readonly=True) as conn:
            row = conn.execute("SELECT 1 FROM dredger_retry_queue WHERE url = ?", (key,)).fetchone()
            return row is not None

    def is_known(self, url: str) -> bool:
        """Return True if URL is already imported, rejected, or in retry queue."""
        key = canonicalize_url(url) or url
        with _connect(self.db_path, readonly=True) as conn:
            for table in ("dredger_imported", "dredger_rejects", "dredger_retry_queue"):
                row = conn.execute(f"SELECT 1 FROM {table} WHERE url = ?", (key,)).fetchone()
                if row is not None:
                    return True
            return False

    def add_retry(self, url: str, reason: str = "", increment: bool = False) -> int:
        """Add or update a retry entry. Returns the new attempt count."""
        key = canonicalize_url(url) or url
        with _connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT attempts FROM dredger_retry_queue WHERE url = ?", (key,)
            ).fetchone()
            attempts = (existing["attempts"] if existing else 0) + (1 if increment else 0)
            conn.execute(
                "INSERT OR REPLACE INTO dredger_retry_queue (url, reason, attempts, last_attempt) VALUES (?, ?, ?, ?)",
                (key, reason, attempts, _utc_now()),
            )
            return attempts

    def remove_retry(self, url: str) -> None:
        key = canonicalize_url(url) or url
        with _connect(self.db_path) as conn:
            conn.execute("DELETE FROM dredger_retry_queue WHERE url = ?", (key,))

    def get_retry_queue(self) -> list[dict[str, Any]]:
        with _connect(self.db_path, readonly=True) as conn:
            rows = conn.execute(
                "SELECT url, reason, attempts, last_attempt FROM dredger_retry_queue"
            ).fetchall()
            return [dict(row) for row in rows]

    def retry_count(self) -> int:
        with _connect(self.db_path, readonly=True) as conn:
            row = conn.execute("SELECT COUNT(*) FROM dredger_retry_queue").fetchone()
            return row[0] if row else 0

    # ------------------------------------------------------------------
    # Sitemap cache
    # ------------------------------------------------------------------

    def get_cached_sitemap(self, site_url: str, cache_expiry_days: int = 7) -> dict[str, Any] | None:
        with _connect(self.db_path, readonly=True) as conn:
            row = conn.execute(
                "SELECT sitemap_url, urls_json, cached_at FROM dredger_sitemap_cache WHERE site_url = ?",
                (site_url,),
            ).fetchone()
            if row is None:
                return None

            cached_at = datetime.fromisoformat(row["cached_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - cached_at > timedelta(days=cache_expiry_days):
                return None

            return {
                "sitemap_url": row["sitemap_url"],
                "urls": json.loads(row["urls_json"]),
                "cached_at": row["cached_at"],
            }

    def cache_sitemap(self, site_url: str, sitemap_url: str, urls: list[str]) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO dredger_sitemap_cache (site_url, sitemap_url, urls_json, cached_at) VALUES (?, ?, ?, ?)",
                (site_url, sitemap_url, json.dumps(urls), _utc_now()),
            )

    # ------------------------------------------------------------------
    # Sites management
    # ------------------------------------------------------------------

    def get_all_sites(self) -> list[dict[str, Any]]:
        with _connect(self.db_path, readonly=True) as conn:
            rows = conn.execute(
                "SELECT id, url, label, region, enabled, added_at FROM dredger_sites ORDER BY region, url"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_enabled_sites(self) -> list[str]:
        with _connect(self.db_path, readonly=True) as conn:
            rows = conn.execute(
                "SELECT url FROM dredger_sites WHERE enabled = 1 ORDER BY region, url"
            ).fetchall()
            return [row["url"] for row in rows]

    def sites_count(self) -> int:
        with _connect(self.db_path, readonly=True) as conn:
            row = conn.execute("SELECT COUNT(*) FROM dredger_sites").fetchone()
            return row[0] if row else 0

    def add_site(self, url: str, label: str = "", region: str = "") -> int:
        """Add a site. Returns the new row id. Raises sqlite3.IntegrityError on duplicate."""
        normalized = url.rstrip("/")
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO dredger_sites (url, label, region, enabled, added_at) VALUES (?, ?, ?, 1, ?)",
                (normalized, label, region, _utc_now()),
            )
            return cursor.lastrowid or 0

    def update_site(self, site_id: int, url: str | None = None, label: str | None = None,
                    region: str | None = None, enabled: bool | None = None) -> bool:
        """Update a site. Returns True if a row was changed."""
        fields: list[str] = []
        values: list[Any] = []
        if url is not None:
            fields.append("url = ?")
            values.append(url.rstrip("/"))
        if label is not None:
            fields.append("label = ?")
            values.append(label)
        if region is not None:
            fields.append("region = ?")
            values.append(region)
        if enabled is not None:
            fields.append("enabled = ?")
            values.append(1 if enabled else 0)
        if not fields:
            return False
        values.append(site_id)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                f"UPDATE dredger_sites SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            return cursor.rowcount > 0

    def delete_site(self, site_id: int) -> bool:
        with _connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM dredger_sites WHERE id = ?", (site_id,))
            return cursor.rowcount > 0

    def seed_defaults(self, defaults: list[dict[str, str]], force: bool = False) -> int:
        """Insert default sites. Returns number inserted.

        If force=True, clears the table first. Otherwise only seeds when empty.
        """
        with _connect(self.db_path) as conn:
            if force:
                conn.execute("DELETE FROM dredger_sites")
            else:
                count = conn.execute("SELECT COUNT(*) FROM dredger_sites").fetchone()[0]
                if count > 0:
                    return 0

            now = _utc_now()
            inserted = 0
            for entry in defaults:
                url = entry.get("url", "").rstrip("/")
                if not url:
                    continue
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO dredger_sites (url, label, region, enabled, added_at) VALUES (?, ?, ?, 1, ?)",
                        (url, entry.get("label", ""), entry.get("region", ""), now),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass
            return inserted
