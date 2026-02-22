from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from cookdex.webui_server.scheduler import SchedulerService


def _make_service(tmp_path):
    """Create a minimal SchedulerService without starting it."""
    from unittest.mock import MagicMock
    from cookdex.webui_server.scheduler import SchedulerService

    svc = SchedulerService.__new__(SchedulerService)
    svc.state = MagicMock()
    svc.runner = MagicMock()
    svc.registry = MagicMock()
    svc.dispatcher_id = "test-dispatcher"

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    svc.scheduler = BackgroundScheduler(
        timezone="UTC",
        jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{tmp_path}/sched.db")},
    )
    return svc


class TestBuildTrigger:
    def test_interval_returns_interval_trigger(self, tmp_path):
        svc = _make_service(tmp_path)
        trigger = svc._build_trigger("interval", {"seconds": 3600})
        assert isinstance(trigger, IntervalTrigger)

    def test_interval_zero_seconds_raises(self, tmp_path):
        svc = _make_service(tmp_path)
        with pytest.raises(ValueError, match="positive"):
            svc._build_trigger("interval", {"seconds": 0})

    def test_interval_negative_seconds_raises(self, tmp_path):
        svc = _make_service(tmp_path)
        with pytest.raises(ValueError, match="positive"):
            svc._build_trigger("interval", {"seconds": -60})

    def test_once_full_iso_returns_date_trigger(self, tmp_path):
        svc = _make_service(tmp_path)
        run_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        trigger = svc._build_trigger("once", {"run_at": run_at})
        assert isinstance(trigger, DateTrigger)

    def test_once_short_format_normalized(self, tmp_path):
        """datetime-local inputs produce "YYYY-MM-DDTHH:MM" without seconds."""
        svc = _make_service(tmp_path)
        run_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        assert len(run_at) == 16  # confirm short format
        trigger = svc._build_trigger("once", {"run_at": run_at})
        assert isinstance(trigger, DateTrigger)

    def test_once_missing_run_at_raises(self, tmp_path):
        svc = _make_service(tmp_path)
        with pytest.raises(ValueError, match="run_at"):
            svc._build_trigger("once", {})

    def test_once_empty_run_at_raises(self, tmp_path):
        svc = _make_service(tmp_path)
        with pytest.raises(ValueError, match="run_at"):
            svc._build_trigger("once", {"run_at": ""})

    def test_unsupported_kind_raises(self, tmp_path):
        svc = _make_service(tmp_path)
        with pytest.raises(ValueError, match="Unsupported"):
            svc._build_trigger("cron", {"expression": "* * * * *"})


class TestRestoreFromDb:
    def test_bad_schedule_does_not_crash_restore(self, tmp_path):
        """A schedule with invalid data should be skipped, not crash the server."""
        svc = _make_service(tmp_path)
        svc.state.list_schedules.return_value = [
            {
                "schedule_id": "bad-id",
                "name": "Broken",
                "task_id": "tag-categorize",
                "schedule_kind": "once",
                "schedule_data": {"run_at": ""},  # invalid — empty run_at
                "options": {},
                "enabled": True,
            }
        ]
        svc.scheduler.start()
        try:
            # Should complete without raising
            svc._restore_from_db()
        finally:
            svc.scheduler.shutdown(wait=False)
