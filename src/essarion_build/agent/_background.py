"""Background task manager — run shell commands in the background while the
agent keeps working.

Use case: the agent wants to install dependencies (`pip install -e .`),
spin up a dev server (`npm run dev`), or kick off a long test suite while
continuing to plan + draft the next change. Tasks run in parallel; the
agent (and the human) can poll their status, tail recent output, wait for
completion, or kill them.

Architecture:

- Each task is a `subprocess.Popen` whose stdout/stderr are drained by
  daemon threads into a bounded ring buffer (so a chatty process can't
  exhaust RAM).
- A `TaskManager` owns a registry of tasks, indexed by short hex id.
- Notifications: when a task finishes, an event is pushed to an internal
  queue. The REPL flushes these at the top of each prompt so the user
  sees `[bg] task abc done (exit 0)` between turns.

Lifetime: tasks die with the REPL by default (`shutdown()` kills the
process group). The user can explicitly `--detach` a task to let it
survive — useful for dev servers — but that's an opt-in.
"""

from __future__ import annotations

import os
import secrets
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque

from pydantic import BaseModel, Field


# How much stdout/stderr we keep per task. Enough to debug a failure;
# bounded so a verbose process can't OOM the agent.
_MAX_TAIL_LINES = 500


class BackgroundTask(BaseModel):
    """One background command and its current state."""

    id: str
    name: str
    cmd: str
    cwd: str
    status: str = "running"  # "running" | "done" | "failed" | "killed"
    pid: int | None = None
    exit_code: int | None = None
    started_at: float
    finished_at: float | None = None
    detached: bool = False
    notified: bool = False  # True once we've shown the "done" notice
    # Lists, not deque, because pydantic serializes them cleanly. We cap on
    # write inside the reader thread.
    stdout_tail: list[str] = Field(default_factory=list)
    stderr_tail: list[str] = Field(default_factory=list)

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def elapsed_seconds(self) -> float:
        end = self.finished_at or time.time()
        return max(0.0, end - self.started_at)


def _read_into(stream, tail: list[str], lock: threading.Lock) -> None:
    """Reader thread: pump `stream` into the task's tail list."""
    try:
        for line in iter(stream.readline, ""):
            line = line.rstrip("\n")
            with lock:
                tail.append(line)
                while len(tail) > _MAX_TAIL_LINES:
                    tail.pop(0)
    except (ValueError, OSError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


class TaskManager:
    """Owns the background-task registry and the OS process handles.

    One TaskManager is created per REPL session. The agent and the slash
    commands share it.
    """

    def __init__(self, cwd: str | Path) -> None:
        self._cwd = str(Path(cwd).resolve())
        self._tasks: dict[str, BackgroundTask] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._locks: dict[str, threading.Lock] = {}
        # Notification queue for "task X done" events the UI hasn't shown yet.
        self._pending_notices: Deque[str] = deque()
        self._notice_lock = threading.Lock()

    # ---------- mutators ----------

    def start(
        self,
        cmd: str,
        *,
        name: str | None = None,
        cwd: str | Path | None = None,
        detached: bool = False,
        env: dict[str, str] | None = None,
    ) -> BackgroundTask:
        """Spawn a background process running `cmd`. Returns the task record.

        `cwd`     — defaults to the manager's root (usually the project root)
        `name`    — short label; defaults to a truncated `cmd`
        `detached` — process keeps running after manager shutdown
        `env`     — extra env vars to merge into the child's environment
        """
        task_id = secrets.token_hex(3)
        # Avoid id collisions in the rare case the random tokens repeat.
        while task_id in self._tasks:
            task_id = secrets.token_hex(3)
        run_cwd = str(Path(cwd).resolve()) if cwd else self._cwd
        merged_env: dict[str, str] | None = None
        if env:
            merged_env = {**os.environ, **env}

        # Use a process group so we can kill the child + its descendants
        # together (think `npm run dev` that spawns `node`).
        popen_kwargs: dict = dict(
            cwd=run_cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=merged_env,
        )
        if sys.platform != "win32":
            popen_kwargs["preexec_fn"] = os.setsid

        try:
            proc = subprocess.Popen(shlex.split(cmd), **popen_kwargs)
        except FileNotFoundError as e:
            task = BackgroundTask(
                id=task_id,
                name=name or cmd[:60],
                cmd=cmd,
                cwd=run_cwd,
                status="failed",
                exit_code=127,
                started_at=time.time(),
                finished_at=time.time(),
                detached=detached,
                stderr_tail=[f"command not found: {e}"],
            )
            self._tasks[task_id] = task
            self._pending_notices.append(task_id)
            return task

        task = BackgroundTask(
            id=task_id,
            name=name or cmd[:60],
            cmd=cmd,
            cwd=run_cwd,
            status="running",
            pid=proc.pid,
            started_at=time.time(),
            detached=detached,
        )
        self._tasks[task_id] = task
        self._procs[task_id] = proc
        lock = threading.Lock()
        self._locks[task_id] = lock

        for stream, tail in [(proc.stdout, task.stdout_tail), (proc.stderr, task.stderr_tail)]:
            t = threading.Thread(target=_read_into, args=(stream, tail, lock), daemon=True)
            t.start()
        return task

    def kill(self, task_id: str) -> BackgroundTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        proc = self._procs.get(task_id)
        if proc and task.is_running:
            self._terminate(proc)
            task.status = "killed"
            task.exit_code = proc.returncode
            task.finished_at = time.time()
            with self._notice_lock:
                self._pending_notices.append(task_id)
        return task

    def _terminate(self, proc: subprocess.Popen) -> None:
        """Try SIGTERM on the process group, then SIGKILL after a short grace."""
        if proc.poll() is not None:
            return
        if sys.platform == "win32":
            proc.terminate()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                proc.kill()
            else:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

    def wait(self, task_id: str, *, timeout: float | None = None) -> BackgroundTask:
        """Block until the task finishes or `timeout` seconds elapse."""
        task = self._tasks.get(task_id)
        proc = self._procs.get(task_id)
        if task is None:
            raise KeyError(task_id)
        if proc is None or not task.is_running:
            return task
        try:
            rc = proc.wait(timeout=timeout)
            task.exit_code = rc
            task.finished_at = time.time()
            task.status = "done" if rc == 0 else "failed"
            with self._notice_lock:
                self._pending_notices.append(task_id)
        except subprocess.TimeoutExpired:
            pass
        return task

    def clear_finished(self) -> int:
        """Remove finished/killed tasks from the registry. Returns count cleared."""
        to_drop = [tid for tid, t in self._tasks.items() if not t.is_running]
        for tid in to_drop:
            self._tasks.pop(tid, None)
            self._procs.pop(tid, None)
            self._locks.pop(tid, None)
        return len(to_drop)

    def shutdown(self) -> None:
        """Called at REPL exit. Kills every non-detached running task."""
        for tid, task in list(self._tasks.items()):
            if task.is_running and not task.detached:
                try:
                    self.kill(tid)
                except KeyError:
                    pass

    # ---------- read-only / polling ----------

    def poll(self, task_id: str) -> BackgroundTask:
        """Refresh a task's status. Reads the OS process exit code if it's done."""
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        proc = self._procs.get(task_id)
        if proc is not None and task.is_running:
            rc = proc.poll()
            if rc is not None:
                task.exit_code = rc
                task.finished_at = time.time()
                task.status = "done" if rc == 0 else "failed"
                with self._notice_lock:
                    self._pending_notices.append(task_id)
        return task

    def poll_all(self) -> list[BackgroundTask]:
        return [self.poll(tid) for tid in list(self._tasks)]

    def get(self, task_id: str) -> BackgroundTask:
        return self.poll(task_id)

    def list_tasks(self) -> list[BackgroundTask]:
        return list(self._tasks.values())

    def running_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.is_running)

    def tail(self, task_id: str, *, lines: int = 30) -> str:
        """Recent stdout (+ stderr if any) for a task."""
        task = self.poll(task_id)
        lock = self._locks.get(task_id)
        if lock is not None:
            with lock:
                out_lines = list(task.stdout_tail[-lines:])
                err_lines = list(task.stderr_tail[-lines:])
        else:
            out_lines = list(task.stdout_tail[-lines:])
            err_lines = list(task.stderr_tail[-lines:])
        body = "\n".join(out_lines)
        if err_lines:
            body += "\n(stderr)\n" + "\n".join(err_lines)
        return body

    def drain_notices(self) -> list[BackgroundTask]:
        """Pop and return any completed-task notices the UI hasn't shown.

        Marks each returned task `notified=True` so a task that completes
        and then is re-polled doesn't notify a second time.
        """
        self.poll_all()
        out: list[BackgroundTask] = []
        with self._notice_lock:
            while self._pending_notices:
                tid = self._pending_notices.popleft()
                task = self._tasks.get(tid)
                if task is not None and not task.notified:
                    task.notified = True
                    out.append(task)
        return out


# ---------- module-level singleton for the SDK tool registry ----------

# `_tools.py` registers `start_background` / `check_background` / etc. with
# the SDK's tool registry. Those functions need a TaskManager but the SDK
# tool surface is module-level — so we keep one TaskManager per REPL session
# and stash it here. `bind_manager()` is called once at session start.

_MANAGER: TaskManager | None = None


def bind_manager(cwd: str | Path) -> TaskManager:
    """Create and install the per-session TaskManager. Returns it."""
    global _MANAGER
    _MANAGER = TaskManager(cwd)
    return _MANAGER


def current_manager() -> TaskManager:
    """The active TaskManager for this session. Lazy-creates if missing."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = TaskManager(Path.cwd())
    return _MANAGER


def shutdown_manager() -> None:
    """Kill non-detached tasks and clear the singleton (REPL exit)."""
    global _MANAGER
    if _MANAGER is not None:
        _MANAGER.shutdown()
        _MANAGER = None
