"""Cross-model second opinion: an INDEPENDENT model red-teams each change,
seeing only the goal + the diff (cheap), and disagreement is surfaced."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import ProviderResponse, Usage
from essarion_build._providers import _PROVIDER_REGISTRY
from essarion_build.agent import _loop
from essarion_build.agent._changes import FileChange, diff_entries
from essarion_build.agent._crosscheck import request_second_opinion
from essarion_build.agent._session import Session, TaskTurn, new_session_id
from essarion_build.agent._theme import ESSARION_THEME
from essarion_build.agent._tools import bind_tools, register_all


@pytest.fixture
def console() -> Console:
    buf = io.StringIO()
    c = Console(theme=ESSARION_THEME, file=buf, force_terminal=False, width=120)
    c._buf = buf
    return c


@pytest.fixture
def session(tmp_path: Path) -> Session:
    bind_tools(tmp_path)
    register_all()
    return Session(
        id=new_session_id(), cwd=str(tmp_path),
        provider="openrouter", model="openai/gpt-4o-mini",
    )


def _out(c: Console) -> str:
    return c._buf.getvalue()


class _Rev:
    """A scripted reviewer provider that records what it was shown."""

    def __init__(self, text: str, model: str = "rev") -> None:
        self._t = text
        self.model = model
        self.seen: str | None = None

    def complete(self, *, system, messages, max_tokens):
        self.seen = messages[0]["content"]
        return ProviderResponse(
            text=self._t, usage=Usage(prompt_tokens=200, completion_tokens=60, total_tokens=260)
        )


# ---- request_second_opinion (parse + token discipline) ----

def test_parse_disagree_with_concerns() -> None:
    op = request_second_opinion(
        _Rev("<agree>no</agree><concerns>\n- a.py:f — race\n- b.py — leak\n</concerns>"
             "<summary>do not ship</summary>"),
        goal="g", change="diff",
    )
    assert op.agree is False
    assert op.disagrees
    assert op.concerns == ["a.py:f — race", "b.py — leak"]


def test_parse_agree_clean() -> None:
    op = request_second_opinion(
        _Rev("<agree>yes</agree><concerns>\nnone\n</concerns><summary>ship</summary>"),
        goal="g", change="c",
    )
    assert op.agree and not op.disagrees and op.concerns == []


def test_agree_but_with_concerns_is_still_surfaced() -> None:
    op = request_second_opinion(
        _Rev("<agree>yes</agree><concerns>\n- nit: naming\n</concerns><summary>ok</summary>"),
        goal="g", change="c",
    )
    assert op.agree and op.disagrees  # concerns present → actionable


def test_only_goal_and_diff_are_sent_not_the_repo() -> None:
    rev = _Rev("<agree>yes</agree>")
    request_second_opinion(rev, goal="THEGOAL", change="THEDIFF")
    assert "THEGOAL" in rev.seen and "THEDIFF" in rev.seen
    # Token discipline: the reviewer prompt is just the goal + the change.
    assert len(rev.seen) < 1000


def test_failed_review_call_is_ok_false_not_raised() -> None:
    class Boom:
        model = "x"

        def complete(self, **k):
            raise RuntimeError("429 rate limited")

    op = request_second_opinion(Boom(), goal="g", change="c")
    assert op.ok is False and "429" in op.error
    assert not op.disagrees  # a failed call doesn't block


# ---- _run_crosscheck (loop helper: charging, render, gating) ----

def test_run_crosscheck_charges_turn_and_renders(console, session, monkeypatch) -> None:
    session.crosscheck_model = "anthropic/claude-haiku-4-5"  # priced on openrouter
    rev = _Rev(
        "<agree>no</agree><concerns>\n- _tools.py:run_shell — command injection\n</concerns>"
        "<summary>do not ship until fixed</summary>",
        model="anthropic/claude-haiku-4-5",
    )
    monkeypatch.setattr(_loop, "build_provider", lambda *, name, api_key, model: rev)
    turn = TaskTurn(task="harden shell")
    op = _loop._run_crosscheck(console, session, "harden shell", "diff --git a/_tools.py", turn)
    assert op is not None and op.disagrees
    assert turn.usage.total_tokens == 260
    assert turn.cost_usd > 0  # the review was metered
    out = _out(console)
    assert "second opinion" in out and "injection" in out


def test_run_crosscheck_off_returns_none(console, session) -> None:
    session.crosscheck_model = None
    assert _loop._run_crosscheck(console, session, "g", "diff", TaskTurn(task="t")) is None


def test_run_crosscheck_skips_when_budget_exhausted(console, session) -> None:
    session.crosscheck_model = "x"
    session.budget_usd = 0.10
    session.total_cost_usd = 0.10
    assert _loop._run_crosscheck(console, session, "g", "diff", TaskTurn(task="t")) is None
    assert "budget" in _out(console)


def test_run_crosscheck_skips_empty_change(console, session) -> None:
    session.crosscheck_model = "x"
    assert _loop._run_crosscheck(console, session, "g", "   ", TaskTurn(task="t")) is None


# ---- diff_entries / diff_since ----

def test_diff_entries_collapses_to_net_change() -> None:
    entries = [
        FileChange(path="a.py", kind="create", before=None, after="x=1\n"),
        FileChange(path="a.py", kind="modify", before="x=1\n", after="x=2\n"),
    ]
    d = diff_entries(entries)
    # create-then-modify collapses to a single creation with the final content.
    assert "b/a.py" in d and "+x=2" in d and "+x=1" not in d
    # created-then-deleted nets to nothing
    assert diff_entries([
        FileChange(path="t", kind="create", before=None, after="z"),
        FileChange(path="t", kind="delete", before="z", after=None),
    ]) == ""


# ---- integration through run_turn_autonomous ----

def _call(name: str, **a) -> str:
    return f'<tool_call name="{name}">{json.dumps(a)}</tool_call>'


class _ScriptProvider:
    """Plan → build → done, then the crosscheck reviewer's disagreement."""

    _RESPONSES = [
        "<plan>1. write app.py</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>",
        _call("write_file", path="app.py", content="import os\nos.system(input())\n"),
        "<done>wrote app.py</done>",
        "<agree>no</agree><concerns>\n- app.py — os.system(input()) is command injection\n"
        "</concerns><summary>do not ship</summary>",
    ]
    _idx = 0

    @classmethod
    def reset(cls) -> None:
        cls._idx = 0

    def __init__(self, *, api_key=None, model) -> None:
        self.model = model

    def complete(self, *, system, messages, max_tokens):
        t = _ScriptProvider._RESPONSES[_ScriptProvider._idx]
        _ScriptProvider._idx += 1
        return ProviderResponse(text=t, usage=Usage(prompt_tokens=20, completion_tokens=10, total_tokens=30))


def test_autonomous_turn_runs_second_opinion(monkeypatch, console, session, tmp_path) -> None:
    _ScriptProvider.reset()
    session.provider = "stub"
    session.model = "m"
    session.crosscheck_model = "reviewer"
    session.effort = "quick"
    monkeypatch.setitem(
        _PROVIDER_REGISTRY, "stub",
        lambda *, api_key=None, model: _ScriptProvider(api_key=api_key, model=model),
    )
    _loop.run_turn_autonomous(console, session, "build an app")
    out = _out(console)
    assert (tmp_path / "app.py").is_file()
    assert "second opinion" in out
    assert "injection" in out
    assert "/fix" in out  # the hint to address the concerns
