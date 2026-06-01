"""Autonomous execution loop: the agent chains real disk tools (write/edit/
delete/shell) toward a goal until it emits <done>. Driven by scripted stub
responses so it's fully deterministic — no API key, no network."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import Context, ProviderResponse, Usage
from essarion_build._providers import _PROVIDER_REGISTRY, StubProvider
from essarion_build._runtime import LiteRuntime
from essarion_build.agent import _agent_exec, _loop, _ui
from essarion_build.agent._session import Session, TaskTurn, new_session_id
from essarion_build.agent._theme import ESSARION_THEME
from essarion_build.agent._tools import bind_tools, register_all


def _call(name: str, **args: object) -> str:
    return f'<tool_call name="{name}">{json.dumps(args)}</tool_call>'


@pytest.fixture
def console() -> Console:
    return Console(theme=ESSARION_THEME, file=io.StringIO(), force_terminal=False, width=120)


@pytest.fixture
def session(tmp_path: Path) -> Session:
    bind_tools(tmp_path)
    register_all()
    return Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="stub",
        model="m",
        budget_usd=1.00,
        effort="quick",  # 1 plan call, deterministic
        autonomous=True,
    )


def test_execute_creates_edits_deletes_and_runs(console, session, tmp_path) -> None:
    """The loop should write a file, edit it, delete another, run a command,
    and report the files it touched — all directly on disk."""
    stub = StubProvider(responses=[
        _call("write_file", path="fib.py", content="def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n"),
        _call("write_file", path="junk.txt", content="scratch\n"),
        _call("apply_diff", path="fib.py", old="return a\n", new="return a  # nth fibonacci\n"),
        _call("delete_file", path="junk.txt"),
        _call("run_shell", cmd="echo built-ok"),
        "<done>created fib.py, edited it, removed junk.txt, verified</done>",
    ])
    turn = TaskTurn(task="build fib")
    result = _agent_exec.execute(
        console, session, "write fib.py with a test", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub), turn=turn,
    )

    # On-disk effects.
    assert (tmp_path / "fib.py").is_file()
    assert "nth fibonacci" in (tmp_path / "fib.py").read_text()  # the edit landed
    assert not (tmp_path / "junk.txt").is_file()                 # created then deleted

    # Loop bookkeeping.
    assert result.stopped_reason == "done"
    assert "fib.py" in result.files_touched
    assert "junk.txt" in result.files_touched
    assert "created fib.py" in result.summary

    # Each action surfaced as a tool run.
    out = console.file.getvalue()
    for tool in ("write_file", "apply_diff", "delete_file", "run_shell"):
        assert tool in out, f"missing tool_run for {tool}"


def test_execute_respects_step_cap(console, session) -> None:
    """A model that never says <done> is stopped at the step cap, not forever."""
    stub = StubProvider(responses=[_call("list_dir", path=".")] * 50, auto_respond=False)
    # auto_respond=False but we give plenty; cap should bite before exhaustion.
    result = _agent_exec.execute(
        console, session, "loop forever", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub), max_steps=5,
    )
    assert result.stopped_reason == "max_steps"
    assert result.steps == 5


class _AutoProvider:
    """Scripted provider for the full run_turn_autonomous path. Class-var queue
    persists across the agent rebuilding the provider each call."""

    _RESPONSES = [
        # plan phase (quick → 1 call, no tool_calls so no inline re-plan)
        "<plan>1. write greet.py\n2. wire a CLI</plan>"
        "<tradeoffs>pure function</tradeoffs><verdict>ship</verdict>",
        # autonomous exec
        _call("write_file", path="greet.py", content="def greet(name):\n    return f'hi {name}'\n"),
        _call("write_file", path="cli.py", content="from greet import greet\nprint(greet('world'))\n"),
        _call("run_shell", cmd="python cli.py"),
        "<done>greet.py + cli.py created and run</done>",
    ]
    _idx = 0

    @classmethod
    def reset(cls) -> None:
        cls._idx = 0

    def __init__(self, *, api_key=None, model: str) -> None:
        self.model = model

    def complete(self, *, system, messages, max_tokens):
        if _AutoProvider._idx >= len(_AutoProvider._RESPONSES):
            raise IndexError("script exhausted")
        text = _AutoProvider._RESPONSES[_AutoProvider._idx]
        _AutoProvider._idx += 1
        return ProviderResponse(text=text, usage=Usage(prompt_tokens=20, completion_tokens=10, total_tokens=30))


def test_run_turn_autonomous_end_to_end(monkeypatch, console, session, tmp_path) -> None:
    """Plan → approve → autonomous build, exercised through the public entry."""
    _AutoProvider.reset()
    monkeypatch.setitem(
        _PROVIDER_REGISTRY, "stub",
        lambda *, api_key=None, model: _AutoProvider(api_key=api_key, model=model),
    )
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda c: "approve")
    _loop.run_turn_autonomous(console, session, "write a greeting helper and a CLI")

    # The agent wrote both files directly to disk.
    assert (tmp_path / "greet.py").is_file()
    assert (tmp_path / "cli.py").is_file()

    # The turn recorded the plan and the files it touched.
    assert session.history, "turn not recorded"
    last = session.history[-1]
    assert "greet.py" in last.plan or "write greet.py" in last.plan
    assert "greet.py" in last.files_touched and "cli.py" in last.files_touched

    out = console.file.getvalue()
    assert "build" in out  # the ── build ── phase header rendered


def test_autonomous_turn_does_not_prompt_for_approval(
    monkeypatch, console, session, tmp_path
) -> None:
    """The default agentic turn plans internally and builds straight through —
    it must NOT stop to ask the user to approve the plan."""
    _AutoProvider.reset()
    monkeypatch.setitem(
        _PROVIDER_REGISTRY, "stub",
        lambda *, api_key=None, model: _AutoProvider(api_key=api_key, model=model),
    )

    def _boom(_console):
        raise AssertionError("autonomous mode must not prompt for plan approval")

    monkeypatch.setattr(_ui, "prompt_approve_plan", _boom)

    # No exception → the approval gate was never hit, and the files got built.
    _loop.run_turn_autonomous(console, session, "write a greeting helper and a CLI")
    assert (tmp_path / "greet.py").is_file()
    assert (tmp_path / "cli.py").is_file()


def test_execute_nudges_past_a_prose_only_step(console, session, tmp_path) -> None:
    """A single prose-only step (no tool call, no <done>) shouldn't end the task
    — the loop nudges the model to keep going, and it then finishes the work."""
    stub = StubProvider(
        responses=[
            "Let me think about how to approach this…",          # prose only
            _call("write_file", path="made.txt", content="ok\n"),  # then it acts
            "<done>created made.txt</done>",
        ],
        auto_respond=False,
    )
    result = _agent_exec.execute(
        console, session, "create made.txt", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub),
    )
    assert (tmp_path / "made.txt").is_file()
    assert result.stopped_reason == "done"


def test_execute_gives_up_after_repeated_no_action(console, session) -> None:
    """If the model never acts, the loop nudges a bounded number of times and
    then stops with no_action — it does not spin forever."""
    stub = StubProvider(responses=["thinking, no actions…"] * 10, auto_respond=False)
    result = _agent_exec.execute(
        console, session, "stall", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub), max_steps=20,
    )
    assert result.stopped_reason == "no_action"
    # 2 nudges + the final give-up step = 3 model calls, well under the cap.
    assert result.steps == 3
