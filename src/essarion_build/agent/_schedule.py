"""Scheduled / recurring tasks — run essarion unattended on a cadence.

Daily code-health reports, nightly dependency audits, a weekly "summarize what
changed" digest — described once in natural language, then run on a schedule
without you in the loop. The store is a plain JSON file under `.essarion/` so
it's inspectable and diffable; the runner is zero-dependency.

How "unattended" works (honestly): a schedule needs *something* to wake it.
essarion gives you two ways, no daemon required —

1. **System cron / CI cron** (recommended for real unattended runs): add one
   crontab line that calls ``essarion schedule run-due`` every few minutes; it
   runs whatever is due and exits. This survives reboots and costs nothing idle.
2. **Foreground loop** (handy on a VPS you keep up): ``essarion schedule
   run-due --loop 60`` stays running and re-checks every 60s.

Each due job runs as a one-shot agent task in its own process
(``python -m essarion_build --task "<task>"``), so a long or crashing job can
never wedge the scheduler.

CLI::

    essarion schedule add "audit deps for CVEs and open issues" --every 1d
    essarion schedule list
    essarion schedule run <id>          # run one now, regardless of due time
    essarion schedule run-due           # run everything due (what cron calls)
    essarion schedule rm <id>

REPL::

    /schedule                    list jobs
    /schedule add 1d <task...>   add a daily job
    /schedule rm <id>            remove a job
"""

from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from pydantic import BaseModel, Field

# Interval suffixes → seconds. A bare number is taken as seconds.
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([smhdw]?)\s*$", re.IGNORECASE)

# Floor on an interval — a runaway "every 1s" schedule helps nobody.
MIN_INTERVAL = 30


def parse_interval(spec: str | int) -> int:
    """Parse ``"10m"`` / ``"2h"`` / ``"1d"`` / ``"30s"`` / ``"1w"`` (or a bare
    number of seconds) into seconds. Raises ``ValueError`` on garbage."""
    if isinstance(spec, int):
        seconds = spec
    else:
        m = _INTERVAL_RE.match(str(spec))
        if not m:
            raise ValueError(
                f"bad interval {spec!r} — use e.g. 30s, 10m, 2h, 1d, 1w"
            )
        seconds = int(m.group(1)) * _UNIT_SECONDS[(m.group(2) or "s").lower()]
    if seconds < MIN_INTERVAL:
        raise ValueError(f"interval too short — minimum is {MIN_INTERVAL}s")
    return seconds


def format_interval(seconds: int) -> str:
    """Render seconds back as a compact ``1d`` / ``2h`` / ``10m`` string."""
    for suffix, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0 and seconds >= size:
            return f"{seconds // size}{suffix}"
    return f"{seconds}s"


class Job(BaseModel):
    """One recurring task."""

    id: str
    task: str
    every: int  # seconds between runs
    name: str = ""
    enabled: bool = True
    created_at: float = Field(default_factory=time.time)
    last_run: float | None = None
    next_run: float = 0.0
    runs: int = 0
    last_status: str = ""
    model: str | None = None
    budget: float | None = None

    def is_due(self, now: float) -> bool:
        return self.enabled and now >= self.next_run

    def advance(self, now: float) -> None:
        """Record a run and roll ``next_run`` forward, catching up past any
        missed windows so a long downtime doesn't trigger a backlog storm."""
        self.last_run = now
        self.runs += 1
        if self.every <= 0:
            self.next_run = now
            return
        nxt = self.next_run
        while nxt <= now:
            nxt += self.every
        self.next_run = nxt


def new_job_id() -> str:
    return secrets.token_hex(3)


class Schedule(BaseModel):
    """The set of recurring jobs for a project (or the global store)."""

    path: Path
    jobs: list[Job] = Field(default_factory=list)

    def add(
        self,
        task: str,
        every: str | int,
        *,
        name: str = "",
        model: str | None = None,
        budget: float | None = None,
        due_now: bool = False,
        now: float | None = None,
    ) -> Job:
        task = " ".join((task or "").split())
        if not task:
            raise ValueError("task must be non-empty")
        seconds = parse_interval(every)
        ts = time.time() if now is None else now
        job = Job(
            id=new_job_id(),
            task=task,
            every=seconds,
            name=name.strip(),
            model=model,
            budget=budget,
            created_at=ts,
            next_run=ts if due_now else ts + seconds,
        )
        self.jobs.append(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return next((j for j in self.jobs if j.id == job_id), None)

    def remove(self, job_id: str) -> bool:
        before = len(self.jobs)
        self.jobs = [j for j in self.jobs if j.id != job_id]
        return len(self.jobs) != before

    def set_enabled(self, job_id: str, enabled: bool) -> bool:
        job = self.get(job_id)
        if job is None:
            return False
        job.enabled = enabled
        return True

    def due(self, now: float | None = None) -> list[Job]:
        ts = time.time() if now is None else now
        return [j for j in self.jobs if j.is_due(ts)]

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"jobs": [j.model_dump() for j in self.jobs]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return self.path


def schedule_path_for(cwd: str | Path) -> Path:
    """Where the schedule lives for ``cwd``.

    Per-project (``<root>/.essarion/schedule.json``) when initialized, else the
    global ``~/.essarion/schedule.json``. Mirrors memory + learned skills."""
    from ._project import find_project_root

    project = find_project_root(cwd)
    if project.has_essarion_dir:
        return project.essarion_dir / "schedule.json"
    return Path.home() / ".essarion" / "schedule.json"


def load_schedule(cwd: str | Path) -> Schedule:
    """Read the schedule for ``cwd`` (empty if none exists yet)."""
    path = schedule_path_for(cwd)
    if not path.is_file():
        return Schedule(path=path, jobs=[])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Schedule(path=path, jobs=[])
    jobs = [Job.model_validate(j) for j in (data.get("jobs") or [])]
    return Schedule(path=path, jobs=jobs)


def subprocess_runner(cwd: str | Path, *, timeout: int = 3600):
    """Default job runner: execute the task as a one-shot agent in its own
    process, so a long or crashing job can't wedge the scheduler."""
    import subprocess
    import sys

    def run(job: Job) -> str:
        cmd = [sys.executable, "-m", "essarion_build", "--task", job.task]
        if job.model:
            cmd += ["--model", job.model]
        if job.budget:
            cmd += ["--budget", str(job.budget)]
        try:
            proc = subprocess.run(
                cmd, cwd=str(cwd), capture_output=True, text=True,
                timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            return f"timed out after {timeout}s"
        except OSError as e:
            return f"failed to start: {e}"
        return f"exit {proc.returncode}"

    return run


def run_due(
    cwd: str | Path,
    *,
    runner=None,
    now: float | None = None,
) -> list[tuple[Job, str]]:
    """Run every job that's due, advance each, and persist. Returns the
    ``(job, status)`` pairs that ran. ``runner`` is injectable for tests."""
    schedule = load_schedule(cwd)
    ts = time.time() if now is None else now
    due = schedule.due(ts)
    if not due:
        return []
    run = runner if runner is not None else subprocess_runner(cwd)
    results: list[tuple[Job, str]] = []
    for job in due:
        try:
            status = run(job)
        except Exception as e:  # noqa: BLE001 - a bad job can't kill the loop
            status = f"error: {type(e).__name__}: {e}"
        job.last_status = str(status)
        job.advance(time.time() if now is None else now)
        results.append((job, job.last_status))
    schedule.save()
    return results


def run_one(cwd: str | Path, job_id: str, *, runner=None) -> str:
    """Run a single job now, regardless of its due time. Returns its status."""
    schedule = load_schedule(cwd)
    job = schedule.get(job_id)
    if job is None:
        raise KeyError(job_id)
    run = runner if runner is not None else subprocess_runner(cwd)
    status = run(job)
    job.last_status = str(status)
    job.advance(time.time())
    schedule.save()
    return status


__all__ = [
    "Job",
    "Schedule",
    "MIN_INTERVAL",
    "parse_interval",
    "format_interval",
    "schedule_path_for",
    "load_schedule",
    "subprocess_runner",
    "run_due",
    "run_one",
    "new_job_id",
]
