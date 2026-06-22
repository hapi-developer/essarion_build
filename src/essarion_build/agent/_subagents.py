"""Subagents — parallel, context-isolated workers the main agent can spawn.

The whole point of a subagent is **context isolation**: a scoped task (sweep
these modules for dead code, find every caller of X, build the tests for Y)
runs in its own fresh executor loop with its own message history, and only
its final SUMMARY returns to the parent. The parent's context never absorbs
the hundreds of intermediate tool results, so a big fan-out exploration costs
the parent a paragraph instead of a context window.

The model calls:

    <tool_call name="spawn_subagents">{"tasks": [
        {"name": "auth-sweep", "task": "Audit src/auth/ for ...", "read_only": true},
        {"name": "api-tests",  "task": "Write tests for src/api.py"}
    ]}</tool_call>

Tasks run in PARALLEL (threads — the executor blocks on provider I/O, so
threads overlap well). Each subagent:

- shares the parent's sandbox cwd, session model/provider and change log
  (so `/undo` and `/diff` still see every mutation),
- is non-interactive: it can't prompt the user; permission decisions that
  would normally *ask* are denied instead (yolo mode still auto-approves),
- cannot spawn further subagents (depth cap of 1 — fan-out, not a fork bomb),
- gets a tighter step/read budget than a full turn,
- rolls its token usage and cost into the parent turn after it finishes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import Context, Usage
from ._permissions import PermissionPolicy
from ._session import Session, TaskTurn


# Hard limits — a fan-out should be wide but bounded.
MAX_SUBAGENTS = 8
_SUBAGENT_MAX_STEPS = 18
_SUBAGENT_READ_CAP = 14
# How much of one subagent's summary the parent sees.
_SUMMARY_CAP = 1800

# The tool sets a subagent may use. Note: no spawn_subagents (no recursion),
# no ask_user (non-interactive), no computer/desktop tools.
READ_ONLY_ALLOW = {
    "read_file", "list_dir", "grep", "find_files", "glob",
    "repo_map", "outline", "find_symbol", "web_fetch",
}
FULL_ALLOW = READ_ONLY_ALLOW | {
    "write_file", "apply_diff", "edit_symbol", "delete_file", "run_shell",
    "start_background", "check_background", "wait_background",
    "kill_background", "list_background", "remember",
}


@dataclass
class SubagentSpec:
    """One requested subagent, validated."""

    task: str
    name: str = ""
    read_only: bool = False


@dataclass
class SubagentOutcome:
    """What one subagent returned — the only thing the parent's context sees."""

    name: str
    summary: str = ""
    stopped_reason: str = "done"
    files_touched: list[str] = field(default_factory=list)
    steps: int = 0
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    error: str = ""


def parse_specs(args: dict[str, Any]) -> list[SubagentSpec]:
    """Validate spawn_subagents args into specs. Raises ValueError on bad input."""
    raw = args.get("tasks")
    if isinstance(raw, dict):
        raw = [raw]
    if isinstance(args.get("task"), str) and not raw:
        raw = [{"task": args["task"], "name": str(args.get("name", ""))}]
    if not isinstance(raw, list) or not raw:
        raise ValueError('expected {"tasks": [{"task": "...", "name": "..."}]}')
    specs: list[SubagentSpec] = []
    for i, item in enumerate(raw, start=1):
        if isinstance(item, str):
            item = {"task": item}
        if not isinstance(item, dict):
            continue
        task = str(item.get("task", "")).strip()
        if not task:
            continue
        name = str(item.get("name", "")).strip() or f"subagent-{i}"
        specs.append(SubagentSpec(
            task=task, name=name, read_only=bool(item.get("read_only", False)),
        ))
    if not specs:
        raise ValueError("no valid tasks given")
    if len(specs) > MAX_SUBAGENTS:
        raise ValueError(f"too many subagents ({len(specs)}); max is {MAX_SUBAGENTS}")
    return specs


def _quiet_console():
    """A themed console that renders nothing — subagents work silently; the
    parent renders one line per subagent instead."""
    from rich.console import Console

    from ._theme import ESSARION_THEME

    return Console(theme=ESSARION_THEME, highlight=False, quiet=True)


def _subagent_context(spec: SubagentSpec, session: Session) -> Context:
    """A fresh, lean context for one subagent: project memory + conventions +
    a repo map — but NOT the parent's conversation, skills, or attachments.
    Isolation is the feature."""
    from pathlib import Path

    ctx = Context()
    cwd = Path(session.cwd)
    try:
        from ._memory import inject_into_context, load_memory

        inject_into_context(load_memory(cwd), ctx)
    except Exception:  # noqa: BLE001 - memory must never break a spawn
        pass
    try:
        from ._conventions import inject_into_context as _inject_conventions

        _inject_conventions(cwd, ctx)
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import _repomap

        rendered = _repomap.render_map(_repomap.build_index(cwd), budget_chars=4000)
        if rendered:
            ctx.add_note("REPO MAP (ranked key symbols):\n" + rendered)
    except Exception:  # noqa: BLE001
        pass
    return ctx


def _run_one(
    spec: SubagentSpec,
    session: Session,
    *,
    make_runtime: Callable[[str, str], Any],
    policy: PermissionPolicy,
) -> SubagentOutcome:
    """Run one subagent to completion in the calling thread."""
    from . import _agent_exec

    outcome = SubagentOutcome(name=spec.name)
    sub_turn = TaskTurn(task=spec.task)
    allow = set(READ_ONLY_ALLOW if spec.read_only else FULL_ALLOW)
    preamble = (
        f"You are the subagent {spec.name!r} — a scoped worker spawned by a "
        "lead agent. Do ONLY your assigned task; do not expand scope. "
        "You cannot ask the user questions or spawn further subagents. "
        "Your <done> summary is the ONLY thing the lead agent will see, so "
        "make it carry your full findings: be specific, cite files/symbols/"
        "line numbers, and keep it under ~15 sentences."
        + (" You are READ-ONLY: do not modify any files." if spec.read_only else "")
    )
    try:
        result = _agent_exec.execute(
            _quiet_console(),
            session,
            spec.task,
            _subagent_context(spec, session),
            make_runtime=make_runtime,
            turn=sub_turn,
            max_steps=_SUBAGENT_MAX_STEPS,
            allow=allow,
            extra_system=preamble,
            policy=policy,
            interactive=False,
            read_cap_override=_SUBAGENT_READ_CAP,
        )
        outcome.summary = (result.summary or "").strip()[:_SUMMARY_CAP]
        outcome.stopped_reason = result.stopped_reason
        outcome.files_touched = list(result.files_touched)
        outcome.steps = result.steps
    except Exception as e:  # noqa: BLE001 - one subagent's crash must not sink the batch
        outcome.error = f"{type(e).__name__}: {e}"
        outcome.stopped_reason = "error"
    outcome.usage = sub_turn.usage
    outcome.cost_usd = sub_turn.cost_usd
    return outcome


def run_subagents(
    specs: list[SubagentSpec],
    session: Session,
    *,
    make_runtime: Callable[[str, str], Any],
    policy: PermissionPolicy | None = None,
) -> list[SubagentOutcome]:
    """Run all specs in parallel; return outcomes in the original order.

    Usage/cost accounting is per-outcome — the CALLER folds it into the parent
    turn after this returns (single-threaded merge; no locking needed).
    """
    policy = policy or PermissionPolicy()
    outcomes: list[SubagentOutcome | None] = [None] * len(specs)

    def _worker(i: int, spec: SubagentSpec) -> None:
        outcomes[i] = _run_one(
            spec, session, make_runtime=make_runtime, policy=policy
        )

    threads = [
        threading.Thread(target=_worker, args=(i, s), name=f"subagent-{s.name}", daemon=True)
        for i, s in enumerate(specs)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return [
        o if o is not None else SubagentOutcome(name=s.name, error="did not run", stopped_reason="error")
        for o, s in zip(outcomes, specs)
    ]


def format_outcomes(outcomes: list[SubagentOutcome]) -> str:
    """The combined report fed back to the parent model."""
    blocks: list[str] = []
    for o in outcomes:
        head = f"[{o.name}] " + (
            f"FAILED: {o.error}" if o.error else f"finished ({o.stopped_reason}, {o.steps} step(s))"
        )
        if o.files_touched:
            head += " — files touched: " + ", ".join(o.files_touched[:10])
        body = o.summary or ("(no summary returned)" if not o.error else "")
        blocks.append(head + ("\n" + body if body else ""))
    return "\n\n".join(blocks)


__all__ = [
    "MAX_SUBAGENTS",
    "SubagentOutcome",
    "SubagentSpec",
    "format_outcomes",
    "parse_specs",
    "run_subagents",
]
