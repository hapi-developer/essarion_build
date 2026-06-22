"""Scheduled / recurring tasks — the cron-style automation surface that runs
essarion unattended on a cadence."""

from __future__ import annotations

from pathlib import Path

import pytest

from essarion_build.agent._schedule import (
    format_interval,
    load_schedule,
    parse_interval,
    run_due,
    run_one,
)


def _sched(tmp: Path):
    (tmp / ".essarion").mkdir(exist_ok=True)
    return load_schedule(tmp)


# ---------- interval parsing ----------

@pytest.mark.parametrize(
    "spec,sec",
    [("30s", 30), ("10m", 600), ("2h", 7200), ("1d", 86400), ("1w", 604800), ("45", 45)],
)
def test_parse_interval(spec: str, sec: int) -> None:
    assert parse_interval(spec) == sec


def test_parse_interval_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_interval("soon")
    with pytest.raises(ValueError):
        parse_interval("5x")


def test_parse_interval_enforces_floor() -> None:
    with pytest.raises(ValueError):
        parse_interval("5s")


def test_format_interval() -> None:
    assert format_interval(86400) == "1d"
    assert format_interval(600) == "10m"
    assert format_interval(45) == "45s"


# ---------- store CRUD + persistence ----------

def test_add_list_remove_roundtrip(tmp_path: Path) -> None:
    s = _sched(tmp_path)
    j = s.add("audit deps for CVEs", "1d")
    s.save()
    s2 = load_schedule(tmp_path)
    assert len(s2.jobs) == 1
    assert s2.jobs[0].task == "audit deps for CVEs"
    assert s2.get(j.id).every == 86400
    assert s2.remove(j.id)
    s2.save()
    assert load_schedule(tmp_path).jobs == []


def test_add_rejects_empty_task(tmp_path: Path) -> None:
    s = _sched(tmp_path)
    with pytest.raises(ValueError):
        s.add("   ", "1d")


# ---------- due / advance semantics ----------

def test_due_and_advance(tmp_path: Path) -> None:
    s = _sched(tmp_path)
    now = 1000.0
    j = s.add("x", "1m", due_now=True, now=now)
    assert s.due(now) == [j]
    assert s.due(now - 1) == []
    j.advance(now)
    assert j.runs == 1
    assert j.last_run == now
    assert j.next_run == now + 60
    assert s.due(now) == []


def test_advance_catches_up_after_downtime(tmp_path: Path) -> None:
    s = _sched(tmp_path)
    j = s.add("x", "1m", due_now=True, now=0.0)
    j.advance(500.0)  # 500s later with a 60s interval
    assert j.next_run > 500.0
    assert j.next_run - 500.0 <= 60


def test_disabled_job_is_never_due(tmp_path: Path) -> None:
    s = _sched(tmp_path)
    j = s.add("x", "1m", due_now=True, now=0.0)
    assert s.set_enabled(j.id, False)
    assert s.due(0.0) == []


# ---------- running ----------

def test_run_due_with_injected_runner(tmp_path: Path) -> None:
    s = _sched(tmp_path)
    now = 1000.0
    j = s.add("nightly report", "1m", due_now=True, now=now)
    s.save()
    ran: list[str] = []

    def runner(job):
        ran.append(job.id)
        return "exit 0"

    results = run_due(tmp_path, runner=runner, now=now)
    assert [status for _, status in results] == ["exit 0"]
    assert ran == [j.id]
    after = load_schedule(tmp_path).get(j.id)
    assert after.runs == 1
    assert after.last_status == "exit 0"
    assert after.next_run > now


def test_run_due_nothing_due(tmp_path: Path) -> None:
    s = _sched(tmp_path)
    s.add("x", "1h", now=1000.0)  # next_run = 1000 + 3600
    s.save()
    assert run_due(tmp_path, runner=lambda j: "x", now=1000.0) == []


def test_run_due_isolates_a_failing_job(tmp_path: Path) -> None:
    s = _sched(tmp_path)
    j = s.add("x", "1m", due_now=True, now=1000.0)
    s.save()

    def boom(job):
        raise RuntimeError("kaboom")

    results = run_due(tmp_path, runner=boom, now=1000.0)
    assert "error" in results[0][1].lower()
    # The job still advanced, so a permanently-broken job can't spin.
    assert load_schedule(tmp_path).get(j.id).runs == 1


def test_run_one(tmp_path: Path) -> None:
    s = _sched(tmp_path)
    j = s.add("x", "1h", now=1000.0)
    s.save()
    assert run_one(tmp_path, j.id, runner=lambda job: "exit 0") == "exit 0"
    assert load_schedule(tmp_path).get(j.id).runs == 1


def test_run_one_unknown_id(tmp_path: Path) -> None:
    _sched(tmp_path).save()
    with pytest.raises(KeyError):
        run_one(tmp_path, "nope", runner=lambda j: "x")


# ---------- CLI surface ----------

def test_cli_schedule_add_and_list(tmp_path: Path, capsys) -> None:
    (tmp_path / ".essarion").mkdir()
    from essarion_build.cli import main

    rc = main(["schedule", "add", "audit the deps", "--every", "1d", "--cwd", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / ".essarion" / "schedule.json").is_file()
    capsys.readouterr()
    rc = main(["schedule", "list", "--cwd", str(tmp_path)])
    assert rc == 0
    assert "audit the deps" in capsys.readouterr().out
