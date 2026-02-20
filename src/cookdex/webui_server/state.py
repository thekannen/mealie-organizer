from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Iterator


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class StateStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._write_lock = Lock()

    @contextmanager
    def _connect(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30,
            check_same_thread=False,
        )
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

    def initialize(self, task_ids: list[str]) -> None:
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                      username TEXT PRIMARY KEY,
                      password_hash TEXT NOT NULL,
                      created_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                      token TEXT PRIMARY KEY,
                      username TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      expires_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runs (
                      run_id TEXT PRIMARY KEY,
                      task_id TEXT NOT NULL,
                      status TEXT NOT NULL,
                      options_json TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      started_at TEXT,
                      finished_at TEXT,
                      exit_code INTEGER,
                      error_text TEXT,
                      triggered_by TEXT NOT NULL,
                      schedule_id TEXT,
                      log_path TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS run_logs (
                      run_id TEXT PRIMARY KEY,
                      log_path TEXT NOT NULL,
                      size_bytes INTEGER NOT NULL DEFAULT 0,
                      updated_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schedules (
                      schedule_id TEXT PRIMARY KEY,
                      name TEXT NOT NULL,
                      task_id TEXT NOT NULL,
                      schedule_kind TEXT NOT NULL,
                      schedule_data_json TEXT NOT NULL,
                      options_json TEXT NOT NULL,
                      enabled INTEGER NOT NULL DEFAULT 1,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      last_enqueued_at TEXT
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS task_policies (
                      task_id TEXT PRIMARY KEY,
                      allow_dangerous INTEGER NOT NULL DEFAULT 0,
                      updated_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS secrets (
                      key TEXT PRIMARY KEY,
                      encrypted_value TEXT NOT NULL,
                      updated_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_settings (
                      key TEXT PRIMARY KEY,
                      value_json TEXT NOT NULL,
                      updated_at TEXT NOT NULL
                    );
                    """
                )
                now = utc_now_iso()
                for task_id in task_ids:
                    conn.execute(
                        """
                        INSERT INTO task_policies(task_id, allow_dangerous, updated_at)
                        VALUES(?, 0, ?)
                        ON CONFLICT(task_id) DO NOTHING;
                        """,
                        (task_id, now),
                    )

    def has_users(self) -> bool:
        with self._connect(readonly=True) as conn:
            row = conn.execute("SELECT 1 FROM users LIMIT 1;").fetchone()
            return row is not None

    def count_users(self) -> int:
        with self._connect(readonly=True) as conn:
            row = conn.execute("SELECT COUNT(*) AS value FROM users;").fetchone()
            return int(row["value"]) if row is not None else 0

    def list_users(self) -> list[dict[str, str]]:
        with self._connect(readonly=True) as conn:
            rows = conn.execute(
                "SELECT username, created_at FROM users ORDER BY username ASC;"
            ).fetchall()
        return [{"username": str(row["username"]), "created_at": str(row["created_at"])} for row in rows]

    def user_exists(self, username: str) -> bool:
        with self._connect(readonly=True) as conn:
            row = conn.execute("SELECT 1 FROM users WHERE username = ? LIMIT 1;", (username,)).fetchone()
            return row is not None

    def create_user(self, username: str, password_hash: str) -> bool:
        now = utc_now_iso()
        with self._write_lock:
            with self._connect() as conn:
                row = conn.execute("SELECT 1 FROM users WHERE username = ? LIMIT 1;", (username,)).fetchone()
                if row is not None:
                    return False
                conn.execute(
                    "INSERT INTO users(username, password_hash, created_at) VALUES(?, ?, ?);",
                    (username, password_hash, now),
                )
        return True

    def upsert_user(self, username: str, password_hash: str) -> None:
        now = utc_now_iso()
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO users(username, password_hash, created_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(username) DO UPDATE SET
                      password_hash=excluded.password_hash;
                    """,
                    (username, password_hash, now),
                )

    def update_password(self, username: str, password_hash: str) -> bool:
        with self._write_lock:
            with self._connect() as conn:
                result = conn.execute(
                    "UPDATE users SET password_hash = ? WHERE username = ?;",
                    (password_hash, username),
                )
                return int(result.rowcount or 0) > 0

    def get_password_hash(self, username: str) -> str | None:
        with self._connect(readonly=True) as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE username = ?;", (username,)).fetchone()
            if row is None:
                return None
            return str(row["password_hash"])

    def delete_user(self, username: str) -> bool:
        with self._write_lock:
            with self._connect() as conn:
                # Both deletes are in a single transaction (atomic).
                conn.execute("DELETE FROM sessions WHERE username = ?;", (username,))
                result = conn.execute("DELETE FROM users WHERE username = ?;", (username,))
                return int(result.rowcount or 0) > 0

    def create_session(self, token: str, username: str, expires_at: str) -> None:
        now = utc_now_iso()
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sessions(token, username, created_at, expires_at)
                    VALUES(?, ?, ?, ?);
                    """,
                    (token, username, now, expires_at),
                )

    def get_session(self, token: str) -> dict[str, Any] | None:
        with self._connect(readonly=True) as conn:
            row = conn.execute(
                "SELECT token, username, created_at, expires_at FROM sessions WHERE token = ?;",
                (token,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def delete_session(self, token: str) -> None:
        with self._write_lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM sessions WHERE token = ?;", (token,))

    def purge_expired_sessions(self, now_iso: str) -> None:
        with self._write_lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM sessions WHERE expires_at <= ?;", (now_iso,))

    def create_run(
        self,
        run_id: str,
        task_id: str,
        options: dict[str, Any],
        triggered_by: str,
        schedule_id: str | None,
        log_path: str,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        payload = json.dumps(options, sort_keys=True)
        with self._write_lock:
            with self._connect() as conn:
                # Both inserts are in a single transaction (atomic).
                conn.execute(
                    """
                    INSERT INTO runs(
                      run_id, task_id, status, options_json, created_at, started_at,
                      finished_at, exit_code, error_text, triggered_by, schedule_id, log_path
                    ) VALUES (?, ?, 'queued', ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?);
                    """,
                    (run_id, task_id, payload, now, triggered_by, schedule_id, log_path),
                )
                conn.execute(
                    """
                    INSERT INTO run_logs(run_id, log_path, size_bytes, updated_at)
                    VALUES(?, ?, 0, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                      log_path=excluded.log_path,
                      updated_at=excluded.updated_at;
                    """,
                    (run_id, log_path, now),
                )
        return self.get_run(run_id) or {}

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT run_id, task_id, status, options_json, created_at, started_at, finished_at,
                       exit_code, error_text, triggered_by, schedule_id, log_path
                FROM runs
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect(readonly=True) as conn:
            row = conn.execute(
                """
                SELECT run_id, task_id, status, options_json, created_at, started_at, finished_at,
                       exit_code, error_text, triggered_by, schedule_id, log_path
                FROM runs
                WHERE run_id = ?;
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def update_run_status(
        self,
        run_id: str,
        *,
        status: str,
        started_at: str | None = None,
        finished_at: str | None = None,
        exit_code: int | None = None,
        error_text: str | None = None,
    ) -> None:
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE runs SET
                      status = ?,
                      started_at = COALESCE(?, started_at),
                      finished_at = COALESCE(?, finished_at),
                      exit_code = ?,
                      error_text = ?
                    WHERE run_id = ?;
                    """,
                    (status, started_at, finished_at, exit_code, error_text, run_id),
                )

    def update_run_log_size(self, run_id: str, size_bytes: int) -> None:
        now = utc_now_iso()
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE run_logs SET size_bytes = ?, updated_at = ? WHERE run_id = ?;",
                    (size_bytes, now, run_id),
                )

    def list_task_policies(self) -> dict[str, dict[str, Any]]:
        with self._connect(readonly=True) as conn:
            rows = conn.execute(
                "SELECT task_id, allow_dangerous, updated_at FROM task_policies ORDER BY task_id ASC;"
            ).fetchall()
        payload: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload[str(row["task_id"])] = {
                "allow_dangerous": bool(row["allow_dangerous"]),
                "updated_at": str(row["updated_at"]),
            }
        return payload

    def set_task_policy(self, task_id: str, allow_dangerous: bool) -> None:
        now = utc_now_iso()
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO task_policies(task_id, allow_dangerous, updated_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                      allow_dangerous=excluded.allow_dangerous,
                      updated_at=excluded.updated_at;
                    """,
                    (task_id, 1 if allow_dangerous else 0, now),
                )

    def list_schedules(self) -> list[dict[str, Any]]:
        with self._connect(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT schedule_id, name, task_id, schedule_kind, schedule_data_json, options_json, enabled,
                       created_at, updated_at, last_enqueued_at
                FROM schedules
                ORDER BY created_at DESC;
                """
            ).fetchall()
        schedules: list[dict[str, Any]] = []
        for row in rows:
            schedules.append(
                {
                    "schedule_id": str(row["schedule_id"]),
                    "name": str(row["name"]),
                    "task_id": str(row["task_id"]),
                    "schedule_kind": str(row["schedule_kind"]),
                    "schedule_data": json.loads(str(row["schedule_data_json"]) or "{}"),
                    "options": json.loads(str(row["options_json"]) or "{}"),
                    "enabled": bool(row["enabled"]),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                    "last_enqueued_at": row["last_enqueued_at"],
                }
            )
        return schedules

    def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        with self._connect(readonly=True) as conn:
            row = conn.execute(
                """
                SELECT schedule_id, name, task_id, schedule_kind, schedule_data_json, options_json, enabled,
                       created_at, updated_at, last_enqueued_at
                FROM schedules
                WHERE schedule_id = ?;
                """,
                (schedule_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "schedule_id": str(row["schedule_id"]),
            "name": str(row["name"]),
            "task_id": str(row["task_id"]),
            "schedule_kind": str(row["schedule_kind"]),
            "schedule_data": json.loads(str(row["schedule_data_json"]) or "{}"),
            "options": json.loads(str(row["options_json"]) or "{}"),
            "enabled": bool(row["enabled"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "last_enqueued_at": row["last_enqueued_at"],
        }

    def create_schedule(
        self,
        schedule_id: str,
        name: str,
        task_id: str,
        schedule_kind: str,
        schedule_data: dict[str, Any],
        options: dict[str, Any],
        enabled: bool,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO schedules(
                      schedule_id, name, task_id, schedule_kind, schedule_data_json, options_json, enabled,
                      created_at, updated_at, last_enqueued_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL);
                    """,
                    (
                        schedule_id,
                        name,
                        task_id,
                        schedule_kind,
                        json.dumps(schedule_data, sort_keys=True),
                        json.dumps(options, sort_keys=True),
                        1 if enabled else 0,
                        now,
                        now,
                    ),
                )
        return self.get_schedule(schedule_id) or {}

    def update_schedule(
        self,
        schedule_id: str,
        *,
        name: str,
        task_id: str,
        schedule_kind: str,
        schedule_data: dict[str, Any],
        options: dict[str, Any],
        enabled: bool,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE schedules SET
                      name = ?,
                      task_id = ?,
                      schedule_kind = ?,
                      schedule_data_json = ?,
                      options_json = ?,
                      enabled = ?,
                      updated_at = ?
                    WHERE schedule_id = ?;
                    """,
                    (
                        name,
                        task_id,
                        schedule_kind,
                        json.dumps(schedule_data, sort_keys=True),
                        json.dumps(options, sort_keys=True),
                        1 if enabled else 0,
                        now,
                        schedule_id,
                    ),
                )
        return self.get_schedule(schedule_id) or {}

    def delete_schedule(self, schedule_id: str) -> None:
        with self._write_lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM schedules WHERE schedule_id = ?;", (schedule_id,))

    def touch_schedule_enqueue(self, schedule_id: str) -> None:
        now = utc_now_iso()
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE schedules SET last_enqueued_at = ?, updated_at = ? WHERE schedule_id = ?;",
                    (now, now, schedule_id),
                )

    def list_settings(self) -> dict[str, Any]:
        with self._connect(readonly=True) as conn:
            rows = conn.execute("SELECT key, value_json FROM app_settings ORDER BY key ASC;").fetchall()
        payload: dict[str, Any] = {}
        for row in rows:
            payload[str(row["key"])] = json.loads(str(row["value_json"]))
        return payload

    def set_settings(self, settings: dict[str, Any]) -> None:
        if not settings:
            return
        now = utc_now_iso()
        with self._write_lock:
            with self._connect() as conn:
                for key, value in settings.items():
                    conn.execute(
                        """
                        INSERT INTO app_settings(key, value_json, updated_at)
                        VALUES(?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET
                          value_json=excluded.value_json,
                          updated_at=excluded.updated_at;
                        """,
                        (key, json.dumps(value), now),
                    )

    def delete_setting(self, key: str) -> None:
        with self._write_lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM app_settings WHERE key = ?;", (key,))

    def list_encrypted_secrets(self) -> dict[str, str]:
        with self._connect(readonly=True) as conn:
            rows = conn.execute("SELECT key, encrypted_value FROM secrets ORDER BY key ASC;").fetchall()
        return {str(row["key"]): str(row["encrypted_value"]) for row in rows}

    def set_secret(self, key: str, encrypted_value: str) -> None:
        now = utc_now_iso()
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO secrets(key, encrypted_value, updated_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                      encrypted_value=excluded.encrypted_value,
                      updated_at=excluded.updated_at;
                    """,
                    (key, encrypted_value, now),
                )

    def delete_secret(self, key: str) -> None:
        with self._write_lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM secrets WHERE key = ?;", (key,))

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": str(row["run_id"]),
            "task_id": str(row["task_id"]),
            "status": str(row["status"]),
            "options": json.loads(str(row["options_json"]) or "{}"),
            "created_at": str(row["created_at"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "exit_code": row["exit_code"],
            "error": row["error_text"],
            "triggered_by": str(row["triggered_by"]),
            "schedule_id": row["schedule_id"],
            "log_path": str(row["log_path"]),
        }
