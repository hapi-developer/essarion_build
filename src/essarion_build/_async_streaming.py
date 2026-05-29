"""Async streaming: yield ReasoningEvent objects as the async loop runs.

Mirrors `_streaming.py` against the async provider protocol. Buffered
async providers emit one `token` event per phase; providers with native
streaming surface chunks (when the provider has a `stream()` method
returning an AsyncIterator[StreamChunk]).
"""

from __future__ import annotations

from typing import AsyncIterator

from ._async_providers import AsyncProvider, build_async_provider
from ._config import current
from ._context import Context
from ._prompts import (
    current_draft,
    current_plan,
    current_selfcheck_generate,
    current_selfcheck_reason,
)
from ._providers import StreamChunk, Usage
from ._runtime import _build_system, _extract_tag, _repair_prompt
from ._streaming import Phase, ReasoningEvent
from .exceptions import ReasoningFormatError


async def _astream_phase(
    *,
    provider: AsyncProvider,
    system: str,
    messages: list[dict],
    max_tokens: int,
    required_tags: list[str],
    phase: Phase,
) -> AsyncIterator[ReasoningEvent]:
    yield ReasoningEvent(kind="phase_start", phase=phase)
    stream = getattr(provider, "stream", None)

    full_text = ""
    phase_usage = Usage()
    if callable(stream):
        async for chunk in stream(
            system=system, messages=messages, max_tokens=max_tokens
        ):
            if chunk.text:
                full_text += chunk.text
                yield ReasoningEvent(kind="token", phase=phase, text=chunk.text)
            if chunk.done:
                phase_usage = chunk.usage
    else:
        response = await provider.complete(
            system=system, messages=messages, max_tokens=max_tokens
        )
        full_text = response.text
        phase_usage = response.usage
        yield ReasoningEvent(kind="token", phase=phase, text=full_text)

    messages.append({"role": "assistant", "content": full_text})
    tags = {t: _extract_tag(full_text, t) for t in required_tags}
    missing = [t for t, body in tags.items() if not body]

    if missing:
        messages.append({"role": "user", "content": _repair_prompt(missing)})
        repair = await provider.complete(
            system=system, messages=messages, max_tokens=max_tokens
        )
        phase_usage = phase_usage + repair.usage
        messages.append({"role": "assistant", "content": repair.text})
        yield ReasoningEvent(kind="token", phase=phase, text=repair.text)
        for tag in missing:
            body = _extract_tag(repair.text, tag)
            if body:
                tags[tag] = body
        still_missing = [t for t, body in tags.items() if not body]
        if still_missing:
            raise ReasoningFormatError(
                f"Model response is still missing required tag(s) after one "
                f"repair pass: {still_missing}. Model={provider.model!r}."
            )

    yield ReasoningEvent(kind="phase_end", phase=phase, text=full_text, tags=tags)
    yield ReasoningEvent(kind="usage", phase=phase, usage=phase_usage)


async def astream_reason(
    task: str,
    *,
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    _provider: AsyncProvider | None = None,
) -> AsyncIterator[ReasoningEvent]:
    """Async sibling of `stream_reason`."""
    cfg = current()
    ctx = context if context is not None else Context()
    prov = _provider or build_async_provider(
        name=provider or cfg.provider,
        api_key=api_key if api_key is not None else cfg.api_key,
        model=model or cfg.model,
    )
    budget = max_tokens if max_tokens is not None else cfg.max_tokens
    system = _build_system(ctx)
    messages: list[dict] = [
        {"role": "user", "content": current_plan().format(task=task)}
    ]
    total_usage = Usage()
    plan_tags: dict[str, str] = {}
    selfcheck_tags: dict[str, str] = {}

    async for ev in _astream_phase(
        provider=prov,
        system=system,
        messages=messages,
        max_tokens=budget,
        required_tags=["plan", "tradeoffs", "verdict"],
        phase="plan",
    ):
        if ev.kind == "phase_end":
            plan_tags = ev.tags
        if ev.kind == "usage":
            total_usage = total_usage + ev.usage
        yield ev

    messages.append({"role": "user", "content": current_selfcheck_reason()})
    async for ev in _astream_phase(
        provider=prov,
        system=system,
        messages=messages,
        max_tokens=budget,
        required_tags=["verdict"],
        phase="selfcheck",
    ):
        if ev.kind == "phase_end":
            selfcheck_tags = ev.tags
        if ev.kind == "usage":
            total_usage = total_usage + ev.usage
        yield ev

    yield ReasoningEvent(
        kind="complete",
        usage=total_usage,
        tags={
            "plan": plan_tags.get("plan", ""),
            "tradeoffs": plan_tags.get("tradeoffs", ""),
            "verdict": selfcheck_tags.get("verdict") or plan_tags.get("verdict", ""),
        },
    )


async def astream_generate(
    task: str,
    *,
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    _provider: AsyncProvider | None = None,
) -> AsyncIterator[ReasoningEvent]:
    """Async sibling of `stream_generate`."""
    cfg = current()
    ctx = context if context is not None else Context()
    prov = _provider or build_async_provider(
        name=provider or cfg.provider,
        api_key=api_key if api_key is not None else cfg.api_key,
        model=model or cfg.model,
    )
    budget = max_tokens if max_tokens is not None else cfg.max_tokens
    system = _build_system(ctx)
    messages: list[dict] = [
        {"role": "user", "content": current_plan().format(task=task)}
    ]
    total_usage = Usage()
    plan_tags: dict[str, str] = {}
    draft_tags: dict[str, str] = {}
    selfcheck_tags: dict[str, str] = {}

    async for ev in _astream_phase(
        provider=prov,
        system=system,
        messages=messages,
        max_tokens=budget,
        required_tags=["plan", "tradeoffs", "verdict"],
        phase="plan",
    ):
        if ev.kind == "phase_end":
            plan_tags = ev.tags
        if ev.kind == "usage":
            total_usage = total_usage + ev.usage
        yield ev

    messages.append({"role": "user", "content": current_draft()})
    async for ev in _astream_phase(
        provider=prov,
        system=system,
        messages=messages,
        max_tokens=budget,
        required_tags=["code"],
        phase="draft",
    ):
        if ev.kind == "phase_end":
            draft_tags = ev.tags
        if ev.kind == "usage":
            total_usage = total_usage + ev.usage
        yield ev

    messages.append({"role": "user", "content": current_selfcheck_generate()})
    async for ev in _astream_phase(
        provider=prov,
        system=system,
        messages=messages,
        max_tokens=budget,
        required_tags=["verdict", "defense"],
        phase="selfcheck",
    ):
        if ev.kind == "phase_end":
            selfcheck_tags = ev.tags
        if ev.kind == "usage":
            total_usage = total_usage + ev.usage
        yield ev

    yield ReasoningEvent(
        kind="complete",
        usage=total_usage,
        tags={
            "plan": plan_tags.get("plan", ""),
            "tradeoffs": plan_tags.get("tradeoffs", ""),
            "verdict": selfcheck_tags.get("verdict") or plan_tags.get("verdict", ""),
            "code": draft_tags.get("code", ""),
            "defense": selfcheck_tags.get("defense", ""),
        },
    )


__all__ = ["astream_reason", "astream_generate"]
