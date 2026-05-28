"""Tests for adaptive effort in the async runtime (areason/agenerate)."""

from __future__ import annotations

from essarion_build import AsyncLiteRuntime, AsyncStubProvider, Context, areason, agenerate

PLAN = "<plan>1. base</plan><tradeoffs>- a</tradeoffs><verdict>base</verdict>"
REVISED = "<plan>1. revised</plan><tradeoffs>- b</tradeoffs><verdict>revised</verdict>"
CRITIQUE = "<critique>misses the empty case</critique>"
SELFCHECK = "<verdict>final: ship</verdict>"
CODE = "<code>def x(): pass</code>"
SELFCHECK_GEN = "<verdict>ship</verdict><defense>safe</defense>"


async def test_areason_quick_one_call() -> None:
    stub = AsyncStubProvider(responses=[PLAN])
    r = await areason("t", context=Context(), effort="quick", _runtime=AsyncLiteRuntime(stub))
    assert stub.call_count == 1
    assert r.effort == "quick"
    assert "base" in r.plan


async def test_areason_deep_four_calls_revised_wins() -> None:
    stub = AsyncStubProvider(responses=[PLAN, CRITIQUE, REVISED, SELFCHECK])
    r = await areason("t", context=Context(), effort="deep", _runtime=AsyncLiteRuntime(stub))
    assert stub.call_count == 4
    assert "revised" in r.plan
    assert r.effort == "deep"


async def test_areason_auto_triage_routes() -> None:
    stub = AsyncStubProvider(responses=[
        "<complexity>4</complexity>", PLAN, CRITIQUE, REVISED, SELFCHECK,
    ])
    r = await areason("harden auth", context=Context(), effort="auto", _runtime=AsyncLiteRuntime(stub))
    assert stub.call_count == 5  # triage + deep(4)
    assert r.effort == "deep"


async def test_agenerate_deep_five_calls() -> None:
    stub = AsyncStubProvider(responses=[PLAN, CRITIQUE, REVISED, CODE, SELFCHECK_GEN])
    g = await agenerate("t", context=Context(), effort="deep", _runtime=AsyncLiteRuntime(stub))
    assert stub.call_count == 5
    assert "revised" in g.reasoning.plan
    assert g.reasoning.effort == "deep"
    assert g.defense == "safe"
