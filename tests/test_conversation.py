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
    # Inject the runtime by monkey-patching reason() via the underlying call.
    # Conversation's own reason/generate must call through select_runtime, so
    # we test by passing a runtime via the public per-call kwarg in reason().
    # The cleanest path is to call reason()/generate() with _runtime through
    # Conversation — but Conversation doesn't expose that. So we test the
    # state-management behaviour instead by patching reason() at module level.
    from essarion_build import _conversation

    rt = LiteRuntime(stub)

    def fake_reason(task, **kwargs):
        kwargs["_runtime"] = rt
        from essarion_build._reasoning import reason as real_reason

        return real_reason(task, **kwargs)

    _conversation._reason = fake_reason  # type: ignore[attr-defined]
    try:
        r1 = conv.reason("design schema")
        r2 = conv.reason("write migration")
    finally:
        from essarion_build._reasoning import reason as real_reason

        _conversation._reason = real_reason  # type: ignore[attr-defined]

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
    from essarion_build import _conversation

    rt = LiteRuntime(stub)

    def fake_reason(task, **kwargs):
        kwargs["_runtime"] = rt
        from essarion_build._reasoning import reason as real_reason

        return real_reason(task, **kwargs)

    _conversation._reason = fake_reason  # type: ignore[attr-defined]
    try:
        r = conv.reason("anything")
    finally:
        from essarion_build._reasoning import reason as real_reason

        _conversation._reason = real_reason  # type: ignore[attr-defined]

    assert r.usage.total_tokens == 22
    assert conv.usage.total_tokens == 22


def test_conversation_fork_is_independent() -> None:
    conv = Conversation(context=Context())
    conv.context.notes.append("original")

    forked = conv.fork()
    forked.context.notes.append("only in fork")

    assert conv.context.notes == ["original"]
    assert forked.context.notes == ["original", "only in fork"]
