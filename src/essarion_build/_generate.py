"""Generation model + generate() entrypoint."""

from __future__ import annotations

from pydantic import BaseModel

from ._context import Context
from ._reasoning import Reasoning
from ._runtime import Runtime, select_runtime


class Generation(BaseModel):
    """Structured output of a generate() call.

    `reasoning` is the underlying Reasoning object that produced the code.
    `defense` is a one-paragraph argument for why the change is safe to ship.
    """

    code: str
    reasoning: Reasoning
    defense: str


def generate(
    task: str,
    *,
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    _runtime: Runtime | None = None,
) -> Generation:
    """Run the reason-and-draft loop on `task` against `context`.

    Returns a Generation with `code`, `reasoning`, `defense`.
    """
    ctx = context if context is not None else Context()
    rt = _runtime or select_runtime(
        runtime=runtime, provider=provider, api_key=api_key, model=model
    )
    fields = rt.generate(task=task, context=ctx)
    return Generation(
        code=fields["code"],
        reasoning=Reasoning(
            plan=fields["plan"],
            tradeoffs=fields["tradeoffs"],
            verdict=fields["verdict"],
        ),
        defense=fields["defense"],
    )
