"""Tests for stream_reason() / stream_generate()."""

from __future__ import annotations

import pytest

from essarion_build import (
    Context,
    ReasoningEvent,
    StreamChunk,
    StubProvider,
    Usage,
    stream_generate,
    stream_reason,
)
from essarion_build._providers import ProviderResponse


def test_stream_reason_emits_phases_with_buffered_provider() -> None:
    stub = StubProvider(
        responses=[
            "<plan>1. do</plan><tradeoffs>- a</tradeoffs><verdict>preliminary</verdict>",
            "<verdict>final: ship</verdict>",
        ]
    )
    events = list(stream_reason("task", context=Context(), _provider=stub))

    phase_starts = [e.phase for e in events if e.kind == "phase_start"]
    phase_ends = [e.phase for e in events if e.kind == "phase_end"]
    assert phase_starts == ["plan", "selfcheck"]
    assert phase_ends == ["plan", "selfcheck"]

    last = events[-1]
    assert last.kind == "complete"
    assert "final: ship" in last.tags["verdict"]


def test_stream_generate_includes_draft_phase() -> None:
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<code>x=1</code>",
            "<verdict>ship</verdict><defense>ok</defense>",
        ]
    )
    events = list(stream_generate("task", context=Context(), _provider=stub))
    phases = [e.phase for e in events if e.kind == "phase_start"]
    assert phases == ["plan", "draft", "selfcheck"]

    last = events[-1]
    assert last.tags["code"] == "x=1"
    assert last.tags["defense"] == "ok"


def test_stream_with_token_capable_provider_emits_token_deltas() -> None:
    """A streaming provider's tokens are surfaced as `token` events."""

    class _StreamingStub:
        model = "stream-stub"

        def __init__(self) -> None:
            self.calls = 0
            self._scripts = [
                [
                    "<plan>1. do",
                    "</plan><tradeoffs>-</tradeoffs>",
                    "<verdict>preliminary</verdict>",
                ],
                ["<verdict>final: ", "ship</verdict>"],
            ]

        def stream(self, *, system, messages, max_tokens):
            chunks = self._scripts[self.calls]
            self.calls += 1
            for c in chunks:
                yield StreamChunk(text=c)
            yield StreamChunk(done=True, usage=Usage(prompt_tokens=1))

        def complete(self, *, system, messages, max_tokens):
            raise AssertionError("complete() should not be called when stream() is available")

    prov = _StreamingStub()
    events = list(stream_reason("task", context=Context(), _provider=prov))
    token_events = [e for e in events if e.kind == "token"]
    # 3 plan chunks + 2 selfcheck chunks = 5
    assert len(token_events) == 5
    assert "".join(t.text for t in token_events if t.phase == "plan") == (
        "<plan>1. do</plan><tradeoffs>-</tradeoffs><verdict>preliminary</verdict>"
    )


def test_stream_repair_pass_when_phase_missing_tag() -> None:
    """A missing tag triggers a repair call; the repair text is also emitted as
    a token event, and the final phase_end has the merged tags."""
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<code>x=1</code>",
            "<verdict>ship</verdict>",  # missing defense
            "<defense>safe</defense>",
        ]
    )
    events = list(stream_generate("task", context=Context(), _provider=stub))
    selfcheck_ends = [e for e in events if e.kind == "phase_end" and e.phase == "selfcheck"]
    assert selfcheck_ends[0].tags["defense"] == "safe"


def test_stream_complete_carries_aggregate_usage() -> None:
    stub = StubProvider(
        responses=[
            ProviderResponse(
                text="<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
                usage=Usage(prompt_tokens=10, total_tokens=12),
            ),
            ProviderResponse(
                text="<verdict>ship</verdict>",
                usage=Usage(prompt_tokens=20, total_tokens=22),
            ),
        ]
    )
    events = list(stream_reason("task", context=Context(), _provider=stub))
    complete = [e for e in events if e.kind == "complete"][0]
    assert complete.usage.total_tokens == 34
