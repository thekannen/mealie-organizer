from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .runner import RunQueueManager
from .state import StateStore
from .tasks import TaskRegistry

_DISPATCHERS: dict[str, Callable[[str], None]] = {}
_DEFAULT_MISFIRE_GRACE_SECONDS = 60
_MISSED_INTERVAL_GRACE_SECONDS = 7 * 24 * 60 * 60
_MISSED_ONCE_GRACE_SECONDS = 30 * 24 * 60 * 60


def _dispatcher_id_for_path(sqlite_path: str) -> str:
    digest = hashlib.sha256(sqlite_path.encode("utf-8")).hexdigest()
    return f"scheduler:{digest}"


def _run_registered_dispatcher(dispatcher_id: str, schedule_id: str) -> None:
    dispatcher = _DISPATCHERS.get(dispatcher_id)
    if dispatcher is None:
        return
    dispatcher(schedule_id)

def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SchedulePayload:
    name: str
    task_id: str
    schedule_kind: str
    schedule_data: dict[str, Any]
    options: dict[str, Any]
    enabled: bool = True


class SchedulerService:
    def __init__(
        self,
        state: StateStore,
        runner: RunQueueManager,
        registry: TaskRegistry,
        sqlite_path: str,
    ) -> None:
        self.state = state
        self.runner = runner
        self.registry = registry
        self.dispatcher_id = _dispatcher_id_for_path(sqlite_path)
        _DISPATCHERS[self.dispatcher_id] = self._fire_schedule
        self.scheduler = BackgroundScheduler(
            timezone="UTC",
            jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{sqlite_path}")},
        )

    def start(self) -> None:
        self._restore_from_db()
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self) -> None:
        _DISPATCHERS.pop(self.dispatcher_id, None)
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def list_schedules(self) -> list[dict[str, Any]]:
        schedules = self.state.list_schedules()
        for item in schedules:
            job = self.scheduler.get_job(item["schedule_id"])
            item["next_run_at"] = _iso(job.next_run_time) if job else None
        return schedules

    def create_schedule(self, payload: SchedulePayload) -> dict[str, Any]:
        schedule_id = str(uuid4())
        record = self.state.create_schedule(
            schedule_id=schedule_id,
            name=payload.name,
            task_id=payload.task_id,
            schedule_kind=payload.schedule_kind,
            schedule_data=payload.schedule_data,
            options=payload.options,
            enabled=payload.enabled,
        )
        self._sync_schedule_job(record)
        return self._with_next_run(record)

    def update_schedule(self, schedule_id: str, payload: SchedulePayload) -> dict[str, Any] | None:
        if self.state.get_schedule(schedule_id) is None:
            return None
        record = self.state.update_schedule(
            schedule_id=schedule_id,
            name=payload.name,
            task_id=payload.task_id,
            schedule_kind=payload.schedule_kind,
            schedule_data=payload.schedule_data,
            options=payload.options,
            enabled=payload.enabled,
        )
        self._sync_schedule_job(record)
        return self._with_next_run(record)

    def delete_schedule(self, schedule_id: str) -> bool:
        existing = self.state.get_schedule(schedule_id)
        if existing is None:
            return False
        try:
            self.scheduler.remove_job(schedule_id, jobstore="default")
        except Exception:
            pass
        self.state.delete_schedule(schedule_id)
        return True

    def _restore_from_db(self) -> None:
        for item in self.state.list_schedules():
            try:
                self._sync_schedule_job(item)
            except Exception as exc:
                logger.warning(
                    "Skipping schedule %s (%s) on restore: %s",
                    item.get("schedule_id"), item.get("name"), exc,
                )

    def _with_next_run(self, record: dict[str, Any]) -> dict[str, Any]:
        job = self.scheduler.get_job(str(record["schedule_id"]))
        payload = dict(record)
        payload["next_run_at"] = _iso(job.next_run_time) if job else None
        return payload

    def _sync_schedule_job(self, record: dict[str, Any]) -> None:
        schedule_id = str(record["schedule_id"])
        if not bool(record["enabled"]):
            try:
                self.scheduler.remove_job(schedule_id, jobstore="default")
            except Exception:
                pass
            return
        schedule_data = dict(record["schedule_data"])
        trigger = self._build_trigger(record["schedule_kind"], schedule_data)
        misfire_grace_time = self._resolve_misfire_grace_time(str(record["schedule_kind"]), schedule_data)
        self.scheduler.add_job(
            func=_run_registered_dispatcher,
            trigger=trigger,
            id=schedule_id,
            replace_existing=True,
            kwargs={"dispatcher_id": self.dispatcher_id, "schedule_id": schedule_id},
            misfire_grace_time=misfire_grace_time,
            coalesce=True,
            max_instances=1,
            jobstore="default",
        )

    def _resolve_misfire_grace_time(self, kind: str, schedule_data: dict[str, Any]) -> int:
        run_if_missed = bool(schedule_data.get("run_if_missed", False))
        if not run_if_missed:
            return _DEFAULT_MISFIRE_GRACE_SECONDS
        if kind == "once":
            return _MISSED_ONCE_GRACE_SECONDS
        return _MISSED_INTERVAL_GRACE_SECONDS

    @staticmethod
    def _parse_dt(val: str | None) -> datetime | None:
        """Parse a datetime string to a timezone-aware UTC datetime.

        Accepts ISO 8601 with Z suffix (from frontend), naive datetime-local
        strings (legacy), and full ISO 8601 with offset.
        """
        if not val:
            return None
        s = str(val).strip()
        if not s:
            return None
        # Pad "YYYY-MM-DDTHH:MM" → "YYYY-MM-DDTHH:MM:00" for fromisoformat
        if len(s) == 16 and "T" in s:
            s = s + ":00"
        # Replace trailing Z with +00:00 for fromisoformat (Python 3.9 compat)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _build_trigger(self, kind: str, schedule_data: dict[str, Any]) -> IntervalTrigger | DateTrigger:
        if kind == "interval":
            seconds = int(schedule_data.get("seconds", 0))
            if seconds <= 0:
                raise ValueError("Interval schedules require positive 'seconds'.")
            start_date = self._parse_dt(schedule_data.get("start_at"))
            end_date = self._parse_dt(schedule_data.get("end_at"))
            return IntervalTrigger(seconds=seconds, timezone="UTC", start_date=start_date, end_date=end_date)
        if kind == "once":
            run_at_raw = str(schedule_data.get("run_at", "")).strip()
            if not run_at_raw:
                raise ValueError("Once schedules require non-empty 'run_at'.")
            run_at = self._parse_dt(run_at_raw)
            return DateTrigger(run_date=run_at)
        raise ValueError(f"Unsupported schedule kind: {kind}")

    def _fire_schedule(self, schedule_id: str) -> None:
        record = self.state.get_schedule(schedule_id)
        if record is None or not bool(record["enabled"]):
            return
        task_id = str(record["task_id"])
        if task_id not in self.registry.task_ids:
            return
        self.runner.enqueue(
            task_id=task_id,
            options=dict(record["options"]),
            triggered_by="scheduler",
            schedule_id=schedule_id,
        )
        self.state.touch_schedule_enqueue(schedule_id)
