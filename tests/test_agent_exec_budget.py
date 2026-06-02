"""Budget-enforcement correctness for the autonomous executor:

* pre-estimate the next step and stop BEFORE crossing the cap (not after);
* fail gracefully with a partial summary instead of nothing;
* an exploration budget that stops "reads forever, answers never".
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import Context, ProviderResponse, Usage
from essarion_build._runtime import LiteRuntime
from essarion_build.agent import _agent_exec
from essarion_build.agent._session import Session, TaskTurn, new_session_id
from essarion_build.agent._theme import ESSARION_THEME
from essarion_build.agent._tools import bind_tools, register_all


def _call(name: str, **args: object) -> str:
    return f'<tool_call name="{name}">{json.dumps(args)}</tool_call>'


@pytest.fixture
def console() -> Console:
    return Console(theme=ESSARION_THEME, file=io.StringIO(), force_terminal=False, width=120)


class _SummaryProvider:
    """Returns a <done> wrap-up on every call, with negligible reported usage.
    Used to prove the budget guard finalizes with a real summary call."""

    def __init__(self, *, model: str = "openai/gpt-4o") -> None:
        self.model = model
        self.call_count = 0
        self.last_messages: list[dict] | None = None

    def complete(self, *, system, messages, max_tokens):
        self.call_count += 1
        self.last_messages = list(messages)
        return ProviderResponse(
            text="<done>Reviewed _loop.py and _runtime.py; out of budget before finishing.</done>",
            usage=Usage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )


def _assert_roles_alternate(messages) -> None:
    """No two consecutive same-role turns — Anthropic rejects that."""
    roles = [m["role"] for m in messages]
    assert all(a != b for a, b in zip(roles, roles[1:])), roles


def test_pre_estimation_stops_before_overrun_and_summarizes(console, tmp_path) -> None:
    """A worst-case next step (huge max_tokens at gpt-4o output prices) cannot fit
    a small cap, so the loop finalizes with a summary BEFORE billing the step."""
    bind_tools(tmp_path)
    register_all()
    session = Session(
        id=new_session_id(), cwd=str(tmp_path),
        provider="openrouter", model="openai/gpt-4o",  # priced: $2.50/$10 per Mtok
        budget_usd=0.50, max_tokens=100_000,  # one full step's output ≈ $1.00 > cap
        effort="quick", autonomous=True,
    )
    prov = _SummaryProvider()
    turn = TaskTurn(task="review the codebase")
    result = _agent_exec.execute(
        console, session, "review the codebase for concurrency bugs", Context(),
        make_runtime=lambda p, m: LiteRuntime(prov), turn=turn,
    )
    out = console.file.getvalue()
    assert result.stopped_reason == "budget"
    assert "budget cap reached" in out
    assert "wrapping up with a summary" in out
    assert "Reviewed _loop.py" in result.summary  # the partial summary survived
    assert prov.call_count == 1  # only the cheap wrap-up call, no full step
    # And we never overran: the only billed call was the tiny summary.
    assert turn.cost_usd < 0.50
    # The wrap-up call must keep roles alternating (no two user turns in a row).
    _assert_roles_alternate(prov.last_messages)


class _OneStepThenBudget:
    """Step 1 reads a file with a big (priced) prompt; the accrued cost then makes
    step 2 unaffordable, forcing finalize after a real action has been taken."""

    def __init__(self, *, model: str = "openai/gpt-4o") -> None:
        self.model = model
        self.calls: list[list[dict]] = []

    def complete(self, *, system, messages, max_tokens):
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            return ProviderResponse(
                text=_call("read_file", path="a.py"),
                usage=Usage(prompt_tokens=80_000, completion_tokens=0, total_tokens=80_000),
            )
        return ProviderResponse(
            text="<done>partial findings</done>",
            usage=Usage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )


def test_finalize_after_action_keeps_roles_alternating(console, tmp_path) -> None:
    """When the cap is hit mid-run, the wrap-up call folds into the trailing user
    turn instead of appending a second one (Anthropic-safe)."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    bind_tools(tmp_path)
    register_all()
    session = Session(
        id=new_session_id(), cwd=str(tmp_path),
        provider="openrouter", model="openai/gpt-4o",
        budget_usd=0.30, max_tokens=10_000, autonomous=True,
    )
    prov = _OneStepThenBudget()
    turn = TaskTurn(task="review")
    result = _agent_exec.execute(
        console, session, "review the code", Context(),
        make_runtime=lambda p, m: LiteRuntime(prov), turn=turn, max_steps=10,
    )
    assert result.stopped_reason == "budget"
    assert len(prov.calls) == 2  # one real step, then the wrap-up
    _assert_roles_alternate(prov.calls[-1])  # would be user,user without the fix
    assert "partial findings" in result.summary


class _ReadProvider:
    """Emits read_file calls forever (until a final <done>). Free/unpriced model,
    so the *exploration* cap — not the dollar cap — is what must bite."""

    def __init__(self, *, model: str = "m") -> None:
        self.model = model
        self.call_count = 0

    def complete(self, *, system, messages, max_tokens):
        self.call_count += 1
        if self.call_count >= 8:
            return ProviderResponse(text="<done>read enough</done>", usage=Usage())
        return ProviderResponse(text=_call("read_file", path="a.py"), usage=Usage())


def test_exploration_cap_fires_nudge(console, tmp_path) -> None:
    """After `read_cap` read-only calls, the loop warns and pushes for an answer."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    bind_tools(tmp_path)
    register_all()
    session = Session(
        id=new_session_id(), cwd=str(tmp_path),
        provider="stub", model="m",  # unpriced → no dollar cap interference
        budget_usd=0.0, read_cap=3, autonomous=True,
    )
    prov = _ReadProvider()
    turn = TaskTurn(task="analyze")
    result = _agent_exec.execute(
        console, session, "analyze the code", Context(),
        make_runtime=lambda p, m: LiteRuntime(prov), turn=turn, max_steps=20,
    )
    out = console.file.getvalue()
    assert "exploration budget reached" in out
    # The cap nudges; it doesn't hard-stop, so the model still finishes cleanly.
    assert result.stopped_reason == "done"


def test_tiny_budget_synthesizes_recap_without_a_call(console, tmp_path) -> None:
    """When there isn't even headroom for a wrap-up call, the recap is synthesized
    from actions taken — no provider call, but still a non-empty summary."""
    bind_tools(tmp_path)
    register_all()
    session = Session(
        id=new_session_id(), cwd=str(tmp_path),
        provider="openrouter", model="openai/gpt-4o",
        budget_usd=1e-9, max_tokens=4096, autonomous=True,
    )
    prov = _SummaryProvider()
    turn = TaskTurn(task="x")
    result = _agent_exec.execute(
        console, session, "do something", Context(),
        make_runtime=lambda p, m: LiteRuntime(prov), turn=turn,
    )
    assert result.stopped_reason == "budget"
    assert prov.call_count == 0  # couldn't afford even the summary call
    assert "Stopped on budget" in result.summary
