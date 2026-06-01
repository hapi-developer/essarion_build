"""/goal — pursue a goal autonomously until done, with no approval stops and
auto-continuation past step caps. Driven by scripted providers (no network)."""

from __future__ import annotations

import io
import json

import pytest
from rich.console import Console

from essarion_build import ProviderResponse, Usage
from essarion_build._providers import _PROVIDER_REGISTRY
from essarion_build.agent import _commands, _loop, _ui
from essarion_build.agent._session import Session, new_session_id
from essarion_build.agent._theme import ESSARION_THEME
from essarion_build.agent._tools import bind_tools, register_all


def _call(name, **a):
    return f'<tool_call name="{name}">{json.dumps(a)}</tool_call>'


@pytest.fixture
def console():
    return Console(theme=ESSARION_THEME, file=io.StringIO(), force_terminal=False, width=120)


@pytest.fixture
def session(tmp_path):
    bind_tools(tmp_path)
    register_all()
    return Session(id=new_session_id(), cwd=str(tmp_path), provider="stub", model="m",
                   budget_usd=5.0, effort="quick")


def test_goal_runs_without_approval_and_finishes(monkeypatch, console, session, tmp_path) -> None:
    """/goal never calls the approval prompt and runs the plan to <done>."""
    script = [
        "<plan>1. make the file</plan><tradeoffs>n/a</tradeoffs><verdict>ship</verdict>",
        _call("write_file", path="out.txt", content="done\n"),
        "<done>created out.txt</done>",
    ]
    i = {"n": 0}

    class P:
        model = "m"
        def complete(self, *, system, messages, max_tokens):
            t = script[i["n"]]; i["n"] += 1
            return ProviderResponse(text=t, usage=Usage(total_tokens=10))

    monkeypatch.setitem(_PROVIDER_REGISTRY, "stub", lambda *, api_key=None, model: P())

    def _boom(_console):
        raise AssertionError("/goal must NOT ask for plan approval")
    monkeypatch.setattr(_ui, "prompt_approve_plan", _boom)

    _loop.run_goal(console, session, "create out.txt")
    out = console.file.getvalue()
    assert (tmp_path / "out.txt").is_file()
    assert "goal accomplished" in out
    assert session.autonomous is True  # /goal implies autonomous


def test_goal_continues_past_step_cap_until_done(monkeypatch, console, session) -> None:
    """If a round hits the step cap, /goal starts another round until <done>."""
    rounds = {"n": 0}

    class P:
        model = "m"
        def complete(self, *, system, messages, max_tokens):
            # The executor's system prompt is distinct from the planner's.
            is_exec = "autonomous coding agent" in system
            if not is_exec:
                return ProviderResponse(text="<plan>p</plan><tradeoffs>t</tradeoffs><verdict>v</verdict>",
                                        usage=Usage(total_tokens=5))
            # Exec: round 1 never says done (forces the step cap); round 2 finishes.
            if rounds["n"] == 0:
                return ProviderResponse(text=_call("list_dir", path="."), usage=Usage(total_tokens=5))
            return ProviderResponse(text="<done>finished on the second round</done>", usage=Usage(total_tokens=5))

    monkeypatch.setitem(_PROVIDER_REGISTRY, "stub", lambda *, api_key=None, model: P())
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda c: "approve")

    # Tiny step cap so round 1 caps out fast; flip rounds after the first.
    import essarion_build.agent._agent_exec as ax
    orig = ax.execute
    def wrapped(*a, **k):
        k.setdefault("max_steps", 3)
        res = orig(*a, **k)
        rounds["n"] += 1  # next round's exec phase will emit <done>
        return res
    monkeypatch.setattr(ax, "execute", wrapped)

    _loop.run_goal(console, session, "create something", max_rounds=4)
    out = console.file.getvalue()
    assert "continuing toward the goal" in out  # it didn't stop at the first cap
    assert "goal accomplished" in out


def test_goal_command_requires_an_argument(console, session) -> None:
    assert _commands._cmd_goal(console, session, "  ") == "continue"
    assert "usage:" in console.file.getvalue()


def test_goal_command_is_registered() -> None:
    assert "/goal" in _commands.COMMANDS
    assert any("/goal" in cmds for _, cmds in _commands._HELP_GROUPS)
