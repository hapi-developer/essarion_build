"""Subagents: parallel, context-isolated workers. Driven by scripted stubs —
each subagent gets a fresh StubProvider from the runtime factory, so the
tests are deterministic with no network."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import Context
from essarion_build._providers import StubProvider, Usage, ProviderResponse
from essarion_build._runtime import LiteRuntime
from essarion_build.agent import _agent_exec, _subagents
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
        id=new_session_id(), cwd=str(tmp_path), provider="stub", model="m",
        effort="quick", autonomous=True,
    )


# ---------- spec parsing ----------

def test_parse_specs_full_form() -> None:
    specs = _subagents.parse_specs({"tasks": [
        {"name": "a", "task": "audit auth", "read_only": True},
        {"task": "write tests"},
        "plain string task",
    ]})
    assert [s.name for s in specs] == ["a", "subagent-2", "subagent-3"]
    assert specs[0].read_only is True
    assert specs[2].task == "plain string task"


def test_parse_specs_single_task_shorthand() -> None:
    specs = _subagents.parse_specs({"task": "one thing", "name": "solo"})
    assert len(specs) == 1
    assert specs[0].name == "solo"


def test_parse_specs_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        _subagents.parse_specs({})
    with pytest.raises(ValueError):
        _subagents.parse_specs({"tasks": [{"name": "no-task"}]})
    with pytest.raises(ValueError):
        _subagents.parse_specs(
            {"tasks": [{"task": f"t{i}"} for i in range(_subagents.MAX_SUBAGENTS + 1)]}
        )


# ---------- direct run ----------

def _fresh_stub_factory(script: list[str]):
    """make_runtime that hands every caller a NEW stub with `script`."""
    def make(provider: str, model: str) -> LiteRuntime:
        return LiteRuntime(StubProvider(responses=list(script)))
    return make


def test_run_subagents_parallel_returns_ordered_outcomes(session) -> None:
    outcomes = _subagents.run_subagents(
        [
            _subagents.SubagentSpec(task="t1", name="one", read_only=True),
            _subagents.SubagentSpec(task="t2", name="two", read_only=True),
        ],
        session,
        make_runtime=_fresh_stub_factory(["<done>found the thing in core.py:42</done>"]),
    )
    assert [o.name for o in outcomes] == ["one", "two"]
    assert all(o.stopped_reason == "done" for o in outcomes)
    assert all("core.py:42" in o.summary for o in outcomes)


def test_read_only_subagent_cannot_write(session, tmp_path) -> None:
    outcomes = _subagents.run_subagents(
        [_subagents.SubagentSpec(task="sneaky write", name="ro", read_only=True)],
        session,
        make_runtime=_fresh_stub_factory([
            _call("write_file", path="evil.txt", content="nope"),
            "<done>tried</done>",
        ]),
    )
    assert not (tmp_path / "evil.txt").exists()
    assert outcomes[0].files_touched == []


def test_subagent_writes_are_tracked_and_logged(session, tmp_path) -> None:
    outcomes = _subagents.run_subagents(
        [_subagents.SubagentSpec(task="make a file", name="writer")],
        session,
        make_runtime=_fresh_stub_factory([
            _call("write_file", path="made.txt", content="hello"),
            "<done>made made.txt</done>",
        ]),
    )
    assert (tmp_path / "made.txt").read_text() == "hello"
    assert outcomes[0].files_touched == ["made.txt"]
    # Mutations flow through the shared change log → /undo & /diff still work.
    from essarion_build.agent._changes import current_changelog

    assert any(e.path == "made.txt" for e in current_changelog().entries)


def test_subagent_usage_rolls_up(session) -> None:
    rich_usage = ProviderResponse(
        text="<done>ok</done>",
        usage=Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )

    def make(provider: str, model: str) -> LiteRuntime:
        return LiteRuntime(StubProvider(responses=[rich_usage]))

    outcomes = _subagents.run_subagents(
        [_subagents.SubagentSpec(task="t", name="n", read_only=True)],
        session, make_runtime=make,
    )
    assert outcomes[0].usage.total_tokens == 150


def test_crashing_subagent_does_not_sink_the_batch(session) -> None:
    def make(provider: str, model: str):
        raise RuntimeError("factory exploded")

    outcomes = _subagents.run_subagents(
        [_subagents.SubagentSpec(task="t", name="boom")],
        session, make_runtime=make,
    )
    assert outcomes[0].stopped_reason == "error"
    assert "factory exploded" in outcomes[0].error


# ---------- through the executor (the parent loop) ----------

def test_executor_spawns_subagents_and_feeds_back_summaries(console, session, tmp_path) -> None:
    """Parent emits spawn_subagents → workers run → parent sees only their
    summaries (context isolation) and inherits files_touched/usage."""
    calls = {"n": 0}
    parent_script = [
        _call("spawn_subagents", tasks=[
            {"name": "w1", "task": "write a.txt"},
            {"name": "w2", "task": "scan", "read_only": True},
        ]),
        "<done>fanned out and merged</done>",
    ]
    child_script = [
        _call("write_file", path="a.txt", content="A"),
        "<done>a.txt written; scan found nothing odd</done>",
    ]
    parent_stub = StubProvider(responses=list(parent_script))

    def make_with_capture(provider: str, model: str) -> LiteRuntime:
        calls["n"] += 1
        if calls["n"] == 1:
            return LiteRuntime(parent_stub)
        return LiteRuntime(StubProvider(responses=list(child_script)))

    turn = TaskTurn(task="parent")
    result = _agent_exec.execute(
        console, session, "do a big job", Context(),
        make_runtime=make_with_capture, turn=turn,
    )
    assert result.stopped_reason == "done"
    assert "a.txt" in result.files_touched      # child's mutation surfaced on parent
    assert (tmp_path / "a.txt").read_text() == "A"
    out = console.file.getvalue()
    assert "Spawned" in out and "w1" in out and "w2" in out
    # Context isolation: the parent model received ONLY the children's
    # summaries in its feedback — and did receive them.
    fed_back = parent_stub.calls[-1]["messages"][-1]["content"]
    assert "a.txt written; scan found nothing odd" in fed_back
    assert "[w1]" in fed_back and "[w2]" in fed_back


def test_subagent_cannot_spawn_subagents(console, session) -> None:
    """interactive=False (a subagent context) → spawn requests are refused."""
    stub = StubProvider(responses=[
        _call("spawn_subagents", tasks=[{"task": "recurse"}]),
        "<done>gave up on recursion</done>",
    ])
    result = _agent_exec.execute(
        console, session, "try to recurse", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub),
        interactive=False,
    )
    assert result.stopped_reason == "done"
    fed_back = stub.calls[-1]["messages"][-1]["content"]
    assert "cannot spawn subagents" in fed_back


def test_non_interactive_ask_user_gets_canned_answer(console, session) -> None:
    stub = StubProvider(responses=[
        _call("ask_user", questions=[{"question": "which?", "options": ["a", "b"]}]),
        "<done>chose for myself</done>",
    ])
    result = _agent_exec.execute(
        console, session, "ask something", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub),
        interactive=False,
    )
    assert result.stopped_reason == "done"
    fed_back = stub.calls[-1]["messages"][-1]["content"]
    assert "no interactive user" in fed_back


def test_non_interactive_risky_shell_is_denied_not_hung(console, session) -> None:
    """A permission decision that would ASK must become DENY when there is no
    user at the keyboard — never a blocking prompt inside a worker thread."""
    stub = StubProvider(responses=[
        _call("run_shell", cmd="sudo rm -rf ./build"),
        "<done>adapted</done>",
    ])
    result = _agent_exec.execute(
        console, session, "cleanup", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub),
        interactive=False,
    )
    assert result.stopped_reason == "done"
    fed_back = stub.calls[-1]["messages"][-1]["content"]
    assert "blocked by permission policy" in fed_back


def test_top_level_prompt_advertises_subagents_but_subagent_prompt_does_not(
    console, session
) -> None:
    stub_top = StubProvider(responses=["<done>x</done>"])
    _agent_exec.execute(
        console, session, "t", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub_top),
    )
    assert "spawn_subagents" in stub_top.calls[0]["system"]

    stub_sub = StubProvider(responses=["<done>x</done>"])
    _agent_exec.execute(
        console, session, "t", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub_sub),
        interactive=False,
    )
    assert "spawn_subagents" not in stub_sub.calls[0]["system"]
