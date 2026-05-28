"""Tests for the async streaming variants (astream_reason / astream_generate)."""

from __future__ import annotations

import pytest

from essarion_build import (
    AsyncStubProvider,
    Context,
    Usage,
    astream_generate,
    astream_reason,
)
from essarion_build._providers import ProviderResponse


async def test_astream_reason_emits_phases() -> None:
    stub = AsyncStubProvider(
        responses=[
            "<plan>1. do</plan><tradeoffs>- a</tradeoffs><verdict>preliminary</verdict>",
            "<verdict>final: ship</verdict>",
        ]
    )
    events = []
    async for ev in astream_reason("task", context=Context(), _provider=stub):
        events.append(ev)

    starts = [e.phase for e in events if e.kind == "phase_start"]
    ends = [e.phase for e in events if e.kind == "phase_end"]
    assert starts == ["plan", "selfcheck"]
    assert ends == ["plan", "selfcheck"]
    last = events[-1]
    assert last.kind == "complete"
    assert "final: ship" in last.tags["verdict"]


async def test_astream_generate_includes_draft_phase() -> None:
    stub = AsyncStubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<code>x=1</code>",
            "<verdict>ship</verdict><defense>ok</defense>",
        ]
    )
    events = []
    async for ev in astream_generate("task", context=Context(), _provider=stub):
        events.append(ev)

    phases = [e.phase for e in events if e.kind == "phase_start"]
    assert phases == ["plan", "draft", "selfcheck"]
    last = events[-1]
    assert last.tags["code"] == "x=1"
    assert last.tags["defense"] == "ok"


async def test_astream_aggregates_usage() -> None:
    stub = AsyncStubProvider(
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
    events = []
    async for ev in astream_reason("task", context=Context(), _provider=stub):
        events.append(ev)
    complete = [e for e in events if e.kind == "complete"][0]
    assert complete.usage.total_tokens == 34


async def test_astream_repair_pass() -> None:
    """A missing tag in the selfcheck triggers a repair call inline."""
    stub = AsyncStubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<code>x=1</code>",
            "<verdict>ship</verdict>",  # missing defense
            "<defense>safe</defense>",
        ]
    )
    events = []
    async for ev in astream_generate("task", context=Context(), _provider=stub):
        events.append(ev)
    selfcheck_ends = [e for e in events if e.kind == "phase_end" and e.phase == "selfcheck"]
    assert selfcheck_ends[0].tags["defense"] == "safe"
