"""Direct Mealie database client for high-throughput bulk operations.

Bypasses the HTTP API for operations that would otherwise require thousands of
individual PATCH/GET calls.  Uses raw parameterized SQL against the same
PostgreSQL (or SQLite) database that Mealie itself uses.

Supported operations
--------------------
  bulk_update_yield     – UPDATE recipe yield fields in a single transaction.
  get_recipe_rows       – SELECT all recipe rows with quality-scoring fields.
  get_group_id          – Resolve the first group's UUID.

Configuration (environment variables)
--------------------------------------
  MEALIE_DB_TYPE          : 'postgres' | 'sqlite'  (unset → DB disabled)

  PostgreSQL direct (PostgreSQL accessible from this host):
    MEALIE_PG_HOST        : hostname / IP  (default: localhost)
    MEALIE_PG_PORT        : port           (default: 5432)
    MEALIE_PG_DB          : database name  (default: mealie_db)
    MEALIE_PG_USER        : user name      (default: mealie__user)
    MEALIE_PG_PASS        : password       (required)

  PostgreSQL via auto SSH tunnel (set when PostgreSQL only listens locally):
    MEALIE_DB_SSH_HOST    : SSH host, e.g. 192.168.99.180
    MEALIE_DB_SSH_USER    : SSH user (default: root)
    MEALIE_DB_SSH_KEY     : path to private key (default: ~/.ssh/cookdex_mealie)
    MEALIE_PG_HOST, _PORT, _DB, _USER, _PASS as above (HOST defaults to localhost)

    When MEALIE_DB_SSH_HOST is set, cookdex automatically opens the tunnel
    before connecting and closes it when done.  No manual ssh command needed.

  SQLite:
    MEALIE_SQLITE_PATH    : absolute path to mealie.db
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def db_type() -> str:
    return _env("MEALIE_DB_TYPE").lower()


def is_db_enabled() -> bool:
    return db_type() in {"postgres", "postgresql", "sqlite"}


# ---------------------------------------------------------------------------
# DBWrapper — thin abstraction over psycopg2 / sqlite3
# ---------------------------------------------------------------------------

class DBWrapper:
    """Low-level connection wrapper for parameterised SQL execution.

    Supports PostgreSQL (%s placeholders) and SQLite (? placeholders) via a
    simple translation layer.  SQL can be written with %s and it will be
    converted for SQLite automatically.
    """

    def __init__(self) -> None:
        dtype = db_type()
        self.conn: Any = None
        self.cursor: Any = None
        self._tunnel: Any = None  # sshtunnel.SSHTunnelForwarder, if opened
        self._type: str = "postgres" if dtype in {"postgres", "postgresql"} else "sqlite"
        self._ph: str = "%s" if self._type == "postgres" else "?"

        if self._type == "postgres":
            try:
                import psycopg2  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError(
                    "psycopg2 is required for PostgreSQL DB access.  "
                    "Install it with:  pip install 'cookdex[db]'  or  pip install psycopg2-binary"
                ) from exc

            pg_host, pg_port = self._resolve_pg_endpoint()
            self.conn = psycopg2.connect(
                host=pg_host,
                port=pg_port,
                dbname=_env("MEALIE_PG_DB", "mealie_db"),
                user=_env("MEALIE_PG_USER", "mealie__user"),
                password=_env("MEALIE_PG_PASS"),
            )
            self.conn.autocommit = False
        else:
            import sqlite3  # stdlib
            path = _env("MEALIE_SQLITE_PATH", "/app/data/mealie.db")
            self.conn = sqlite3.connect(path)
            self.conn.create_function("REGEXP", 2, self._sqlite_regexp)

        self.cursor = self.conn.cursor()

    def _resolve_pg_endpoint(self) -> tuple[str, int]:
        """Return (host, port) for PostgreSQL, opening an SSH tunnel if configured."""
        ssh_host = _env("MEALIE_DB_SSH_HOST")
        pg_host = _env("MEALIE_PG_HOST", "localhost")
        pg_port = int(_env("MEALIE_PG_PORT", "5432"))

        if not ssh_host:
            return pg_host, pg_port

        try:
            from sshtunnel import SSHTunnelForwarder  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "sshtunnel is required for auto SSH tunnel.  "
                "Install it with:  pip install 'cookdex[db]'  or  pip install sshtunnel"
            ) from exc

        ssh_user = _env("MEALIE_DB_SSH_USER", "root")
        ssh_key = _env("MEALIE_DB_SSH_KEY") or os.path.expanduser("~/.ssh/cookdex_mealie")
        ssh_key = os.path.expanduser(ssh_key)
        print(f"[db] Opening SSH tunnel -> {ssh_user}@{ssh_host} -> {pg_host}:{pg_port}", flush=True)
        print(f"[db] SSH key: {ssh_key} (exists={os.path.isfile(ssh_key)})", flush=True)

        tunnel = SSHTunnelForwarder(
            ssh_host,
            ssh_username=ssh_user,
            ssh_pkey=ssh_key,
            remote_bind_address=(pg_host, pg_port),
            allow_agent=False,
            host_pkey_directories=[],
            set_keepalive=10,
        )
        tunnel.start()
        self._tunnel = tunnel
        print(f"[db] Tunnel up on localhost:{tunnel.local_bind_port}", flush=True)
        return "127.0.0.1", tunnel.local_bind_port

    # ------------------------------------------------------------------
    # SQLite helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sqlite_regexp(expr: Optional[str], item: Optional[str]) -> bool:
        if not expr or item is None:
            return False
        try:
            # Translate PostgreSQL word-boundary markers (\y) to Python's \b
            py_expr = expr.replace(r"\y", r"\b")
            return bool(re.compile(py_expr, re.IGNORECASE).search(item))
        except re.error:
            return False

    def _translate_sql(self, sql: str) -> str:
        """Convert %s placeholders and PostgreSQL-isms to SQLite syntax."""
        if self._type != "sqlite":
            return sql
        sql = sql.replace("%s", "?")
        sql = re.sub(r"gen_random_uuid\(\)", "lower(hex(randomblob(16)))", sql)
        sql = sql.replace("::uuid", "")
        # Inline literal patterns:  col ~* 'pattern'
        sql = re.sub(r"([\w.]+)\s*~\*\s*'([^']+)'", r"\1 REGEXP '\2'", sql)
        sql = re.sub(r"([\w.]+)\s*!~\*\s*'([^']+)'", r"NOT (\1 REGEXP '\2')", sql)
        # Parameterized patterns:  col ~* ?  (after %s → ? conversion above)
        sql = re.sub(r"([\w.]+)\s*~\*\s*\?", r"\1 REGEXP ?", sql)
        sql = re.sub(r"([\w.]+)\s*!~\*\s*\?", r"NOT (\1 REGEXP ?)", sql)
        return sql

    # ------------------------------------------------------------------
    # Core execution interface
    # ------------------------------------------------------------------

    @property
    def placeholder(self) -> str:
        return self._ph

    def execute(self, sql: str, params: tuple = ()) -> "DBWrapper":
        self.cursor.execute(self._translate_sql(sql), params)
        return self

    def executemany(self, sql: str, params_seq: list[tuple]) -> "DBWrapper":
        self.cursor.executemany(self._translate_sql(sql), params_seq)
        return self

    def fetchone(self) -> Optional[tuple]:
        return self.cursor.fetchone()

    def fetchall(self) -> list[tuple]:
        return self.cursor.fetchall() or []

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass
        try:
            if self._tunnel is not None:
                self._tunnel.stop()
                self._tunnel = None
        except Exception:
            pass

    def __enter__(self) -> "DBWrapper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()


# ---------------------------------------------------------------------------
# MealieDBClient — high-level operations for cookdex tasks
# ---------------------------------------------------------------------------

class MealieDBClient:
    """High-level Mealie DB client.

    Instantiate and call the needed methods; close() when done.
    Prefer using as a context manager (``with`` block) for automatic cleanup.
    """

    _OPTIONAL_INDEXES: list[tuple[str, str, str]] = [
        ("idx_cdx_tags_group_name", "tags", "group_id, lower(name)"),
        ("idx_cdx_tools_group_name", "tools", "group_id, lower(name)"),
        ("idx_cdx_categories_group_name", "categories", "group_id, lower(name)"),
        ("idx_cdx_tags_slug_group", "tags", "slug, group_id"),
        ("idx_cdx_tools_slug_group", "tools", "slug, group_id"),
        ("idx_cdx_categories_slug_group", "categories", "slug, group_id"),
    ]

    def __init__(self) -> None:
        self._db = DBWrapper()
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create optional performance indexes on Mealie tables (idempotent)."""
        for idx_name, table, columns in self._OPTIONAL_INDEXES:
            try:
                self._db.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({columns})"
                )
            except Exception:
                pass  # Table may not exist yet or columns differ across versions.
        try:
            self._db.commit()
        except Exception:
            pass

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "MealieDBClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self._db.commit()
        else:
            self._db.rollback()
        self.close()

    # ------------------------------------------------------------------
    # Group helpers
    # ------------------------------------------------------------------

    def get_group_id(self) -> Optional[str]:
        """Return the first group's id (UUID as string)."""
        row = self._db.execute("SELECT id FROM groups LIMIT 1").fetchone()
        return str(row[0]) if row else None

    def get_group_id_for_api_key(self, api_user_id: str) -> Optional[str]:
        """Return group_id for the user associated with the API key."""
        row = self._db.execute(
            "SELECT group_id FROM users WHERE id = %s",
            (api_user_id,),
        ).fetchone()
        return str(row[0]) if row else None

    # ------------------------------------------------------------------
    # Recipe quality reads
    # ------------------------------------------------------------------

    def get_recipe_rows(self, group_id: Optional[str] = None) -> list[dict]:
        """Return all recipes with fields needed for gold-medallion scoring.

        Includes tag, category, and tool counts via a single JOIN query —
        orders of magnitude faster than N individual API calls.
        """
        p = self._db.placeholder

        where = f"WHERE r.group_id = {p}" if group_id else ""
        params: tuple = (group_id,) if group_id else ()

        sql = f"""
            SELECT
                r.id,
                r.slug,
                r.name,
                r.description,
                r.recipe_yield,
                r.recipe_yield_quantity,
                r.recipe_servings,
                r.prep_time,
                r.total_time,
                r.perform_time,
                r.cook_time,
                COUNT(DISTINCT rtag.tag_id)  AS tag_count,
                COUNT(DISTINCT rcat.category_id) AS cat_count,
                COUNT(DISTINCT rtool.tool_id) AS tool_count,
                n.calories
            FROM recipes r
            LEFT JOIN recipes_to_tags       rtag  ON r.id = rtag.recipe_id
            LEFT JOIN recipes_to_categories rcat  ON r.id = rcat.recipe_id
            LEFT JOIN recipes_to_tools      rtool ON r.id = rtool.recipe_id
            LEFT JOIN recipe_nutrition      n     ON r.id = n.recipe_id
            {where}
            GROUP BY
                r.id, r.slug, r.name, r.description,
                r.recipe_yield, r.recipe_yield_quantity, r.recipe_servings,
                r.prep_time, r.total_time, r.perform_time, r.cook_time,
                n.calories
        """
        rows = self._db.execute(sql, params).fetchall()
        keys = (
            "id", "slug", "name", "description",
            "recipeYield", "recipeYieldQuantity", "recipeServings",
            "prepTime", "totalTime", "performTime", "cookTime",
            "tag_count", "cat_count", "tool_count",
            "calories",
        )
        return [dict(zip(keys, row)) for row in rows]

    # ------------------------------------------------------------------
    # Yield bulk update
    # ------------------------------------------------------------------

    def bulk_update_yield(
        self,
        updates: list[dict],
        *,
        group_id: Optional[str] = None,
    ) -> tuple[int, int]:
        """Bulk-update recipe yield fields in a single transaction.

        Each ``update`` dict must contain:
            recipe_id       : str (UUID) — preferred
            OR slug + group_id : str

        And at least one of:
            recipe_yield            : str | None
            recipe_yield_quantity   : float | None
            recipe_servings         : float | None

        Returns (applied, failed).
        """
        applied = 0
        failed = 0
        p = self._db.placeholder

        for u in updates:
            try:
                sets: list[str] = []
                vals: list[Any] = []

                if "recipe_yield" in u:
                    sets.append(f"recipe_yield = {p}")
                    vals.append(u["recipe_yield"])
                if "recipe_yield_quantity" in u:
                    sets.append(f"recipe_yield_quantity = {p}")
                    vals.append(u["recipe_yield_quantity"])
                if "recipe_servings" in u:
                    sets.append(f"recipe_servings = {p}")
                    vals.append(u["recipe_servings"])

                if not sets:
                    continue

                if "recipe_id" in u:
                    vals.append(u["recipe_id"])
                    where = f"id = {p}"
                elif "slug" in u and (group_id or "group_id" in u):
                    gid = u.get("group_id") or group_id
                    vals.extend([u["slug"], gid])
                    where = f"slug = {p} AND group_id = {p}"
                else:
                    raise ValueError(f"update missing recipe_id or slug: {u!r}")

                sql = f"UPDATE recipes SET {', '.join(sets)} WHERE {where}"
                self._db.execute(sql, tuple(vals))
                applied += 1

            except Exception as exc:
                print(f"[db_error] yield update failed: {exc}", flush=True)
                failed += 1

        self._db.commit()
        return applied, failed

    # ------------------------------------------------------------------
    # Ensure tag / tool exist (used by future tagger tasks)
    # ------------------------------------------------------------------

    def _slug(self, name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    def lookup_tag_id(self, name: str, group_id: str) -> Optional[str]:
        """Return tag id for an exact name match (case-insensitive), else None."""
        p = self._db.placeholder
        row = self._db.execute(
            f"SELECT id FROM tags WHERE group_id = {p} AND lower(name) = lower({p}) LIMIT 1",
            (group_id, name),
        ).fetchone()
        return str(row[0]) if row else None

    def lookup_tool_id(self, name: str, group_id: str) -> Optional[str]:
        """Return tool id for an exact name match (case-insensitive), else None."""
        p = self._db.placeholder
        row = self._db.execute(
            f"SELECT id FROM tools WHERE group_id = {p} AND lower(name) = lower({p}) LIMIT 1",
            (group_id, name),
        ).fetchone()
        return str(row[0]) if row else None

    def lookup_category_id(self, name: str, group_id: str) -> Optional[str]:
        """Return category id for an exact name match (case-insensitive), else None."""
        p = self._db.placeholder
        row = self._db.execute(
            f"SELECT id FROM categories WHERE group_id = {p} AND lower(name) = lower({p}) LIMIT 1",
            (group_id, name),
        ).fetchone()
        return str(row[0]) if row else None

    def ensure_tag(self, name: str, group_id: str, *, dry_run: bool = True) -> Optional[str]:
        """Return tag id, creating it if necessary (unless dry_run)."""
        slug = self._slug(name)
        p = self._db.placeholder
        row = self._db.execute(
            f"SELECT id FROM tags WHERE slug = {p} AND group_id = {p}", (slug, group_id)
        ).fetchone()
        if row:
            return str(row[0])
        if dry_run:
            return "dry-run-id"
        new_id = str(uuid.uuid4())
        self._db.execute(
            f"INSERT INTO tags (id, group_id, name, slug) VALUES ({p}, {p}, {p}, {p})",
            (new_id, group_id, name, slug),
        )
        return new_id

    def ensure_tool(self, name: str, group_id: str, *, dry_run: bool = True) -> Optional[str]:
        """Return tool id, creating it if necessary (unless dry_run)."""
        slug = self._slug(name)
        p = self._db.placeholder
        row = self._db.execute(
            f"SELECT id FROM tools WHERE slug = {p} AND group_id = {p}", (slug, group_id)
        ).fetchone()
        if row:
            return str(row[0])
        if dry_run:
            return "dry-run-id"
        new_id = str(uuid.uuid4())
        self._db.execute(
            f"INSERT INTO tools (id, group_id, name, slug, on_hand) VALUES ({p}, {p}, {p}, {p}, FALSE)",
            (new_id, group_id, name, slug),
        )
        return new_id

    def link_tag(self, recipe_id: str, tag_id: str, *, dry_run: bool = True) -> None:
        """Associate a tag with a recipe (idempotent)."""
        if dry_run:
            return
        p = self._db.placeholder
        exists = self._db.execute(
            f"SELECT 1 FROM recipes_to_tags WHERE recipe_id = {p} AND tag_id = {p}",
            (recipe_id, tag_id),
        ).fetchone()
        if not exists:
            self._db.execute(
                f"INSERT INTO recipes_to_tags (recipe_id, tag_id) VALUES ({p}, {p})",
                (recipe_id, tag_id),
            )

    # ------------------------------------------------------------------
    # Rule-based tagger queries
    # ------------------------------------------------------------------

    def find_recipe_ids_by_ingredient(
        self,
        group_id: str,
        pattern: str,
        *,
        exclude_pattern: str = "",
        min_matches: int = 1,
    ) -> list[str]:
        """Return recipe IDs where parsed ingredient food names match *pattern*.

        Matching is case-insensitive regex (``~*`` on PostgreSQL; REGEXP on SQLite).
        Patterns may use ``\\y`` for word boundaries (PostgreSQL syntax); these are
        automatically translated to ``\\b`` for SQLite.

        If *exclude_pattern* is given, foods matching it are excluded from the
        matching set first.  *min_matches* sets the minimum number of distinct
        foods that must match before the recipe is included (use 2+ for cuisine
        fingerprinting).
        """
        p = self._db.placeholder
        where_parts = [f"r.group_id = {p}", f"f.name ~* {p}"]
        params: list = [group_id, pattern]
        if exclude_pattern:
            where_parts.append(f"NOT (f.name ~* {p})")
            params.append(exclude_pattern)
        where = " AND ".join(where_parts)
        params.append(min_matches)
        sql = f"""
            SELECT ri.recipe_id
            FROM recipes_ingredients ri
            JOIN recipes r ON r.id = ri.recipe_id
            JOIN ingredient_foods f ON ri.food_id = f.id
            WHERE {where}
            GROUP BY ri.recipe_id
            HAVING COUNT(DISTINCT f.id) >= {p}
        """
        return [str(row[0]) for row in self._db.execute(sql, tuple(params)).fetchall()]

    def find_recipe_ids_by_text(
        self,
        group_id: str,
        pattern: str,
        *,
        match_on: str = "both",
    ) -> list[str]:
        """Return recipe IDs where text fields match *pattern* (case-insensitive).

        ``match_on`` values:
          - ``both`` (default): name OR description
          - ``name``: name only
          - ``description``: description only
        """
        p = self._db.placeholder
        mode = str(match_on or "both").strip().casefold()
        if mode == "name":
            where_text = f"name ~* {p}"
            params: tuple[Any, ...] = (group_id, pattern)
        elif mode == "description":
            where_text = f"description ~* {p}"
            params = (group_id, pattern)
        else:
            where_text = f"(name ~* {p} OR description ~* {p})"
            params = (group_id, pattern, pattern)
        sql = f"""
            SELECT id
            FROM recipes
            WHERE group_id = {p}
              AND {where_text}
        """
        return [str(row[0]) for row in self._db.execute(sql, params).fetchall()]

    def find_recipe_ids_by_instruction(
        self,
        group_id: str,
        pattern: str,
    ) -> list[str]:
        """Return recipe IDs where any instruction step text matches *pattern* (case-insensitive)."""
        p = self._db.placeholder
        sql = f"""
            SELECT DISTINCT inst.recipe_id
            FROM recipe_instructions inst
            JOIN recipes r ON r.id = inst.recipe_id
            WHERE r.group_id = {p}
              AND inst.text ~* {p}
        """
        return [str(row[0]) for row in self._db.execute(sql, (group_id, pattern)).fetchall()]

    def link_tool(self, recipe_id: str, tool_id: str, *, dry_run: bool = True) -> None:
        """Associate a tool with a recipe (idempotent)."""
        if dry_run:
            return
        p = self._db.placeholder
        exists = self._db.execute(
            f"SELECT 1 FROM recipes_to_tools WHERE recipe_id = {p} AND tool_id = {p}",
            (recipe_id, tool_id),
        ).fetchone()
        if not exists:
            self._db.execute(
                f"INSERT INTO recipes_to_tools (recipe_id, tool_id) VALUES ({p}, {p})",
                (recipe_id, tool_id),
            )

    def ensure_category(self, name: str, group_id: str, *, dry_run: bool = True) -> Optional[str]:
        """Return category id, creating it if necessary (unless dry_run)."""
        slug = self._slug(name)
        p = self._db.placeholder
        row = self._db.execute(
            f"SELECT id FROM categories WHERE slug = {p} AND group_id = {p}", (slug, group_id)
        ).fetchone()
        if row:
            return str(row[0])
        if dry_run:
            return "dry-run-id"
        new_id = str(uuid.uuid4())
        self._db.execute(
            f"INSERT INTO categories (id, group_id, name, slug) VALUES ({p}, {p}, {p}, {p})",
            (new_id, group_id, name, slug),
        )
        return new_id

    def link_category(self, recipe_id: str, category_id: str, *, dry_run: bool = True) -> None:
        """Associate a category with a recipe (idempotent)."""
        if dry_run:
            return
        p = self._db.placeholder
        exists = self._db.execute(
            f"SELECT 1 FROM recipes_to_categories WHERE recipe_id = {p} AND category_id = {p}",
            (recipe_id, category_id),
        ).fetchone()
        if not exists:
            self._db.execute(
                f"INSERT INTO recipes_to_categories (recipe_id, category_id) VALUES ({p}, {p})",
                (recipe_id, category_id),
            )


    # ------------------------------------------------------------------
    # Recipe deletion (cascade)
    # ------------------------------------------------------------------

    _FK_TABLES: list[tuple[str, str]] = [
        ("api_extras", "recipee_id"),
        ("group_meal_plans", "recipe_id"),
        ("notes", "recipe_id"),
        ("recipe_assets", "recipe_id"),
        ("recipe_instructions", "recipe_id"),
        ("recipe_nutrition", "recipe_id"),
        ("recipe_settings", "recipe_id"),
        ("recipe_share_tokens", "recipe_id"),
        ("recipes_to_categories", "recipe_id"),
        ("recipes_to_tags", "recipe_id"),
        ("recipes_to_tools", "recipe_id"),
        ("shopping_list_recipe_reference", "recipe_id"),
        ("recipe_comments", "recipe_id"),
        ("recipes_ingredients", "recipe_id"),
        ("recipes_ingredients", "referenced_recipe_id"),
        ("shopping_list_item_recipe_reference", "recipe_id"),
        ("recipe_timeline_events", "recipe_id"),
        ("users_to_recipes", "recipe_id"),
        ("households_to_recipes", "recipe_id"),
    ]

    def delete_recipe(self, slug: str) -> bool:
        """Delete a recipe and all FK references by slug. Returns True if deleted."""
        p = self._db.placeholder
        row = self._db.execute(f"SELECT id FROM recipes WHERE slug = {p}", (slug,)).fetchone()
        if not row:
            return False
        rid = str(row[0])
        for table, col in self._FK_TABLES:
            try:
                self._db.execute(f"DELETE FROM {table} WHERE {col} = {p}", (rid,))
            except Exception:
                self._db.conn.rollback()
        self._db.execute(f"DELETE FROM recipes WHERE id = {p}", (rid,))
        self._db.commit()
        return True


# ---------------------------------------------------------------------------
# Factory / connectivity check
# ---------------------------------------------------------------------------

def resolve_db_client() -> Optional[MealieDBClient]:
    """Return a connected MealieDBClient or None if DB is not configured."""
    if not is_db_enabled():
        return None
    try:
        return MealieDBClient()
    except Exception as exc:
        print(f"[db] Connection failed: {exc}", flush=True)
        return None
