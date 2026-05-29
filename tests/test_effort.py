"""Tests for adaptive reasoning effort levels.

Drives the LiteRuntime with a StubProvider and asserts on the number of
provider calls and which plan wins at each effort level. No network.
"""

from __future__ import annotations

import pytest

from essarion_build import (
    Context,
    LiteRuntime,
    StubProvider,
    Usage,
    generate,
    reason,
)
from essarion_build._effort import (
    DEFAULT_EFFORT,
    EFFORT_LEVELS,
    VALID_EFFORTS,
    approx_generate_calls,
    approx_reason_calls,
    effort_for_complexity,
    plan_refinement_steps,
    runs_reason_selfcheck,
    validate_effort,
)

# Reusable tag-complete responses.
PLAN = "<plan>1. base step</plan><tradeoffs>- a</tradeoffs><verdict>base</verdict>"
REVISED = "<plan>1. revised step</plan><tradeoffs>- b</tradeoffs><verdict>revised</verdict>"
ALT = "<plan>1. alt step</plan><tradeoffs>- c</tradeoffs><verdict>alt</verdict>"
SYNTH = "<plan>1. synth step</plan><tradeoffs>- d</tradeoffs><verdict>synth</verdict>"
CRITIQUE = "<critique>the base plan ignores the empty case</critique>"
SELFCHECK = "<verdict>final: ship</verdict>"
CODE = "<code>def x():\n    return 1</code>"
SELFCHECK_GEN = "<verdict>final: ship</verdict><defense>safe</defense>"


# -------------------- pure helpers --------------------

def test_validate_effort_accepts_known() -> None:
    for e in VALID_EFFORTS:
        assert validate_effort(e) == e
    assert validate_effort("DEEP") == "deep"  # case-insensitive


def test_validate_effort_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        validate_effort("turbo")


def test_plan_refinement_steps() -> None:
    assert plan_refinement_steps("quick") == []
    assert plan_refinement_steps("standard") == []
    assert plan_refinement_steps("deep") == ["critique", "revise"]
    assert plan_refinement_steps("max") == ["alt", "synthesize", "critique", "revise"]


def test_runs_reason_selfcheck() -> None:
    assert runs_reason_selfcheck("quick") is False
    assert runs_reason_selfcheck("standard") is True
    assert runs_reason_selfcheck("deep") is True


def test_effort_for_complexity_mapping() -> None:
    assert effort_for_complexity(1) == "quick"
    assert effort_for_complexity(2) == "quick"
    assert effort_for_complexity(3) == "standard"
    assert effort_for_complexity(4) == "deep"
    assert effort_for_complexity(5) == "deep"  # auto never escalates to max


def test_call_count_helpers() -> None:
    assert approx_reason_calls("quick") == 1
    assert approx_reason_calls("standard") == 2
    assert approx_reason_calls("deep") == 4
    assert approx_reason_calls("max") == 6
    assert approx_generate_calls("standard") == 3
    assert approx_generate_calls("deep") == 5
    assert approx_generate_calls("max") == 7


# -------------------- reason() at each effort --------------------

def test_reason_quick_one_call() -> None:
    stub = StubProvider(responses=[PLAN])
    r = reason("t", context=Context(), effort="quick", _runtime=LiteRuntime(stub))
    assert stub.call_count == 1
    assert "base step" in r.plan
    assert r.verdict == "base"  # no selfcheck refinement
    assert r.effort == "quick"


def test_reason_standard_two_calls() -> None:
    stub = StubProvider(responses=[PLAN, SELFCHECK])
    r = reason("t", context=Context(), effort="standard", _runtime=LiteRuntime(stub))
    assert stub.call_count == 2
    assert r.verdict == "final: ship"  # selfcheck refined the verdict
    assert r.effort == "standard"


def test_reason_deep_four_calls_revised_plan_wins() -> None:
    stub = StubProvider(responses=[PLAN, CRITIQUE, REVISED, SELFCHECK])
    r = reason("t", context=Context(), effort="deep", _runtime=LiteRuntime(stub))
    assert stub.call_count == 4
    # The revise step's plan should be the one returned, not the base plan.
    assert "revised step" in r.plan
    assert r.verdict == "final: ship"
    assert r.effort == "deep"


def test_reason_max_six_calls_synthesis_then_revise() -> None:
    stub = StubProvider(
        responses=[PLAN, ALT, SYNTH, CRITIQUE, REVISED, SELFCHECK]
    )
    r = reason("t", context=Context(), effort="max", _runtime=LiteRuntime(stub))
    assert stub.call_count == 6
    # Final plan is the post-critique revision (last plan-producing step).
    assert "revised step" in r.plan
    assert r.effort == "max"


def test_reason_default_is_standard() -> None:
    stub = StubProvider(responses=[PLAN, SELFCHECK])
    r = reason("t", context=Context(), _runtime=LiteRuntime(stub))
    assert stub.call_count == 2
    assert r.effort == DEFAULT_EFFORT == "standard"


# -------------------- auto / triage --------------------

def test_auto_triage_routes_to_deep() -> None:
    # triage says complexity 4 → deep → plan+critique+revise+selfcheck
    stub = StubProvider(
        responses=["<complexity>4</complexity><reason>security</reason>",
                   PLAN, CRITIQUE, REVISED, SELFCHECK]
    )
    r = reason("harden auth", context=Context(), effort="auto", _runtime=LiteRuntime(stub))
    # 1 triage + 4 deep = 5 calls
    assert stub.call_count == 5
    assert r.effort == "deep"
    assert "revised step" in r.plan


def test_auto_triage_routes_to_quick() -> None:
    # triage says complexity 1 → quick → plan only
    stub = StubProvider(
        responses=["<complexity>1</complexity><reason>rename</reason>", PLAN]
    )
    r = reason("rename a var", context=Context(), effort="auto", _runtime=LiteRuntime(stub))
    assert stub.call_count == 2  # triage + plan
    assert r.effort == "quick"


def test_auto_triage_unparseable_defaults_to_standard() -> None:
    # triage output has no digit → defaults to complexity 3 → standard
    stub = StubProvider(
        responses=["I cannot rate this", PLAN, SELFCHECK]
    )
    r = reason("x", context=Context(), effort="auto", _runtime=LiteRuntime(stub))
    assert stub.call_count == 3  # triage + plan + selfcheck
    assert r.effort == "standard"


# -------------------- generate() at each effort --------------------

def test_generate_standard_three_calls() -> None:
    stub = StubProvider(responses=[PLAN, CODE, SELFCHECK_GEN])
    g = generate("t", context=Context(), effort="standard", _runtime=LiteRuntime(stub))
    assert stub.call_count == 3
    assert "def x" in g.code
    assert g.defense == "safe"
    assert g.reasoning.effort == "standard"


def test_generate_deep_five_calls() -> None:
    # plan, critique, revise, draft, selfcheck-with-defense
    stub = StubProvider(responses=[PLAN, CRITIQUE, REVISED, CODE, SELFCHECK_GEN])
    g = generate("t", context=Context(), effort="deep", _runtime=LiteRuntime(stub))
    assert stub.call_count == 5
    assert "revised step" in g.reasoning.plan
    assert "def x" in g.code
    assert g.reasoning.effort == "deep"


def test_generate_quick_three_calls() -> None:
    # generate always drafts + does the code selfcheck; quick just skips
    # plan refinement (there is none for quick anyway).
    stub = StubProvider(responses=[PLAN, CODE, SELFCHECK_GEN])
    g = generate("t", context=Context(), effort="quick", _runtime=LiteRuntime(stub))
    assert stub.call_count == 3
    assert g.reasoning.effort == "quick"


# -------------------- usage accounting honesty --------------------

def test_deep_usage_sums_all_calls() -> None:
    from essarion_build._providers import ProviderResponse

    def r(text: str, n: int) -> ProviderResponse:
        return ProviderResponse(text=text, usage=Usage(total_tokens=n, prompt_tokens=n))

    stub = StubProvider(responses=[
        r(PLAN, 10), r(CRITIQUE, 5), r(REVISED, 12), r(SELFCHECK, 4),
    ])
    res = reason("t", context=Context(), effort="deep", _runtime=LiteRuntime(stub))
    assert res.usage.total_tokens == 10 + 5 + 12 + 4


def test_bad_effort_raises() -> None:
    with pytest.raises(ValueError):
        reason("t", context=Context(), effort="ultra", _runtime=LiteRuntime(StubProvider(responses=[PLAN])))
