"""Tests for the background task manager + tool surface."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from essarion_build.agent._background import (
    TaskManager,
    bind_manager,
    current_manager,
    shutdown_manager,
)


def _wait_status(mgr: TaskManager, task_id: str, statuses: set[str], timeout: float = 5.0) -> None:
    """Poll until the task hits one of `statuses` or `timeout` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = mgr.poll(task_id)
        if task.status in statuses:
            return
        time.sleep(0.05)
    raise AssertionError(
        f"task {task_id} did not reach {statuses} within {timeout}s; "
        f"current status: {mgr.poll(task_id).status}"
    )


def test_start_returns_running_task(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    task = mgr.start("sleep 5")
    try:
        assert task.is_running
        assert task.pid
        assert task.cwd == str(tmp_path)
    finally:
        mgr.shutdown()


def test_short_command_completes_done(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    task = mgr.start("echo hello")
    _wait_status(mgr, task.id, {"done", "failed"})
    task = mgr.poll(task.id)
    assert task.status == "done"
    assert task.exit_code == 0
    # stdout captured
    assert any("hello" in line for line in task.stdout_tail)


def test_failed_command_marked_failed(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    task = mgr.start("bash -c 'exit 7'")
    _wait_status(mgr, task.id, {"done", "failed"})
    task = mgr.poll(task.id)
    assert task.status == "failed"
    assert task.exit_code == 7


def test_command_not_found_creates_failed_task(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    task = mgr.start("definitely-not-a-real-command-xyz")
    assert task.status == "failed"
    assert task.exit_code == 127


def test_kill_terminates_running_task(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    task = mgr.start("sleep 30")
    try:
        assert task.is_running
        time.sleep(0.1)  # let it actually start
        killed = mgr.kill(task.id)
        assert killed.status == "killed"
        assert not killed.is_running
    finally:
        mgr.shutdown()


def test_wait_with_timeout_returns_running_if_not_done(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    task = mgr.start("sleep 5")
    try:
        result = mgr.wait(task.id, timeout=0.2)
        assert result.is_running  # still running after the short timeout
    finally:
        mgr.shutdown()


def test_wait_returns_finished_task(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    task = mgr.start("echo hi")
    result = mgr.wait(task.id, timeout=5)
    assert result.status == "done"
    assert result.exit_code == 0


def test_parallel_tasks_independent(tmp_path: Path) -> None:
    """Multiple tasks run in parallel without blocking each other."""
    mgr = TaskManager(tmp_path)
    started = time.time()
    a = mgr.start("sleep 0.5")
    b = mgr.start("sleep 0.5")
    c = mgr.start("sleep 0.5")
    mgr.wait(a.id, timeout=3)
    mgr.wait(b.id, timeout=3)
    mgr.wait(c.id, timeout=3)
    elapsed = time.time() - started
    # If they ran in parallel: ~0.5s. If serially: ~1.5s. Allow some slack.
    assert elapsed < 1.2, f"expected parallel execution, took {elapsed:.2f}s"


def test_list_tasks_includes_running_and_finished(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    long = mgr.start("sleep 3")
    short = mgr.start("echo done")
    try:
        _wait_status(mgr, short.id, {"done"})
        tasks = mgr.list_tasks()
        assert len(tasks) == 2
        statuses = {t.status for t in tasks}
        assert "running" in statuses
        assert "done" in statuses
    finally:
        mgr.shutdown()


def test_running_count(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    mgr.start("sleep 2")
    mgr.start("sleep 2")
    try:
        assert mgr.running_count() == 2
    finally:
        mgr.shutdown()


def test_clear_finished_removes_only_done_tasks(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    long = mgr.start("sleep 5")
    short = mgr.start("echo hi")
    try:
        _wait_status(mgr, short.id, {"done"})
        n = mgr.clear_finished()
        assert n == 1
        assert long.id in {t.id for t in mgr.list_tasks()}
        assert short.id not in {t.id for t in mgr.list_tasks()}
    finally:
        mgr.shutdown()


def test_tail_includes_output(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    task = mgr.start('bash -c \'echo line1; echo line2; echo err >&2\'')
    _wait_status(mgr, task.id, {"done"})
    body = mgr.tail(task.id)
    assert "line1" in body
    assert "line2" in body
    assert "err" in body


def test_shutdown_kills_non_detached_tasks(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    task = mgr.start("sleep 60")
    assert task.is_running
    mgr.shutdown()
    task = mgr.poll(task.id)
    assert not task.is_running


def test_drain_notices_returns_completed_tasks_once(tmp_path: Path) -> None:
    mgr = TaskManager(tmp_path)
    task = mgr.start("echo done")
    _wait_status(mgr, task.id, {"done"})
    notices = mgr.drain_notices()
    assert any(t.id == task.id for t in notices)
    # Second drain returns no further notice for the same task
    second = mgr.drain_notices()
    assert all(t.id != task.id for t in second)


def test_bind_and_current_manager_are_session_scoped(tmp_path: Path) -> None:
    """`bind_manager(cwd)` installs a fresh manager; `current_manager()` returns it."""
    bind_manager(tmp_path)
    try:
        mgr = current_manager()
        assert mgr is not None
        task = mgr.start("echo bound")
        _wait_status(mgr, task.id, {"done"})
    finally:
        shutdown_manager()


def test_tools_start_and_check(tmp_path: Path) -> None:
    """The tool surface (start_background / check_background) wraps the manager."""
    from essarion_build.agent import _tools

    _tools.bind_tools(tmp_path)
    try:
        msg = _tools.start_background("echo from-tool")
        assert "started task" in msg
        # extract id from "started task [abc123] '...'"
        task_id = msg.split("[", 1)[1].split("]", 1)[0]
        _wait_status(current_manager(), task_id, {"done"})
        report = _tools.check_background(task_id)
        assert "done" in report or "exit=0" in report
    finally:
        shutdown_manager()
