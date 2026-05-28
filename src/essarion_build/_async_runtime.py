"""Async LiteRuntime — mirrors the sync `LiteRuntime` for `areason()` / `agenerate()`.

Same prompts, same tag-repair logic. Only the provider transport is async.
"""

from __future__ import annotations

from typing import Any, Protocol

from ._async_providers import AsyncProvider, build_async_provider
from ._config import current
from ._context import Context
from ._prompts import (
    current_draft,
    current_plan,
    current_selfcheck_generate,
    current_selfcheck_reason,
)
from ._providers import Usage
from ._runtime import RuntimeResult, _build_system, _extract_tag, _repair_prompt
from .exceptions import CloudRuntimeNotAvailable, ReasoningFormatError


class AsyncRuntime(Protocol):
    async def reason(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        ...

    async def generate(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        ...


class AsyncLiteRuntime:
    """Async sibling of `LiteRuntime`. Drives the same 3-step loop on an `AsyncProvider`."""

    def __init__(self, provider: AsyncProvider) -> None:
        self._provider = provider

    async def _step(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        usage_accum: list[Usage],
        required_tags: list[str],
    ) -> dict[str, str]:
        first = await self._provider.complete(
            system=system, messages=messages, max_tokens=max_tokens
        )
        usage_accum.append(first.usage)
        messages.append({"role": "assistant", "content": first.text})

        tags = {t: _extract_tag(first.text, t) for t in required_tags}
        missing = [t for t, body in tags.items() if not body]
        if not missing:
            return tags

        messages.append({"role": "user", "content": _repair_prompt(missing)})
        second = await self._provider.complete(
            system=system, messages=messages, max_tokens=max_tokens
        )
        usage_accum.append(second.usage)
        messages.append({"role": "assistant", "content": second.text})

        for tag in missing:
            body = _extract_tag(second.text, tag)
            if body:
                tags[tag] = body

        still_missing = [t for t, body in tags.items() if not body]
        if still_missing:
            raise ReasoningFormatError(
                f"Model response is still missing required tag(s) after one "
                f"repair pass: {still_missing}. Model={self._provider.model!r}."
            )
        return tags

    async def reason(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        cfg = current()
        budget = max_tokens if max_tokens is not None else cfg.max_tokens
        system = _build_system(context)
        usage_accum: list[Usage] = []

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": current_plan().format(task=task)},
        ]
        step1 = await self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["plan", "tradeoffs", "verdict"],
        )

        messages.append({"role": "user", "content": current_selfcheck_reason()})
        step3 = await self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["verdict"],
        )

        return RuntimeResult(
            plan=step1["plan"],
            tradeoffs=step1["tradeoffs"],
            verdict=step3["verdict"] or step1["verdict"],
            usage=sum(usage_accum, Usage()),
        )

    async def generate(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        cfg = current()
        budget = max_tokens if max_tokens is not None else cfg.max_tokens
        system = _build_system(context)
        usage_accum: list[Usage] = []

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": current_plan().format(task=task)},
        ]
        step1 = await self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["plan", "tradeoffs", "verdict"],
        )

        messages.append({"role": "user", "content": current_draft()})
        step2 = await self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["code"],
        )

        messages.append({"role": "user", "content": current_selfcheck_generate()})
        step3 = await self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["verdict", "defense"],
        )

        return RuntimeResult(
            plan=step1["plan"],
            tradeoffs=step1["tradeoffs"],
            verdict=step3["verdict"] or step1["verdict"],
            code=step2["code"],
            defense=step3["defense"],
            usage=sum(usage_accum, Usage()),
        )


class AsyncCloudRuntime:
    """Async stub for the future Cloud runtime."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key
        self._model = model

    async def reason(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        raise CloudRuntimeNotAvailable(
            "Cloud runtime is coming soon. Use runtime='lite' (default) for now."
        )

    async def generate(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        raise CloudRuntimeNotAvailable(
            "Cloud runtime is coming soon. Use runtime='lite' (default) for now."
        )


def select_async_runtime(
    *,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> AsyncRuntime:
    """Async sibling of `select_runtime`."""
    cfg = current()
    chosen_runtime = runtime or cfg.runtime
    chosen_provider = provider or cfg.provider
    chosen_api_key = api_key if api_key is not None else cfg.api_key
    chosen_model = model or cfg.model

    if chosen_runtime == "cloud":
        return AsyncCloudRuntime(api_key=chosen_api_key, model=chosen_model)
    if chosen_runtime == "lite":
        prov = build_async_provider(
            name=chosen_provider, api_key=chosen_api_key, model=chosen_model
        )
        return AsyncLiteRuntime(prov)
    raise ValueError(
        f"Unknown runtime {chosen_runtime!r}. Expected 'lite' or 'cloud'."
    )
