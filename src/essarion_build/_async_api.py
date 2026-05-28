"""Async entrypoints: `areason()` and `agenerate()`.

Same signatures and return types as the sync versions; the only difference
is `await`.
"""

from __future__ import annotations

from ._async_runtime import AsyncRuntime, select_async_runtime
from ._context import Context
from ._generate import Generation
from ._providers import Usage
from ._reasoning import Reasoning


async def areason(
    task: str,
    *,
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    _runtime: AsyncRuntime | None = None,
) -> Reasoning:
    """Async version of `reason()`. Same semantics; awaitable."""
    ctx = context if context is not None else Context()
    rt = _runtime or select_async_runtime(
        runtime=runtime, provider=provider, api_key=api_key, model=model
    )
    fields = await rt.reason(task=task, context=ctx, max_tokens=max_tokens)
    return Reasoning(
        plan=fields["plan"],
        tradeoffs=fields["tradeoffs"],
        verdict=fields["verdict"],
        usage=fields.get("usage", Usage()),
    )


async def agenerate(
    task: str,
    *,
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    _runtime: AsyncRuntime | None = None,
) -> Generation:
    """Async version of `generate()`. Same semantics; awaitable."""
    ctx = context if context is not None else Context()
    rt = _runtime or select_async_runtime(
        runtime=runtime, provider=provider, api_key=api_key, model=model
    )
    fields = await rt.generate(task=task, context=ctx, max_tokens=max_tokens)
    usage = fields.get("usage", Usage())
    return Generation(
        code=fields["code"],
        reasoning=Reasoning(
            plan=fields["plan"],
            tradeoffs=fields["tradeoffs"],
            verdict=fields["verdict"],
            usage=usage,
        ),
        defense=fields["defense"],
        usage=usage,
    )
