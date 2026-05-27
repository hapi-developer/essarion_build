"""Reasoning model + reason() entrypoint."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ._context import Context
from ._providers import Usage
from ._runtime import Runtime, select_runtime


class Reasoning(BaseModel):
    """Structured output of a reason() call.

    `usage` aggregates token counts across every provider call the reasoning
    loop made (including any tag-repair retries). Zero counts mean the
    provider didn't report usage.
    """

    plan: str
    tradeoffs: str
    verdict: str
    usage: Usage = Field(default_factory=Usage)


def reason(
    task: str,
    *,
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    _runtime: Runtime | None = None,
) -> Reasoning:
    """Run the reasoning loop on `task` against the supplied `context`.

    Returns a Reasoning with `plan`, `tradeoffs`, `verdict`, and `usage`.

    Per-call kwargs override module defaults set via `configure()`. The
    `_runtime` kwarg is for tests; user code should pass `runtime="lite"|"cloud"`.
    """
    ctx = context if context is not None else Context()
    rt = _runtime or select_runtime(
        runtime=runtime, provider=provider, api_key=api_key, model=model
    )
    fields = rt.reason(task=task, context=ctx, max_tokens=max_tokens)
    return Reasoning(
        plan=fields["plan"],
        tradeoffs=fields["tradeoffs"],
        verdict=fields["verdict"],
        usage=fields.get("usage", Usage()),
    )
