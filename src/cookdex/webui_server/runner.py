from __future__ import annotations

import os
import subprocess
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any, Callable
from uuid import uuid4

from ..config import REPO_ROOT
from .state import StateStore, utc_now_iso
from .tasks import TaskRegistry

ENVProvider = Callable[[], dict[str, str]]


class RunQueueManager:
    def __init__(
        self,
        state: StateStore,
        registry: TaskRegistry,
        environment_provider: ENVProvider,
        logs_dir: Path,
        max_log_files: int = 200,
    ) -> None:
        self.state = state
        self.registry = registry
        self.environment_provider = environment_provider
        self.logs_dir = logs_dir
        self.max_log_files = max_log_files
        self._queue: Queue[str] = Queue()
        self._stop = Event()
        self._thread: Thread | None = None
        self._active: dict[str, subprocess.Popen[str]] = {}
        self._active_lock = Lock()

    def start(self) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._worker_loop, daemon=True, name="webui-runner")
        self._thread.start()

    def stop(self, timeout_seconds: float = 5.0) -> None:
        self._stop.set()
        self._queue.put("")
        if self._thread:
            self._thread.join(timeout_seconds)
            self._thread = None
        with self._active_lock:
            for proc in list(self._active.values()):
                try:
                    proc.terminate()
                except OSError:
                    continue
            self._active.clear()

    def enqueue(
        self,
        task_id: str,
        options: dict[str, Any],
        triggered_by: str,
        schedule_id: str | None = None,
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        log_path = (self.logs_dir / f"{run_id}.log").resolve()
        record = self.state.create_run(
            run_id=run_id,
            task_id=task_id,
            options=options,
            triggered_by=triggered_by,
            schedule_id=schedule_id,
            log_path=str(log_path),
        )
        self._queue.put(run_id)
        return record

    def cancel(self, run_id: str) -> bool:
        record = self.state.get_run(run_id)
        if record is None:
            return False
        status = str(record.get("status"))
        if status in {"succeeded", "failed", "canceled"}:
            return False

        # Hold the active lock across both the status check and the
        # termination to avoid a race with _execute_run finishing.
        with self._active_lock:
            if status == "queued":
                self.state.update_run_status(
                    run_id,
                    status="canceled",
                    finished_at=utc_now_iso(),
                    exit_code=None,
                    error_text="Canceled before execution.",
                )
                return True

            proc = self._active.get(run_id)
            if proc is not None:
                try:
                    proc.terminate()
                except OSError:
                    pass

        self.state.update_run_status(
            run_id,
            status="canceled",
            finished_at=utc_now_iso(),
            exit_code=None,
            error_text="Canceled while running.",
        )
        return True

    def read_log(self, run_id: str, max_bytes: int = 200_000) -> str:
        record = self.state.get_run(run_id)
        if record is None:
            raise KeyError(run_id)
        path = Path(str(record["log_path"]))
        if not path.exists():
            return ""
        data = path.read_text(encoding="utf-8", errors="replace")
        if len(data.encode("utf-8")) <= max_bytes:
            return data
        trimmed = data.encode("utf-8")[-max_bytes:].decode("utf-8", errors="replace")
        return trimmed

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                run_id = self._queue.get(timeout=0.5)
            except Empty:
                continue
            if not run_id:
                continue
            run = self.state.get_run(run_id)
            if run is None:
                continue
            if str(run.get("status")) != "queued":
                continue
            self._execute_run(run_id, run)
            self._rotate_logs()

    def _execute_run(self, run_id: str, run: dict[str, Any]) -> None:
        started_at = utc_now_iso()
        self.state.update_run_status(run_id, status="running", started_at=started_at)
        log_path = Path(str(run["log_path"]))
        log_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            execution = self.registry.build_execution(str(run["task_id"]), dict(run.get("options") or {}))
        except (KeyError, ValueError, TypeError) as exc:
            message = f"Task build failed: {exc}"
            log_path.write_text(message + "\n", encoding="utf-8")
            self.state.update_run_status(
                run_id,
                status="failed",
                finished_at=utc_now_iso(),
                exit_code=1,
                error_text=message,
            )
            self.state.update_run_log_size(run_id, log_path.stat().st_size)
            return

        env = os.environ.copy()
        env.update(self.environment_provider())
        env.update(execution.env)
        command = execution.command

        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write(f"$ {' '.join(command)}\n")
            log_file.flush()
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(REPO_ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except FileNotFoundError as exc:
                message = f"Failed to start process: {exc}"
                log_file.write(message + "\n")
                self.state.update_run_status(
                    run_id,
                    status="failed",
                    finished_at=utc_now_iso(),
                    exit_code=1,
                    error_text=message,
                )
                self.state.update_run_log_size(run_id, log_path.stat().st_size)
                return

            with self._active_lock:
                self._active[run_id] = process

            try:
                if process.stdout is not None:
                    for line in process.stdout:
                        log_file.write(line)
                        log_file.flush()
                exit_code = process.wait()
            finally:
                with self._active_lock:
                    self._active.pop(run_id, None)

            current_run = self.state.get_run(run_id)
            if current_run and str(current_run.get("status")) == "canceled":
                self.state.update_run_log_size(run_id, log_path.stat().st_size)
                return

            if exit_code == 0:
                self.state.update_run_status(
                    run_id,
                    status="succeeded",
                    finished_at=utc_now_iso(),
                    exit_code=0,
                    error_text=None,
                )
            else:
                self.state.update_run_status(
                    run_id,
                    status="failed",
                    finished_at=utc_now_iso(),
                    exit_code=exit_code,
                    error_text=f"Process exited with code {exit_code}.",
                )
            self.state.update_run_log_size(run_id, log_path.stat().st_size)

    def _rotate_logs(self) -> None:
        if self.max_log_files <= 0:
            return
        try:
            log_files = sorted(self.logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)
        except OSError:
            return
        excess = len(log_files) - self.max_log_files
        for path in log_files[:excess]:
            try:
                path.unlink()
            except OSError:
                continue
