"""Tests for the agent's reasoning-effort integration."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import LiteRuntime, StubProvider
from essarion_build.agent import _loop, _ui
from essarion_build.agent._commands import dispatch
from essarion_build.agent._session import Session, new_session_id
from essarion_build.agent._theme import ESSARION_THEME

PLAN = "<plan>1. base</plan><tradeoffs>- a</tradeoffs><verdict>base</verdict>"
REVISED = "<plan>1. revised</plan><tradeoffs>- b</tradeoffs><verdict>revised</verdict>"
CRITIQUE = "<critique>misses the empty case</critique>"
SELFCHECK = "<verdict>final: ship</verdict>"


@pytest.fixture
def console() -> Console:
    buf = io.StringIO()
    c = Console(theme=ESSARION_THEME, file=buf, force_terminal=False, width=120)
    c._buf = buf
    return c


def _out(c: Console) -> str:
    return c._buf.getvalue()


def _session(tmp_path: Path, effort: str = "auto") -> Session:
    return Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="stub",
        model="stub-model",
        budget_usd=1.00,
        effort=effort,
    )


# -------------------- session defaults --------------------

def test_agent_session_defaults_to_auto(tmp_path: Path) -> None:
    s = _session(tmp_path, effort="auto")
    assert s.effort == "auto"


def test_session_default_effort_field_is_auto(tmp_path: Path) -> None:
    # Construct without specifying effort → agent default.
    s = Session(id="x", cwd=str(tmp_path), provider="stub", model="m")
    assert s.effort == "auto"


# -------------------- /effort command --------------------

def test_effort_command_shows_table(console, tmp_path) -> None:
    dispatch(console, _session(tmp_path), "/effort")
    out = _out(console)
    assert "reasoning effort" in out
    for level in ("quick", "standard", "deep", "max", "auto"):
        assert level in out


def test_effort_command_sets_level(console, tmp_path) -> None:
    s = _session(tmp_path)
    dispatch(console, s, "/effort deep")
    assert s.effort == "deep"
    assert "deep" in _out(console)


def test_effort_command_rejects_unknown(console, tmp_path) -> None:
    s = _session(tmp_path)
    dispatch(console, s, "/effort turbo")
    assert s.effort == "auto"  # unchanged
    assert "unknown effort" in _out(console)


def test_effort_max_warns(console, tmp_path) -> None:
    s = _session(tmp_path)
    dispatch(console, s, "/effort max")
    assert s.effort == "max"
    assert "6 reasoning calls" in _out(console)


# -------------------- loop passes effort through --------------------

def test_run_turn_uses_session_effort_deep(console, tmp_path, monkeypatch) -> None:
    """A deep-effort session runs the critique+revise round in the plan phase."""
    # plan, critique, revise, selfcheck (reason) then draft, selfcheck (generate)
    stub = StubProvider(responses=[
        PLAN, CRITIQUE, REVISED, SELFCHECK,            # plan phase (deep reason)
        PLAN, CRITIQUE, REVISED,                        # plan phase (deep generate)
        "<code>def x(): pass</code>",                   # draft
        "<verdict>ship</verdict><defense>safe</defense>",  # selfcheck
    ])
    monkeypatch.setattr(_loop, "_make_runtime", lambda p, m: LiteRuntime(stub))
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda c: "approve")
    monkeypatch.setattr(_ui, "prompt_approve_apply", lambda c, kind="code": "discard")

    s = _session(tmp_path, effort="deep")
    _loop.run_turn(console, s, "harden the auth path")

    assert s.history
    turn = s.history[0]
    # The revised plan should be what we kept.
    assert "revised" in turn.plan
    assert turn.effort == "deep"


def test_run_turn_quick_is_single_plan_call(console, tmp_path, monkeypatch) -> None:
    """A quick-effort session does plan-only reasoning (no selfcheck) then draft."""
    stub = StubProvider(responses=[
        PLAN,                                           # plan phase reason (quick = plan only)
        PLAN,                                           # plan phase generate (quick = plan only)
        "<code>def x(): pass</code>",                   # draft
        "<verdict>ship</verdict><defense>safe</defense>",  # selfcheck
    ])
    monkeypatch.setattr(_loop, "_make_runtime", lambda p, m: LiteRuntime(stub))
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda c: "approve")
    monkeypatch.setattr(_ui, "prompt_approve_apply", lambda c, kind="code": "discard")

    s = _session(tmp_path, effort="quick")
    _loop.run_turn(console, s, "rename a variable")
    assert s.history[0].effort == "quick"
    assert stub.call_count == 4  # plan(reason) + plan(gen) + draft + selfcheck


def test_auto_effort_announced_in_output(console, tmp_path, monkeypatch) -> None:
    """When effort is auto, the resolved depth is shown to the user."""
    stub = StubProvider(responses=[
        "<complexity>1</complexity><reason>rename</reason>",  # triage (reason)
        PLAN,                                                  # plan (quick)
        "<complexity>1</complexity><reason>rename</reason>",  # triage (generate)
        PLAN,                                                  # plan (quick)
        "<code>x=1</code>",                                    # draft
        "<verdict>ship</verdict><defense>ok</defense>",        # selfcheck
    ])
    monkeypatch.setattr(_loop, "_make_runtime", lambda p, m: LiteRuntime(stub))
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda c: "approve")
    monkeypatch.setattr(_ui, "prompt_approve_apply", lambda c, kind="code": "discard")

    s = _session(tmp_path, effort="auto")
    _loop.run_turn(console, s, "rename x to y")
    out = _out(console)
    assert "reasoning depth" in out
    assert s.history[0].effort == "quick"  # triage sized it down


# -------------------- whoami shows effort --------------------

def test_whoami_shows_effort(console, tmp_path) -> None:
    dispatch(console, _session(tmp_path, effort="deep"), "/whoami")
    out = _out(console)
    assert "reasoning" in out
    assert "deep" in out
