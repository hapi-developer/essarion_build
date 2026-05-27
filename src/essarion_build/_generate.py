"""Generation model + generate() entrypoint."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ._context import Context
from ._providers import Usage
from ._reasoning import Reasoning
from ._runtime import Runtime, select_runtime


class Generation(BaseModel):
    """Structured output of a generate() call.

    `reasoning` is the underlying Reasoning that produced the code.
    `defense` is a one-paragraph argument for why the change is safe to ship.
    `usage` aggregates token counts across every provider call (plan + draft +
    selfcheck + any tag-repair retries). The `reasoning.usage` field carries
    the same total — they are two views of the same number.
    """

    code: str
    reasoning: Reasoning
    defense: str
    usage: Usage = Field(default_factory=Usage)


def generate(
    task: str,
    *,
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    _runtime: Runtime | None = None,
) -> Generation:
    """Run the reason-and-draft loop on `task` against `context`.

    Returns a Generation with `code`, `reasoning`, `defense`, and `usage`.

    Per-call kwargs override module defaults set via `configure()`.
    """
    ctx = context if context is not None else Context()
    rt = _runtime or select_runtime(
        runtime=runtime, provider=provider, api_key=api_key, model=model
    )
    fields = rt.generate(task=task, context=ctx, max_tokens=max_tokens)
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
