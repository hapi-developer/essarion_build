"""Tests for output-gated escalation: auto spends more only when the
model's own verdict flags risk."""

from __future__ import annotations

from essarion_build import Context, LiteRuntime, StubProvider, generate, reason
from essarion_build._effort import verdict_signals_risk

PLAN = "<plan>1. base</plan><tradeoffs>- a</tradeoffs><verdict>base ship</verdict>"
PLAN_RISK = "<plan>1. base</plan><tradeoffs>- a</tradeoffs><verdict>do not ship without resolving the race</verdict>"
REVISED = "<plan>1. revised</plan><tradeoffs>- b</tradeoffs><verdict>revised</verdict>"
CRITIQUE = "<critique>race on the counter</critique>"
SELFCHECK_OK = "<verdict>final: ship</verdict>"
SELFCHECK_RISK = "<verdict>do not ship without resolving the race</verdict>"
CODE = "<code>def x(): pass</code>"
SELFCHECK_GEN_OK = "<verdict>ship</verdict><defense>safe</defense>"


# -------------------- the helper --------------------

def test_verdict_signals_risk() -> None:
    assert verdict_signals_risk("do not ship without resolving X")
    assert verdict_signals_risk("I cannot defend this change")
    assert verdict_signals_risk("DO NOT MERGE this yet")
    assert not verdict_signals_risk("ship it")
    assert not verdict_signals_risk("")


# -------------------- reason() escalation --------------------

def test_auto_escalates_on_risk_verdict() -> None:
    # triage→standard(3); plan; selfcheck says "do not ship" → escalate
    # critique + revise + selfcheck2.
    stub = StubProvider(responses=[
        "<complexity>3</complexity>",  # triage → standard
        PLAN,                           # plan
        SELFCHECK_RISK,                 # selfcheck flags risk
        CRITIQUE,                       # escalation: critique
        REVISED,                        # escalation: revise
        SELFCHECK_OK,                   # escalation: selfcheck2
    ])
    r = reason("harden it", context=Context(), effort="auto", _runtime=LiteRuntime(stub))
    assert stub.call_count == 6
    assert r.effort == "deep"           # escalated label
    assert "revised" in r.plan
    assert r.verdict == "final: ship"


def test_auto_no_escalation_when_verdict_ok() -> None:
    stub = StubProvider(responses=[
        "<complexity>3</complexity>",  # triage → standard
        PLAN,                           # plan
        SELFCHECK_OK,                   # selfcheck OK → no escalation
    ])
    r = reason("simple thing", context=Context(), effort="auto", _runtime=LiteRuntime(stub))
    assert stub.call_count == 3
    assert r.effort == "standard"


def test_explicit_effort_does_not_escalate() -> None:
    # Pinned standard + risk verdict → respect the user's choice, no escalation.
    stub = StubProvider(responses=[PLAN, SELFCHECK_RISK])
    r = reason("x", context=Context(), effort="standard", _runtime=LiteRuntime(stub))
    assert stub.call_count == 2
    assert r.effort == "standard"
    assert verdict_signals_risk(r.verdict)  # still flagged, just not escalated


def test_auto_escalation_bounded_to_once() -> None:
    # Even if the escalated selfcheck ALSO flags risk, stop after one round.
    stub = StubProvider(responses=[
        "<complexity>3</complexity>",  # triage → standard
        PLAN,                           # plan
        SELFCHECK_RISK,                 # selfcheck flags risk → escalate
        CRITIQUE,                       # critique
        REVISED,                        # revise
        SELFCHECK_RISK,                 # escalated selfcheck STILL flags risk
    ])
    r = reason("stubborn", context=Context(), effort="auto", _runtime=LiteRuntime(stub))
    assert stub.call_count == 6  # no second escalation
    assert r.effort == "deep"


def test_auto_quick_escalates_on_plan_risk() -> None:
    # triage→quick(1); plan verdict flags risk (no selfcheck at quick) →
    # escalate critique + revise + selfcheck.
    stub = StubProvider(responses=[
        "<complexity>1</complexity>",  # triage → quick
        PLAN_RISK,                      # plan flags risk (quick: no selfcheck)
        CRITIQUE,                       # escalation critique
        REVISED,                        # escalation revise
        SELFCHECK_OK,                   # escalation selfcheck
    ])
    r = reason("trivial-looking but risky", context=Context(), effort="auto", _runtime=LiteRuntime(stub))
    assert stub.call_count == 5
    assert r.effort == "deep"
    assert "revised" in r.plan


# -------------------- generate() escalation --------------------

def test_generate_auto_escalates_plan_before_draft() -> None:
    # triage→standard; plan verdict flags risk → refine plan (critique+revise)
    # BEFORE drafting, so the draft uses the improved plan.
    stub = StubProvider(responses=[
        "<complexity>3</complexity>",  # triage → standard
        PLAN_RISK,                      # plan flags risk
        CRITIQUE,                       # escalation critique
        REVISED,                        # escalation revise (plan now "revised")
        CODE,                           # draft (from improved plan)
        SELFCHECK_GEN_OK,               # final code selfcheck
    ])
    g = generate("ship a feature", context=Context(), effort="auto", _runtime=LiteRuntime(stub))
    assert stub.call_count == 6
    assert g.reasoning.effort == "deep"
    assert "revised" in g.reasoning.plan
    assert "def x" in g.code


def test_generate_auto_no_escalation_when_plan_ok() -> None:
    stub = StubProvider(responses=[
        "<complexity>3</complexity>",  # triage → standard
        PLAN,                           # plan OK
        CODE,                           # draft
        SELFCHECK_GEN_OK,               # selfcheck
    ])
    g = generate("safe feature", context=Context(), effort="auto", _runtime=LiteRuntime(stub))
    assert stub.call_count == 4
    assert g.reasoning.effort == "standard"
