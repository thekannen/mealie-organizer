from __future__ import annotations

import signal
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

from cookdex.webui_server.runner import RunQueueManager
from cookdex.webui_server.tasks import TaskExecution


def _build_manager(*, logs_dir: Path) -> tuple[RunQueueManager, Mock, Mock]:
    state = Mock()
    registry = Mock()
    manager = RunQueueManager(
        state=state,
        registry=registry,
        environment_provider=lambda: {},
        logs_dir=logs_dir,
        max_log_files=50,
    )
    return manager, state, registry


def test_cancel_running_run_terminates_process_group(tmp_path: Path) -> None:
    manager, state, _registry = _build_manager(logs_dir=tmp_path)

    state.get_run.return_value = {"run_id": "run-1", "status": "running"}
    proc = Mock()
    proc.pid = 4321
    proc.poll.return_value = None
    manager._active["run-1"] = proc

    with patch("os.getpgid", return_value=4321, create=True), patch("os.killpg", create=True) as killpg:
        canceled = manager.cancel("run-1")

    assert canceled is True
    killpg.assert_called_once_with(4321, signal.SIGTERM)
    state.update_run_status.assert_called_once()
    kwargs = state.update_run_status.call_args.kwargs
    assert kwargs["status"] == "canceled"
    assert kwargs["error_text"] == "Canceled while running."


def test_worker_loop_marks_failed_when_execute_raises(tmp_path: Path) -> None:
    manager, state, _registry = _build_manager(logs_dir=tmp_path)
    run_id = "run-2"
    log_path = tmp_path / f"{run_id}.log"
    run_record = {"run_id": run_id, "task_id": "data-maintenance", "status": "queued", "log_path": str(log_path)}
    running_record = dict(run_record)
    running_record["status"] = "running"

    calls = {"count": 0}

    def _get_run(_run_id: str):
        calls["count"] += 1
        if calls["count"] == 1:
            return run_record
        return running_record

    state.get_run.side_effect = _get_run
    manager._execute_run = Mock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

    worker = threading.Thread(target=manager._worker_loop, daemon=True)
    worker.start()
    manager._queue.put(run_id)
    time.sleep(0.2)
    manager._stop.set()
    manager._queue.put("")
    worker.join(timeout=2)

    assert state.update_run_status.call_count >= 1
    assert any(
        c.args and c.args[0] == run_id
        and c.kwargs.get("status") == "failed"
        and "Runner internal error" in str(c.kwargs.get("error_text"))
        for c in state.update_run_status.call_args_list
    )
    assert log_path.exists()


def test_execute_run_starts_subprocess_in_new_session(tmp_path: Path) -> None:
    manager, state, registry = _build_manager(logs_dir=tmp_path)
    run_id = "run-3"
    run_record = {"run_id": run_id, "task_id": "ingredient-parse", "options": {}, "log_path": str(tmp_path / "r3.log")}

    registry.build_execution.return_value = TaskExecution(
        command=["python", "-m", "cookdex.ingredient_parser", "--max", "1"],
        env={},
        dangerous_requested=False,
    )
    state.get_run.return_value = {"status": "running"}

    proc = Mock()
    proc.stdout = ["line-1\n", "line-2\n"]
    proc.wait.return_value = 0

    with patch("subprocess.Popen", return_value=proc) as popen:
        manager._execute_run(run_id, run_record)

    assert popen.call_count == 1
    assert popen.call_args.kwargs.get("start_new_session") is True
    status_calls = [c.kwargs.get("status") for c in state.update_run_status.call_args_list]
    assert "running" in status_calls
    assert "succeeded" in status_calls
    state.update_run_log_size.assert_called()
