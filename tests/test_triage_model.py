"""Cheap-triage de-escalation: the effort='auto' routing call runs on a cheap
model while the real reasoning stays on the capable one."""

from __future__ import annotations

from essarion_build import Context, reason
from essarion_build._runtime import LiteRuntime, select_runtime
from essarion_build._providers import StubProvider


def test_triage_call_routes_to_cheap_provider() -> None:
    main = StubProvider(auto_respond=True, model="big")
    triage = StubProvider(auto_respond=True, model="cheap")
    reason(
        "do a thing", context=Context(),
        _runtime=LiteRuntime(main, triage_provider=triage), effort="auto",
    )
    # Exactly one routing call on the cheap model; the real plan ran on main.
    assert triage.call_count == 1
    assert main.call_count >= 1
    # The triage call was a triage prompt (asks for <complexity>).
    assert "<complexity>" in triage.calls[0]["messages"][-1]["content"]


def test_no_triage_provider_runs_everything_on_main() -> None:
    main = StubProvider(auto_respond=True, model="big")
    reason("do a thing", context=Context(), _runtime=LiteRuntime(main), effort="auto")
    # triage + plan both billed to main (complexity 2 → quick → no selfcheck).
    assert main.call_count == 2


def test_select_runtime_builds_separate_triage_provider() -> None:
    rt = select_runtime(runtime="lite", provider="stub", model="big", triage_model="cheap")
    assert isinstance(rt, LiteRuntime)
    assert rt._triage_provider.model == "cheap"
    assert rt._provider.model == "big"


def test_select_runtime_same_model_shares_provider() -> None:
    rt = select_runtime(runtime="lite", provider="stub", model="big", triage_model="big")
    assert rt._triage_provider is rt._provider


def test_select_runtime_no_triage_model_shares_provider() -> None:
    rt = select_runtime(runtime="lite", provider="stub", model="big")
    assert rt._triage_provider is rt._provider


def test_runtime_for_attaches_session_triage_model() -> None:
    """The loop's `_runtime_for` wires the session's cheap triage model onto the
    runtime that `_make_runtime` (the patch seam) produced."""
    from essarion_build.agent._loop import _runtime_for
    from essarion_build.agent._session import Session, new_session_id

    s = Session(
        id=new_session_id(), cwd=".", provider="stub", model="big",
        triage_model="cheap",
    )
    rt = _runtime_for(s)
    assert rt._provider.model == "big"
    assert rt._triage_provider.model == "cheap"

    s.triage_model = None
    rt2 = _runtime_for(s)
    assert rt2._triage_provider is rt2._provider  # no de-escalation when unset
