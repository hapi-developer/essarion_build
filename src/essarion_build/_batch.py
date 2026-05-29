"""Run many reason/generate calls concurrently.

The async API gives us natural concurrency: drive N tasks with
`asyncio.gather` and aggregate the results. `batch_reason` / `batch_generate`
is the convenient wrapper.

Use when you have many independent tasks (review every file in a directory,
generate docs for every public function, run plans for every feature in a
backlog). Don't use when tasks depend on each other — use `Conversation`.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Iterable, TypeVar

from ._async_api import agenerate, areason
from ._context import Context
from ._generate import Generation
from ._reasoning import Reasoning

T = TypeVar("T")


class BatchResult(list):
    """A list subclass that also exposes counts of ok/errors."""

    @property
    def ok(self) -> list:
        return [r for r in self if not isinstance(r, Exception)]

    @property
    def errors(self) -> list[Exception]:
        return [r for r in self if isinstance(r, Exception)]


async def _gather(
    coros: list[Awaitable[T]], *, max_concurrency: int
) -> BatchResult:
    sem = asyncio.Semaphore(max_concurrency)

    async def _run(c: Awaitable[T]) -> T | Exception:
        async with sem:
            try:
                return await c
            except Exception as e:  # noqa: BLE001 - we want to surface, not crash the batch
                return e

    results = await asyncio.gather(*(_run(c) for c in coros))
    return BatchResult(results)


async def batch_reason(
    tasks: Iterable[str],
    *,
    context: Context | None = None,
    max_concurrency: int = 4,
    **kwargs,
) -> BatchResult:
    """Run `areason(task)` for each task concurrently. Returns a `BatchResult`
    list with one entry per input task — either a `Reasoning` or an
    `Exception` (one task's failure doesn't fail the rest).
    """
    ctx = context if context is not None else Context()
    coros: list[Awaitable[Reasoning]] = [
        areason(t, context=ctx, **kwargs) for t in tasks
    ]
    return await _gather(coros, max_concurrency=max_concurrency)


async def batch_generate(
    tasks: Iterable[str],
    *,
    context: Context | None = None,
    max_concurrency: int = 4,
    **kwargs,
) -> BatchResult:
    """Run `agenerate(task)` for each task concurrently."""
    ctx = context if context is not None else Context()
    coros: list[Awaitable[Generation]] = [
        agenerate(t, context=ctx, **kwargs) for t in tasks
    ]
    return await _gather(coros, max_concurrency=max_concurrency)


def run_batch(coro: Awaitable[BatchResult]) -> BatchResult:
    """Convenience: drive a batch_* coroutine from synchronous code."""
    return asyncio.run(coro)


__all__ = ["BatchResult", "batch_reason", "batch_generate", "run_batch"]
