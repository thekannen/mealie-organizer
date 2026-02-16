from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ParserRunSnapshot:
    run_id: str | None = None
    status: str = "idle"
    started_at: str | None = None
    finished_at: str | None = None
    summary: dict[str, Any] | None = None
    error: str | None = None
    dry_run: bool = True


class ParserRunController:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active = False
        self._snapshot = ParserRunSnapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._snapshot)

    def start_dry_run(self) -> dict[str, Any] | None:
        with self._lock:
            if self._active:
                return None
            self._active = True
            self._snapshot = ParserRunSnapshot(
                run_id=str(uuid4()),
                status="running",
                started_at=utc_now_iso(),
                finished_at=None,
                summary=None,
                error=None,
                dry_run=True,
            )
            return asdict(self._snapshot)

    def complete_success(self, summary: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._active = False
            self._snapshot.status = "succeeded"
            self._snapshot.finished_at = utc_now_iso()
            self._snapshot.summary = summary
            self._snapshot.error = None
            return asdict(self._snapshot)

    def complete_failure(self, error: str) -> dict[str, Any]:
        with self._lock:
            self._active = False
            self._snapshot.status = "failed"
            self._snapshot.finished_at = utc_now_iso()
            self._snapshot.summary = None
            self._snapshot.error = error
            return asdict(self._snapshot)

