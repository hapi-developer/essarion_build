"""End-to-end: a stub provider emits <tool_call> in its plan; the agent
runs the tool and re-plans with the result in context."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import ProviderResponse, Usage
from essarion_build._providers import _PROVIDER_REGISTRY
from essarion_build.agent import _loop, _ui
from essarion_build.agent._session import Session, new_session_id
from essarion_build.agent._theme import ESSARION_THEME
from essarion_build.agent._tools import bind_tools, register_all


class _ToolCallingProvider:
    """First plan emits a tool_call; second plan (after the tool runs)
    emits a clean plan. The response queue is a CLASS variable so the
    sequence persists across new instances (the agent rebuilds the
    provider each call)."""

    _RESPONSES = [
        # plan 1: includes a tool_call inline. Still has all required tags.
        "<plan>1. read the relevant file "
        "<tool_call name=\"read_file\">{\"path\":\"src/auth.py\"}</tool_call> "
        "2. analyze</plan>"
        "<tradeoffs>- chosen: depth</tradeoffs>"
        "<verdict>preliminary</verdict>",
        # selfcheck 1
        "<verdict>final</verdict>",
        # plan 2 after tool ran: clean plan, no tool calls.
        "<plan>1. verify the function</plan>"
        "<tradeoffs>- chosen: strict</tradeoffs>"
        "<verdict>ship</verdict>",
        # selfcheck 2
        "<verdict>final: ship</verdict>",
    ]

    @classmethod
    def reset(cls):
        cls._idx = 0

    def __init__(self, *, api_key=None, model: str) -> None:
        self.model = model

    def complete(self, *, system, messages, max_tokens):
        if _ToolCallingProvider._idx >= len(_ToolCallingProvider._RESPONSES):
            raise IndexError("provider script exhausted")
        text = _ToolCallingProvider._RESPONSES[_ToolCallingProvider._idx]
        _ToolCallingProvider._idx += 1
        return ProviderResponse(text=text, usage=Usage(prompt_tokens=20, completion_tokens=10, total_tokens=30))


_ToolCallingProvider._idx = 0


@pytest.fixture
def console() -> Console:
    return Console(theme=ESSARION_THEME, file=io.StringIO(), force_terminal=False, width=120)


@pytest.fixture
def session(tmp_path: Path) -> Session:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text(
        "def verify(token):\n    return token == 'ok'\n"
    )
    bind_tools(tmp_path)
    register_all()
    return Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="tool-calling",
        model="m",
        budget_usd=1.00,
        effort="standard",  # deterministic call count
    )


def test_inline_tool_call_triggers_replan(
    monkeypatch, console: Console, session: Session
) -> None:
    _ToolCallingProvider.reset()
    _PROVIDER_REGISTRY["tool-calling"] = lambda *, api_key=None, model: _ToolCallingProvider(
        api_key=api_key, model=model
    )
    try:
        monkeypatch.setattr(_ui, "prompt_approve_plan", lambda c: "cancel")
        monkeypatch.setattr(_ui, "prompt_approve_apply", lambda c, kind="code": "discard")

        _loop.run_turn(console, session, "audit the auth module")

        out = console.file.getvalue()
        # After the inline tool ran, the agent prints "ran N tool call(s)…"
        assert "ran" in out
        assert "tool call" in out
        # And the second plan (clean, no tool calls) is what we end up with.
        assert any("verify the function" in t.plan for t in session.history)
    finally:
        _PROVIDER_REGISTRY.pop("tool-calling", None)
