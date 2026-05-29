"""Multi-turn conversation: chain reason()/generate() calls that share history.

A `Conversation` wraps a Context, a runtime, and a transcript. Each `step()`
runs one reasoning loop against the accumulated context AND the prior
plans/verdicts so the model knows what was already decided.

This is the right abstraction for "iteratively refine a plan", "follow up on
a generation", and "let the model build on its own previous work" — without
the runtime caller having to weave history through Context manually.
"""

from __future__ import annotations

from typing import Iterable, Self

from pydantic import BaseModel, ConfigDict, Field

from ._context import Context
from ._generate import Generation, generate as _generate
from ._providers import Usage
from ._reasoning import Reasoning, reason as _reason
from ._runtime import Runtime


class ConversationTurn(BaseModel):
    """One turn in a conversation: the task, the kind, and the result."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task: str
    kind: str  # "reason" | "generate"
    result: Reasoning | Generation


class Conversation(BaseModel):
    """A stateful multi-turn driver around `reason()` and `generate()`.

    Each `reason()` / `generate()` call appends a note to the underlying
    Context summarizing the prior plan + verdict, so the next call can refer
    back to "the approach we chose last turn" without re-stating it.

    Usage tracking: `usage` aggregates across every turn.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    context: Context = Field(default_factory=Context)
    runtime: str | None = None
    provider: str | None = None
    api_key: str | None = None
    model: str | None = None
    max_tokens: int | None = None
    history: list[ConversationTurn] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)

    def reason(self, task: str, *, _runtime: Runtime | None = None) -> Reasoning:
        """Run a reason() turn. Appends the resulting plan summary to context.

        The `_runtime` kwarg mirrors `reason()` and is for tests — e.g.
        ``run_with_stub(stub, conv.reason, task)``. User code leaves it unset
        and configures the conversation via `provider` / `runtime` / `model`.
        """
        r = _reason(
            task,
            context=self.context,
            runtime=self.runtime,
            provider=self.provider,
            api_key=self.api_key,
            model=self.model,
            max_tokens=self.max_tokens,
            _runtime=_runtime,
        )
        self._record_turn(task=task, kind="reason", result=r)
        return r

    def generate(self, task: str, *, _runtime: Runtime | None = None) -> Generation:
        """Run a generate() turn. Appends the resulting plan + code summary to context.

        See `reason()` for the `_runtime` test seam.
        """
        g = _generate(
            task,
            context=self.context,
            runtime=self.runtime,
            provider=self.provider,
            api_key=self.api_key,
            model=self.model,
            max_tokens=self.max_tokens,
            _runtime=_runtime,
        )
        self._record_turn(task=task, kind="generate", result=g)
        return g

    def _record_turn(
        self, *, task: str, kind: str, result: Reasoning | Generation
    ) -> None:
        self.history.append(ConversationTurn(task=task, kind=kind, result=result))
        self.usage = self.usage + result.usage
        turn_no = len(self.history)
        verdict = (
            result.verdict if isinstance(result, Reasoning) else result.reasoning.verdict
        )
        plan = result.plan if isinstance(result, Reasoning) else result.reasoning.plan
        summary = (
            f"Prior turn {turn_no} ({kind}): task={task!r}. "
            f"Plan: {_truncate(plan, 400)} "
            f"Verdict: {_truncate(verdict, 200)}"
        )
        self.context.notes.append(summary)

    def fork(self) -> "Conversation":
        """Create a deep copy of this conversation. Useful for what-if branches."""
        return Conversation(
            context=self.context.model_copy(deep=True),
            runtime=self.runtime,
            provider=self.provider,
            api_key=self.api_key,
            model=self.model,
            max_tokens=self.max_tokens,
            history=[t.model_copy(deep=True) for t in self.history],
            usage=self.usage.model_copy(deep=True),
        )

    def replay(self) -> Iterable[ConversationTurn]:
        """Iterate over the history in order. Convenience for UIs."""
        return iter(self.history)


def _truncate(text: str, n: int) -> str:
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


__all__ = ["Conversation", "ConversationTurn"]
