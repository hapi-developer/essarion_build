"""Tests for the multi-turn Conversation class."""

from __future__ import annotations

from essarion_build import (
    Context,
    Conversation,
    LiteRuntime,
    StubProvider,
    Usage,
)
from essarion_build._providers import ProviderResponse


def _plan_response(verdict: str = "ship") -> str:
    return (
        f"<plan>1. do thing</plan>"
        f"<tradeoffs>- option a</tradeoffs>"
        f"<verdict>{verdict}</verdict>"
    )


def test_conversation_records_each_turn() -> None:
    stub = StubProvider(
        responses=[
            _plan_response(),
            "<verdict>final: ship</verdict>",
            _plan_response("preliminary"),
            "<verdict>final: ship</verdict>",
        ]
    )
    conv = Conversation(context=Context())
    # Conversation.reason()/.generate() expose the `_runtime` test seam (same as
    # the top-level reason()/generate()), so a stub-backed runtime drives the
    # turns directly — no module-level monkeypatching required.
    rt = LiteRuntime(stub)
    conv.reason("design schema", _runtime=rt)
    conv.reason("write migration", _runtime=rt)

    assert len(conv.history) == 2
    assert conv.history[0].task == "design schema"
    assert conv.history[1].task == "write migration"
    # Each turn's plan summary should land in context notes.
    assert len(conv.context.notes) == 2
    assert "design schema" in conv.context.notes[0]


def test_conversation_usage_aggregates() -> None:
    stub = StubProvider(
        responses=[
            ProviderResponse(
                text=_plan_response(),
                usage=Usage(prompt_tokens=10, total_tokens=12),
            ),
            ProviderResponse(
                text="<verdict>ship</verdict>",
                usage=Usage(prompt_tokens=8, total_tokens=10),
            ),
        ]
    )
    conv = Conversation(context=Context())
    r = conv.reason("anything", _runtime=LiteRuntime(stub))

    assert r.usage.total_tokens == 22
    assert conv.usage.total_tokens == 22


def test_conversation_fork_is_independent() -> None:
    conv = Conversation(context=Context())
    conv.context.notes.append("original")

    forked = conv.fork()
    forked.context.notes.append("only in fork")

    assert conv.context.notes == ["original"]
    assert forked.context.notes == ["original", "only in fork"]
