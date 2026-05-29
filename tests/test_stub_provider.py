"""Regression suite for the auto-responding StubProvider.

Motivated by a v0.3.0 usability report: selecting the built-in "stub" provider
(`configure(provider="stub")` or `--provider stub`) raised
`ProviderResponseError: StubProvider exhausted` on the very first call, because
the registry-built stub had no scripted responses and a reasoning loop makes
several provider calls (plan, self-check, draft, …). The report also found that
`run_with_stub(..., conv.reason, ...)` raised `TypeError` even though
`essarion_build.testing` documents that contract.

These tests pin down the fix from every angle so the class of bug can't recur:

- a stub selected by name auto-answers *every* reasoning phase, at every effort
  level, for both `reason()`/`generate()` and the async + CLI surfaces;
- explicitly constructed stubs stay strict (scripted) and still raise an
  *actionable* error when exhausted — the scripting contract is preserved;
- `Conversation.reason()/.generate()` honor the `_runtime` test seam.
"""

from __future__ import annotations

import json

import pytest

from essarion_build import (
    AsyncLiteRuntime,
    Context,
    Conversation,
    LiteRuntime,
    StubProvider,
    agenerate,
    areason,
    build_provider,
    configure,
    generate,
    reason,
)
from essarion_build._async_providers import AsyncStubProvider, build_async_provider
from essarion_build._config import current
from essarion_build._effort import (
    EFFORT_LEVELS,
    approx_generate_calls,
    approx_reason_calls,
    verdict_signals_risk,
)
from essarion_build._prompts import (
    CRITIQUE_PLAN_INSTRUCTION,
    DRAFT_INSTRUCTION,
    PLAN_INSTRUCTION,
    SELFCHECK_GENERATE_INSTRUCTION,
    SELFCHECK_REASON_INSTRUCTION,
    TRIAGE_INSTRUCTION,
)
from essarion_build._providers import _STUB_TAG_BODIES, _STUB_TAG_ORDER
from essarion_build._runtime import _extract_tag
from essarion_build.cli import main
from essarion_build.exceptions import ProviderResponseError
from essarion_build.testing import arun_with_stub, run_with_stub

# Concrete (non-auto) effort levels: deterministic call counts, no triage.
CONCRETE_EFFORTS = list(EFFORT_LEVELS)


@pytest.fixture
def restore_config():
    """Snapshot/restore module config so provider-mutating tests don't leak."""
    cfg = current()
    snap = (cfg.provider, cfg.model, cfg.runtime, cfg.effort, cfg.api_key)
    yield
    cfg.provider, cfg.model, cfg.runtime, cfg.effort, cfg.api_key = snap


# -------------------- the original report scenario, now fixed --------------------

def test_configure_provider_stub_works_out_of_the_box(restore_config) -> None:
    """The exact failing scenario from the report: no scripting required."""
    configure(provider="stub", model="test")
    r = reason("add a hello world function")
    assert r.plan and r.tradeoffs and r.verdict
    g = generate("add a hello world function")
    assert g.code and g.defense and g.reasoning.plan and g.reasoning.verdict


def test_per_call_provider_stub_works() -> None:
    """Per-call `provider="stub"` needs no global config and no scripting."""
    r = reason("anything", provider="stub", model="test")
    assert r.verdict
    g = generate("anything", provider="stub", model="test")
    assert g.code and g.defense


# -------------------- build_provider wiring --------------------

def test_build_provider_stub_is_auto_respond() -> None:
    prov = build_provider(name="stub", api_key=None, model="m")
    assert isinstance(prov, StubProvider)
    assert prov.auto_respond is True


def test_explicit_stub_is_strict_by_default() -> None:
    """Explicit construction stays strict — protects every scripted test."""
    assert StubProvider().auto_respond is False
    assert StubProvider(responses=[]).auto_respond is False
    assert StubProvider(responses=["<plan>x</plan>"]).auto_respond is False


# -------------------- every phase, every effort level --------------------

@pytest.mark.parametrize("effort", CONCRETE_EFFORTS)
def test_auto_stub_answers_every_reason_phase(effort: str) -> None:
    """An auto stub completes reason() at each effort with exactly the loop's
    call count — proving it answered plan/critique/revise/alt/synthesize/
    self-check, whichever the level uses (no tag-repair, no exhaustion)."""
    stub = StubProvider(auto_respond=True)
    r = reason(
        "harden the JWT signature validator",
        context=Context(),
        effort=effort,
        _runtime=LiteRuntime(stub),
    )
    assert r.plan and r.tradeoffs and r.verdict
    assert r.effort == effort
    assert stub.call_count == approx_reason_calls(effort)


@pytest.mark.parametrize("effort", CONCRETE_EFFORTS)
def test_auto_stub_answers_every_generate_phase(effort: str) -> None:
    stub = StubProvider(auto_respond=True)
    g = generate(
        "harden the JWT signature validator",
        context=Context(),
        effort=effort,
        _runtime=LiteRuntime(stub),
    )
    assert g.code and g.defense
    assert g.reasoning.plan and g.reasoning.tradeoffs and g.reasoning.verdict
    assert stub.call_count == approx_generate_calls(effort)


def test_auto_effort_runs_triage_then_resolves(restore_config) -> None:
    """`effort="auto"` runs the triage call, parses the stub's complexity, and
    resolves to a concrete level — auto never escalates to `max`."""
    stub = StubProvider(auto_respond=True)
    r = reason("anything", context=Context(), effort="auto", _runtime=LiteRuntime(stub))
    assert r.effort in ("quick", "standard", "deep")  # auto tops out at deep
    # One extra call beyond the resolved loop accounts for triage.
    assert stub.call_count == approx_reason_calls(r.effort) + 1


# -------------------- phase-awareness of the synthesized response --------------------

def test_auto_response_is_phase_aware() -> None:
    """The stub emits exactly the tags the current instruction asks for, read
    out of the prompt itself — not a kitchen-sink blob."""
    stub = StubProvider(auto_respond=True)

    plan = stub.complete(
        system="sys",
        messages=[{"role": "user", "content": PLAN_INSTRUCTION.format(task="t")}],
        max_tokens=100,
    ).text
    assert "<plan>" in plan and "<tradeoffs>" in plan and "<verdict>" in plan
    assert "<code>" not in plan and "<defense>" not in plan

    draft = stub.complete(
        system="sys",
        messages=[{"role": "user", "content": DRAFT_INSTRUCTION}],
        max_tokens=100,
    ).text
    assert "<code>" in draft and "<plan>" not in draft

    sc_gen = stub.complete(
        system="sys",
        messages=[{"role": "user", "content": SELFCHECK_GENERATE_INSTRUCTION}],
        max_tokens=100,
    ).text
    assert "<verdict>" in sc_gen and "<defense>" in sc_gen

    sc_reason = stub.complete(
        system="sys",
        messages=[{"role": "user", "content": SELFCHECK_REASON_INSTRUCTION}],
        max_tokens=100,
    ).text
    assert "<verdict>" in sc_reason and "<defense>" not in sc_reason

    crit = stub.complete(
        system="sys",
        messages=[{"role": "user", "content": CRITIQUE_PLAN_INSTRUCTION}],
        max_tokens=100,
    ).text
    assert "<critique>" in crit


def test_auto_response_triage_is_parseable() -> None:
    """Triage extracts a 1-5 complexity from the stub's reply."""
    stub = StubProvider(auto_respond=True)
    resp = stub.complete(
        system="s",
        messages=[{"role": "user", "content": TRIAGE_INSTRUCTION.format(task="t")}],
        max_tokens=50,
    )
    body = _extract_tag(resp.text, "complexity")
    assert body.strip() in {"1", "2", "3", "4", "5"}


def test_auto_response_falls_back_to_all_tags_when_no_tags_in_prompt() -> None:
    """Safety net: a fully custom prompt with no XML still gets a parseable,
    all-tags response so the runtime never sees an empty/invalid reply."""
    stub = StubProvider(auto_respond=True)
    resp = stub.complete(
        system="s",
        messages=[{"role": "user", "content": "just write good code please"}],
        max_tokens=10,
    )
    for tag in _STUB_TAG_ORDER:
        assert f"<{tag}>" in resp.text


def test_stub_verdict_never_signals_risk() -> None:
    """The canned verdict must not trip output-gated auto-escalation, or the
    loop would spend extra rounds (and extra scripted slots) unexpectedly."""
    assert not verdict_signals_risk(_STUB_TAG_BODIES["verdict"])


def test_auto_response_reports_nonzero_usage() -> None:
    stub = StubProvider(auto_respond=True)
    resp = stub.complete(
        system="x" * 40,
        messages=[{"role": "user", "content": PLAN_INSTRUCTION.format(task="t")}],
        max_tokens=10,
    )
    assert resp.usage.prompt_tokens > 0
    assert resp.usage.completion_tokens > 0
    assert resp.usage.total_tokens == resp.usage.prompt_tokens + resp.usage.completion_tokens


def test_reason_with_auto_stub_aggregates_usage() -> None:
    stub = StubProvider(auto_respond=True)
    r = reason("anything", context=Context(), effort="standard", _runtime=LiteRuntime(stub))
    assert r.usage.total_tokens > 0


# -------------------- scripted + auto interplay --------------------

def test_auto_stub_serves_scripted_first_then_auto() -> None:
    """Scripted responses win while they last; auto-respond fills the rest."""
    stub = StubProvider(
        responses=[
            "<plan>scripted plan</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>"
        ],
        auto_respond=True,
    )
    r = reason("t", context=Context(), effort="standard", _runtime=LiteRuntime(stub))
    assert "scripted plan" in r.plan  # turn 1 came from the script
    assert r.verdict  # turn 2 (self-check) was auto-answered
    assert stub.call_count == 2


# -------------------- strict mode is preserved (the scripting contract) --------------------

def test_strict_stub_exhausted_raises_actionable() -> None:
    stub = StubProvider(responses=[])
    with pytest.raises(ProviderResponseError) as exc:
        stub.complete(
            system="s",
            messages=[{"role": "user", "content": "<plan></plan>"}],
            max_tokens=1,
        )
    msg = str(exc.value)
    assert "auto_respond=True" in msg
    assert "push" in msg


def test_strict_stub_counts_only_served_calls() -> None:
    stub = StubProvider(responses=["<plan>1</plan>"])
    stub.complete(system="s", messages=[], max_tokens=1)
    assert stub.call_count == 1
    with pytest.raises(ProviderResponseError):
        stub.complete(system="s", messages=[], max_tokens=1)
    assert stub.call_count == 1  # the failed call is not recorded


# -------------------- Conversation: the _runtime test seam --------------------

def test_conversation_reason_accepts_runtime_via_run_with_stub() -> None:
    """The contract `essarion_build.testing` documents: run_with_stub drives a
    Conversation turn. Regression for the reported TypeError."""
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>",
            "<verdict>final: ship</verdict>",
        ]
    )
    conv = Conversation()
    r = run_with_stub(stub, conv.reason, "Hello")
    assert "ship" in r.verdict
    assert len(conv.history) == 1
    assert conv.history[0].task == "Hello"
    assert stub.call_count == 2


def test_conversation_generate_accepts_runtime() -> None:
    stub = StubProvider(auto_respond=True)
    conv = Conversation()
    g = conv.generate("write a parser", _runtime=LiteRuntime(stub))
    assert g.code and g.defense
    assert conv.history[0].kind == "generate"


def test_conversation_with_provider_stub_multi_turn() -> None:
    """Out of the box: a stub-backed Conversation records turns + aggregates
    usage with no scripting and no provider registration."""
    conv = Conversation(provider="stub", model="test")
    conv.reason("design a schema")
    conv.generate("write the migration")
    assert len(conv.history) == 2
    assert conv.usage.total_tokens > 0
    # Each turn's plan summary is threaded into the context for the next turn.
    assert len(conv.context.notes) == 2
    assert "design a schema" in conv.context.notes[0]


# -------------------- async parity --------------------

async def test_build_async_provider_stub_is_auto_respond() -> None:
    prov = build_async_provider(name="stub", api_key=None, model="m")
    assert isinstance(prov, AsyncStubProvider)
    assert prov.auto_respond is True


async def test_areason_agenerate_work_with_stub_out_of_the_box() -> None:
    r = await areason("t", provider="stub", model="test")
    assert r.verdict
    g = await agenerate("t", provider="stub", model="test")
    assert g.code and g.defense


@pytest.mark.parametrize("effort", CONCRETE_EFFORTS)
async def test_async_auto_stub_answers_every_phase(effort: str) -> None:
    stub = AsyncStubProvider(auto_respond=True)
    r = await areason("t", context=Context(), effort=effort, _runtime=AsyncLiteRuntime(stub))
    assert r.plan and r.verdict
    assert stub.call_count == approx_reason_calls(effort)


async def test_async_strict_stub_still_raises() -> None:
    stub = AsyncStubProvider(responses=[])
    with pytest.raises(ProviderResponseError):
        await stub.complete(
            system="s",
            messages=[{"role": "user", "content": "<plan></plan>"}],
            max_tokens=1,
        )


async def test_arun_with_stub_drives_conversation_is_unsupported_gracefully() -> None:
    """Conversation is sync-only; arun_with_stub targets the async top-level
    functions. This pins the async stub helper against areason directly."""
    stub = AsyncStubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>",
            "<verdict>ship</verdict>",
        ]
    )
    r = await arun_with_stub(stub, areason, "t", context=Context())
    assert "ship" in r.verdict


# -------------------- CLI: no monkeypatching needed anymore --------------------

def test_cli_reason_provider_stub_no_patching(capsys) -> None:
    rc = main(
        ["reason", "implement a retry decorator", "--provider", "stub",
         "--model", "test", "--no-skills", "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["plan"] and payload["verdict"]


def test_cli_generate_provider_stub_no_patching(capsys) -> None:
    rc = main(
        ["generate", "implement a retry decorator", "--provider", "stub",
         "--model", "test", "--no-skills", "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["code"] and payload["defense"]
