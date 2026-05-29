"""Test helpers re-exported for users.

Users wiring essarion_build into their own apps want to write tests against
their `reason()` / `generate()` calls without hitting any real provider. The
`StubProvider` and `AsyncStubProvider` make that easy:

    from essarion_build import Context, reason
    from essarion_build.testing import StubProvider, run_with_stub

    stub = StubProvider(responses=[
        "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>",
        "<verdict>ship</verdict>",
    ])
    r = run_with_stub(stub, lambda: reason("task", context=Context()))
    assert "ship" in r.verdict

Or directly:

    from essarion_build import Context, LiteRuntime, reason
    from essarion_build.testing import StubProvider

    stub = StubProvider(responses=[...])
    r = reason("task", context=Context(), _runtime=LiteRuntime(stub))
"""

from __future__ import annotations

from typing import Callable, TypeVar

from ._async_providers import AsyncStubProvider
from ._async_runtime import AsyncLiteRuntime
from ._providers import StubProvider
from ._runtime import LiteRuntime

T = TypeVar("T")


def run_with_stub(stub: StubProvider, fn: Callable[..., T], *args, **kwargs) -> T:
    """Run `fn` with the LiteRuntime backed by `stub`.

    Assumes `fn` accepts `_runtime` as a keyword argument (true of
    `reason()`, `generate()`, and `Conversation.reason()` / `.generate()`).
    """
    return fn(*args, _runtime=LiteRuntime(stub), **kwargs)


async def arun_with_stub(stub: AsyncStubProvider, fn: Callable[..., T], *args, **kwargs) -> T:
    """Async sibling of `run_with_stub`."""
    return await fn(*args, _runtime=AsyncLiteRuntime(stub), **kwargs)


__all__ = ["StubProvider", "AsyncStubProvider", "run_with_stub", "arun_with_stub"]
