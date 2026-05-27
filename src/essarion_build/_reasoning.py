"""Reasoning model + reason() entrypoint."""

from __future__ import annotations

from pydantic import BaseModel

from ._context import Context
from ._runtime import Runtime, select_runtime


class Reasoning(BaseModel):
    """Structured output of a reason() call."""

    plan: str
    tradeoffs: str
    verdict: str


def reason(
    task: str,
    *,
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    _runtime: Runtime | None = None,
) -> Reasoning:
    """Run the reasoning loop on `task` against the supplied `context`.

    Returns a Reasoning with `plan`, `tradeoffs`, `verdict`.

    The `_runtime` kwarg is for tests; user code should pass `runtime="lite"|"cloud"`.
    """
    ctx = context if context is not None else Context()
    rt = _runtime or select_runtime(
        runtime=runtime, provider=provider, api_key=api_key, model=model
    )
    fields = rt.reason(task=task, context=ctx)
    return Reasoning(**fields)
