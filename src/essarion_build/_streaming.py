"""Streaming entrypoint: yield progress events as the reasoning loop runs.

The 3-step loop has natural boundaries — plan, draft, selfcheck. Streaming
exposes those as `ReasoningEvent` objects so callers can render progress
("plan: 1. validate alg header…") in real time without waiting for the full
3 calls to complete.

This is a coarser stream than token-level streaming. It works against any
provider's `complete()` — no need for a streaming-capable provider — and it
is what most UIs actually want (one update per phase, not per token).

For providers that implement `StreamingProvider.stream()`, callers get
token-level chunks inside each phase too.
"""

from __future__ import annotations

from typing import Iterator, Literal

from pydantic import BaseModel, Field

from ._config import current
from ._context import Context
from ._prompts import (
    DRAFT_INSTRUCTION,
    PLAN_INSTRUCTION,
    SELFCHECK_GENERATE_INSTRUCTION,
    SELFCHECK_REASON_INSTRUCTION,
)
from ._providers import Provider, Usage, build_provider
from ._runtime import _build_system, _extract_tag, _repair_prompt
from .exceptions import ReasoningFormatError


Phase = Literal["plan", "draft", "selfcheck"]
EventKind = Literal["phase_start", "token", "phase_end", "usage", "complete"]


class ReasoningEvent(BaseModel):
    """A single event in a streamed reason() / generate() run.

    - `phase_start` — a new phase ("plan" / "draft" / "selfcheck") is starting.
    - `token`       — a partial text chunk inside the current phase. Only
                      emitted when the provider supports token-level streaming;
                      buffered providers emit one `token` event with the full
                      response per phase.
    - `phase_end`   — the current phase's response is complete. `text` holds
                      the full assembled response, `tags` holds the extracted
                      structured fields.
    - `usage`       — token usage update for the just-finished phase.
    - `complete`    — terminal event with cumulative `usage`.
    """

    kind: EventKind
    phase: Phase | None = None
    text: str = ""
    tags: dict[str, str] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)


def _stream_phase(
    *,
    provider: Provider,
    system: str,
    messages: list[dict],
    max_tokens: int,
    required_tags: list[str],
    phase: Phase,
) -> Iterator[ReasoningEvent]:
    """Run one phase, streaming token events when the provider supports it.

    Mutates `messages` to append the assistant turn (and the repair exchange,
    if any). Yields events for the caller. Falls back to buffered `complete()`
    when the provider has no `stream` method.

    Emits, in order:
      - phase_start
      - >=1 token events
      - phase_end (with text + extracted tags)
      - usage
      - any repair exchange uses the same shape
    """
    yield ReasoningEvent(kind="phase_start", phase=phase)
    stream = getattr(provider, "stream", None)

    full_text = ""
    phase_usage = Usage()
    if callable(stream):
        for chunk in stream(system=system, messages=messages, max_tokens=max_tokens):
            if chunk.text:
                full_text += chunk.text
                yield ReasoningEvent(kind="token", phase=phase, text=chunk.text)
            if chunk.done:
                phase_usage = chunk.usage
    else:
        response = provider.complete(
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
        repair = provider.complete(
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


def stream_reason(
    task: str,
    *,
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    _provider: Provider | None = None,
) -> Iterator[ReasoningEvent]:
    """Stream a `reason()` run as a sequence of ReasoningEvents.

    Buffered providers emit one `token` per phase (with the full response);
    streaming providers emit fine-grained token deltas. Either way the caller
    sees `phase_start`/`phase_end` so UIs can render progress.
    """
    cfg = current()
    ctx = context if context is not None else Context()
    prov = _provider or build_provider(
        name=provider or cfg.provider,
        api_key=api_key if api_key is not None else cfg.api_key,
        model=model or cfg.model,
    )
    budget = max_tokens if max_tokens is not None else cfg.max_tokens
    system = _build_system(ctx)
    messages: list[dict] = [
        {"role": "user", "content": PLAN_INSTRUCTION.format(task=task)}
    ]
    total_usage = Usage()
    plan_tags: dict[str, str] = {}
    selfcheck_tags: dict[str, str] = {}

    for ev in _stream_phase(
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

    messages.append({"role": "user", "content": SELFCHECK_REASON_INSTRUCTION})
    for ev in _stream_phase(
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


def stream_generate(
    task: str,
    *,
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    _provider: Provider | None = None,
) -> Iterator[ReasoningEvent]:
    """Stream a `generate()` run. Same as stream_reason but with a draft phase."""
    cfg = current()
    ctx = context if context is not None else Context()
    prov = _provider or build_provider(
        name=provider or cfg.provider,
        api_key=api_key if api_key is not None else cfg.api_key,
        model=model or cfg.model,
    )
    budget = max_tokens if max_tokens is not None else cfg.max_tokens
    system = _build_system(ctx)
    messages: list[dict] = [
        {"role": "user", "content": PLAN_INSTRUCTION.format(task=task)}
    ]
    total_usage = Usage()
    plan_tags: dict[str, str] = {}
    draft_tags: dict[str, str] = {}
    selfcheck_tags: dict[str, str] = {}

    for ev in _stream_phase(
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

    messages.append({"role": "user", "content": DRAFT_INSTRUCTION})
    for ev in _stream_phase(
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

    messages.append({"role": "user", "content": SELFCHECK_GENERATE_INSTRUCTION})
    for ev in _stream_phase(
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
