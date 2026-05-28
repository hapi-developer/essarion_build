"""End-to-end tests for the agent's plan-first turn loop.

We drive the loop with a `StubProvider`, mock the approval prompts, and
assert on the rendered output + the recorded session state.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import StubProvider
from essarion_build.agent import _loop, _tools, _ui
from essarion_build.agent._session import Session, new_session_id
from essarion_build.agent._theme import ESSARION_THEME


def _stub_provider_for_plan_and_draft() -> StubProvider:
    """Five scripted responses: plan(3) + selfcheck(1) for reason(),
    then plan(3) + draft(1) + selfcheck(2) for generate()."""
    return StubProvider(
        responses=[
            # reason() — plan
            "<plan>1. validate alg header strictly\n2. verify signature</plan>"
            "<tradeoffs>- chosen: whitelist alg=HS256 only</tradeoffs>"
            "<verdict>preliminary: ship</verdict>",
            # reason() — selfcheck
            "<verdict>final: ship after the whitelist lands</verdict>",
            # generate() — plan
            "<plan>1. validate alg header strictly\n2. verify signature</plan>"
            "<tradeoffs>- chosen: whitelist</tradeoffs>"
            "<verdict>preliminary: ship</verdict>",
            # generate() — draft
            "<code>def verify(token):\n    if header.alg not in ALLOWED_ALGS:\n"
            "        raise InvalidToken('alg not allowed')\n</code>",
            # generate() — selfcheck
            "<verdict>final: ship</verdict><defense>The whitelist closes alg=none.</defense>",
        ]
    )


@pytest.fixture
def headless_console() -> Console:
    """Console that captures into a string buffer (no terminal needed)."""
    buf = io.StringIO()
    return Console(theme=ESSARION_THEME, file=buf, force_terminal=False, width=120)


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="stub",
        model="stub-model",
        budget_usd=1.00,
    )


def test_run_turn_records_a_completed_turn(
    monkeypatch, headless_console: Console, session: Session
) -> None:
    """The full plan-first loop records all five fields on the turn."""
    stub = _stub_provider_for_plan_and_draft()

    # Inject the stub by patching _make_runtime to return a LiteRuntime(stub).
    from essarion_build import LiteRuntime

    monkeypatch.setattr(_loop, "_make_runtime", lambda provider, model: LiteRuntime(stub))

    # Auto-approve the plan and discard the code change (no file writes).
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda console: "approve")
    monkeypatch.setattr(_ui, "prompt_approve_apply", lambda console, kind="code": "discard")

    _loop.run_turn(headless_console, session, "harden JWT alg=none")

    assert len(session.history) == 1
    turn = session.history[0]
    assert "validate alg header" in turn.plan
    assert "whitelist" in turn.tradeoffs
    assert "ALLOWED_ALGS" in turn.code
    assert "whitelist closes alg=none" in turn.defense
    assert stub.call_count == 5


def test_cancel_aborts_before_draft_phase(
    monkeypatch, headless_console: Console, session: Session
) -> None:
    """Cancelling at the plan prompt means generate() is never called."""
    stub = _stub_provider_for_plan_and_draft()
    from essarion_build import LiteRuntime

    monkeypatch.setattr(_loop, "_make_runtime", lambda provider, model: LiteRuntime(stub))
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda console: "cancel")
    monkeypatch.setattr(_ui, "prompt_approve_apply", lambda console, kind="code": "discard")

    _loop.run_turn(headless_console, session, "harden JWT alg=none")

    assert stub.call_count == 2  # reason() ran (plan + selfcheck); generate() did NOT
    assert session.history[0].code == ""


def test_apply_writes_file(
    monkeypatch, headless_console: Console, session: Session, tmp_path: Path
) -> None:
    """Approving the apply step writes the code to the chosen path."""
    stub = _stub_provider_for_plan_and_draft()
    from essarion_build import LiteRuntime

    monkeypatch.setattr(_loop, "_make_runtime", lambda provider, model: LiteRuntime(stub))
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda console: "approve")
    monkeypatch.setattr(_ui, "prompt_approve_apply", lambda console, kind="code": "apply")
    monkeypatch.setattr(_ui, "prompt_text", lambda console, prompt, default="": "out/result.py")

    _tools.bind_tools(tmp_path)
    _loop.run_turn(headless_console, session, "harden JWT alg=none")

    written = (tmp_path / "out" / "result.py").read_text()
    assert "ALLOWED_ALGS" in written
    assert "out/result.py" in session.history[0].files_touched


def test_autoload_files_attaches_referenced_paths(
    monkeypatch, headless_console: Console, session: Session, tmp_path: Path
) -> None:
    """A task that names src/foo.py auto-attaches the file to the Context."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def foo():\n    pass\n")

    stub = _stub_provider_for_plan_and_draft()
    from essarion_build import LiteRuntime

    monkeypatch.setattr(_loop, "_make_runtime", lambda provider, model: LiteRuntime(stub))
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda console: "cancel")  # short-circuit

    _loop.run_turn(headless_console, session, "review src/foo.py for issues")

    # The first stub call should have the file in its system prompt.
    first_system = stub.calls[0]["system"]
    assert "src/foo.py" in first_system
    assert "def foo():" in first_system


def test_workflow_prefix_routes_to_workflow(
    monkeypatch, headless_console: Console, session: Session
) -> None:
    """`review: <target>` runs workflows.review() instead of the plain loop."""
    stub = StubProvider(
        responses=[
            "<plan>1. findings</plan>"
            "<tradeoffs>- chosen: strict review</tradeoffs>"
            "<verdict>do not ship</verdict>",
            "<verdict>final verdict</verdict>",
        ]
    )
    from essarion_build import LiteRuntime

    monkeypatch.setattr(_loop, "_make_runtime", lambda provider, model: LiteRuntime(stub))
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda console: "cancel")
    monkeypatch.setattr(_ui, "prompt_approve_apply", lambda console, kind="code": "discard")

    _loop.run_turn(headless_console, session, "review: src/auth.py")

    assert "findings" in session.history[0].plan


def test_session_budget_meter_updates_on_each_turn(
    monkeypatch, headless_console: Console, session: Session
) -> None:
    from essarion_build._providers import ProviderResponse
    from essarion_build import LiteRuntime, Usage

    # Each scripted response carries a known usage so we can predict the cost.
    stub = StubProvider(
        responses=[
            ProviderResponse(
                text="<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
                usage=Usage(prompt_tokens=1_000_000, total_tokens=1_000_000),
            ),
            ProviderResponse(
                text="<verdict>final</verdict>",
                usage=Usage(prompt_tokens=0, completion_tokens=1_000_000, total_tokens=1_000_000),
            ),
        ]
    )
    monkeypatch.setattr(_loop, "_make_runtime", lambda provider, model: LiteRuntime(stub))
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda console: "cancel")  # plan-only

    # gpt-4o-mini pricing: $0.15/Mtok input, $0.60/Mtok output → 0.15 + 0.60 = 0.75
    session.provider = "openrouter"
    session.model = "openai/gpt-4o-mini"
    _loop.run_turn(headless_console, session, "anything")
    assert abs(session.total_cost_usd - 0.75) < 0.001
