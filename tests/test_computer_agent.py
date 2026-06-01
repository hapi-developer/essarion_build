"""Computer use wired into the agent: opt-in gating, and a full plan→approve→
act→observe→act turn driven by a scripted provider against a FakeBackend (no
real browser). Proves the browser_* tools flow through the autonomous loop and
the reactive digests come back to the model."""

from __future__ import annotations

import io
import json

import pytest
from rich.console import Console

from essarion_build import ProviderResponse, Usage
from essarion_build._providers import _PROVIDER_REGISTRY
from essarion_build._runtime import LiteRuntime
from essarion_build.agent import _computer, _loop, _ui
from essarion_build.agent._session import Session, new_session_id
from essarion_build.agent._theme import ESSARION_THEME
from essarion_build.agent._tools import bind_tools, register_all
from essarion_build.computer import FakeBackend


def _call(name, **a):
    return f'<tool_call name="{name}">{json.dumps(a)}</tool_call>'


# ---- gating: not default, only obvious phrasing self-activates ----

@pytest.mark.parametrize("task,expected", [
    ("use the computer to test the login flow", True),
    ("open a browser and go to example.com", True),
    ("test it in the browser", True),
    ("control the mouse and click submit", True),
    ("refactor the auth module", False),
    ("write a function that opens a file", False),
    ("compute the browser cache size in code", False),
])
def test_wants_computer_use_is_conservative(task, expected) -> None:
    assert _computer.wants_computer_use(task) is expected


def test_computer_use_active_respects_session_flag() -> None:
    s = Session(id="x", cwd="/tmp", provider="p", model="m")
    assert _computer.computer_use_active(s, "refactor things") is False
    s.computer_use = True
    assert _computer.computer_use_active(s, "refactor things") is True


# ---- full turn through the autonomous loop with a fake browser ----

def _todo_app(be: FakeBackend, name: str, kw: dict) -> None:
    obs = be.observer()
    if name == "navigate":
        obs.push_event("navigation", f"navigated to {kw['url']}", severity="notice")
        obs.push_event("dom", "rendered todo app with empty list", severity="info")
        be.outline = "heading: My Todos\ntextbox: New todo\nbutton: Add"
    elif name == "type_text":
        obs.push_event("dom", f"input value set to {kw['text']!r}", severity="info")
    elif name == "click" and kw.get("selector") == "#add":
        obs.push_event("dom", "added list item: Buy milk", severity="notice")
        obs.push_event("network", "POST /api/todos 201", severity="info")


class _ComputerProvider:
    """Scripted: plan, then drive the fake browser, observing between actions."""

    _RESPONSES = [
        "<plan>1. open app 2. add a todo 3. verify</plan><tradeoffs>n/a</tradeoffs><verdict>ship</verdict>",
        _call("browser_navigate", url="http://localhost:5173", expect="todo app loads with an Add button"),
        _call("browser_type", text="Buy milk", selector="#new", expect="input shows Buy milk"),
        _call("browser_click", selector="#add", expect="a new list item 'Buy milk' appears"),
        "<done>opened the app and added a todo; verified the item rendered</done>",
    ]
    _idx = 0
    systems: list[str] = []

    @classmethod
    def reset(cls):
        cls._idx = 0
        cls.systems = []

    def __init__(self, *, api_key=None, model):
        self.model = model

    def complete(self, *, system, messages, max_tokens):
        _ComputerProvider.systems.append(system)
        text = _ComputerProvider._RESPONSES[_ComputerProvider._idx]
        _ComputerProvider._idx += 1
        return ProviderResponse(text=text, usage=Usage(total_tokens=20))


@pytest.fixture
def console():
    return Console(theme=ESSARION_THEME, file=io.StringIO(), force_terminal=False, width=120)


@pytest.fixture
def session(tmp_path):
    bind_tools(tmp_path)
    register_all()
    return Session(
        id=new_session_id(), cwd=str(tmp_path), provider="stub", model="claude-haiku-4-5",
        budget_usd=1.0, effort="quick", autonomous=True, computer_use=True,
    )


def test_full_computer_use_turn(monkeypatch, console, session) -> None:
    _ComputerProvider.reset()
    monkeypatch.setitem(
        _PROVIDER_REGISTRY, "stub",
        lambda *, api_key=None, model: _ComputerProvider(api_key=api_key, model=model),
    )
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda c: "approve")
    # Inject a fake browser instead of launching Chromium.
    backend = FakeBackend(url="about:blank", on_action=_todo_app)
    _computer.set_backend_factory(lambda: backend)
    try:
        _loop.run_turn_autonomous(console, session, "use the computer to add a todo in the app")
    finally:
        _computer.set_backend_factory(None)

    out = console.file.getvalue()
    # The computer-use protocol was injected into the EXECUTE phase prompt.
    assert any("COMPUTER USE IS ENABLED" in s for s in _ComputerProvider.systems)
    # The browser tools actually drove the fake page through the loop.
    assert "computer use enabled" in out
    assert ("browser_navigate" in out) and ("browser_click" in out)
    # Reactive digests + expectation verdicts surfaced.
    assert "✓ expectation met" in out
    assert "added list item: Buy milk" in out
    # The backend was driven and then cleaned up.
    assert ("navigate", {"url": "http://localhost:5173"}) in backend.actions
    assert backend.closed is True


def test_backend_failure_is_surfaced_not_crashed(monkeypatch, console, session) -> None:
    _ComputerProvider.reset()
    # Provider that just finishes, so the turn completes even if browser fails.
    monkeypatch.setitem(
        _PROVIDER_REGISTRY, "stub",
        lambda *, api_key=None, model: type("P", (), {
            "model": model,
            "complete": lambda self, *, system, messages, max_tokens: ProviderResponse(
                text="<plan>p</plan><tradeoffs>t</tradeoffs><verdict>v</verdict>"
                if "GOAL" not in messages[-1]["content"] else "<done>nothing to do</done>",
                usage=Usage(total_tokens=5),
            ),
        })(),
    )
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda c: "approve")

    def _boom():
        raise RuntimeError("chromium not installed")

    _computer.set_backend_factory(_boom)
    try:
        _loop.run_turn_autonomous(console, session, "use the computer to do a thing")
    finally:
        _computer.set_backend_factory(None)
    assert "could not start" in console.file.getvalue()
