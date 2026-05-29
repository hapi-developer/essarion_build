"""Reasoning model + reason() entrypoint."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ._config import current
from ._context import Context
from ._providers import Usage
from ._runtime import Runtime, select_runtime


class Reasoning(BaseModel):
    """Structured output of a reason() call.

    `usage` aggregates token counts across every provider call the reasoning
    loop made (including any tag-repair retries). Zero counts mean the
    provider didn't report usage. `effort` is the reasoning depth actually
    used — useful when `effort="auto"` resolved the level for you.
    """

    plan: str
    tradeoffs: str
    verdict: str
    usage: Usage = Field(default_factory=Usage)
    effort: str = ""


def reason(
    task: str,
    *,
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    effort: str | None = None,
    _runtime: Runtime | None = None,
) -> Reasoning:
    """Run the reasoning loop on `task` against the supplied `context`.

    Returns a Reasoning with `plan`, `tradeoffs`, `verdict`, `usage`, and
    the `effort` level actually used.

    `effort` controls reasoning depth vs. token cost:
      - "quick"     1 call — plan only (trivial tasks)
      - "standard"  2 calls — plan + self-check (default)
      - "deep"      4 calls — plan + critique + revise + self-check
      - "max"       6 calls — adds an alternative-plan + synthesis round
      - "auto"      a tiny triage call sizes the task, then picks quick/
                    standard/deep automatically (cheap by default, deep
                    only when the task warrants it)

    Per-call kwargs override module defaults set via `configure()`. The
    `_runtime` kwarg is for tests; user code should pass `runtime="lite"|"cloud"`.
    """
    ctx = context if context is not None else Context()
    chosen_effort = effort or current().effort
    rt = _runtime or select_runtime(
        runtime=runtime, provider=provider, api_key=api_key, model=model
    )
    fields = rt.reason(
        task=task, context=ctx, max_tokens=max_tokens, effort=chosen_effort
    )
    return Reasoning(
        plan=fields["plan"],
        tradeoffs=fields["tradeoffs"],
        verdict=fields["verdict"],
        usage=fields.get("usage", Usage()),
        effort=fields.get("effort", chosen_effort),
    )
