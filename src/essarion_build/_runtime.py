"""Runtime protocol + LiteRuntime (3-step loop) + CloudRuntime (stub)."""

from __future__ import annotations

import re
from typing import Any, Protocol

from ._config import current
from ._context import Context
from ._prompts import (
    current_draft,
    current_plan,
    current_selfcheck_generate,
    current_selfcheck_reason,
    current_system,
)
from ._providers import Provider, Usage, build_provider
from ._telemetry import emit
from .exceptions import CloudRuntimeNotAvailable, ReasoningFormatError


def _extract_tag(text: str, tag: str) -> str:
    """Extract the body of <tag>...</tag>. Returns empty string if absent."""
    pattern = re.compile(rf"<{tag}>(.*?)</{tag}>", re.DOTALL | re.IGNORECASE)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _build_system(context: Context) -> str:
    """Prepend the system prompt with the rendered context block."""
    block = context.to_prompt_block()
    return f"{current_system()}\n\n{block}"


class RuntimeResult(dict[str, Any]):
    """Plain dict that always carries a `usage` Usage entry alongside extracted tags."""


class Runtime(Protocol):
    """The seam essarion_build calls through. v0 has two concrete implementations."""

    def reason(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        """Run the reasoning-only loop and return extracted tags + usage."""
        ...

    def generate(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        """Run the full reason-and-draft loop and return extracted tags + usage."""
        ...


def _repair_prompt(missing: list[str]) -> str:
    """Prompt asking the model to re-emit exactly the missing tags."""
    tag_list = ", ".join(f"<{t}>" for t in missing)
    template = "\n\n".join(
        f"<{t}>(content for {t})</{t}>" for t in missing
    )
    return (
        f"Your previous response was missing the required {tag_list} tag(s). "
        f"Re-emit ONLY the missing tag(s) using exactly this XML structure:\n\n"
        f"{template}"
    )


class LiteRuntime:
    """Drives the reasoning loop locally via a single Provider.

    Three steps:
      1. plan     — produces <plan>, <tradeoffs>, <verdict>
      2. draft    — (generate() only) produces <code>
      3. selfcheck — refined <verdict> and (for generate) <defense>

    If a step's response is missing any required tag, the runtime asks the
    model once to re-emit just the missing tag(s). This is the difference
    between "works on Sonnet" and "works on gpt-4o-mini too" — cheap models
    drop tags more often than you'd like.
    """

    def __init__(self, provider: Provider) -> None:
        self._provider = provider

    def _step(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        usage_accum: list[Usage],
        required_tags: list[str],
        phase: str = "step",
    ) -> dict[str, str]:
        """One provider call + at most one tag-repair pass.

        Returns a {tag: body} dict for every required tag. Mutates `messages`
        to append the assistant response (and the repair exchange, if any) so
        the caller can continue the conversation. Raises ReasoningFormatError
        when the model fails to produce a tag even after the repair pass.
        """
        emit("phase_call", phase=phase, model=self._provider.model)
        first = self._provider.complete(
            system=system, messages=messages, max_tokens=max_tokens
        )
        usage_accum.append(first.usage)
        messages.append({"role": "assistant", "content": first.text})

        tags = {t: _extract_tag(first.text, t) for t in required_tags}
        missing = [t for t, body in tags.items() if not body]
        if not missing:
            emit(
                "phase_done",
                phase=phase,
                tags=list(tags),
                usage=first.usage.model_dump(),
            )
            return tags

        emit("tag_repair_attempt", phase=phase, missing=missing)
        messages.append({"role": "user", "content": _repair_prompt(missing)})
        second = self._provider.complete(
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
            emit("tag_repair_failed", phase=phase, missing=still_missing)
            raise ReasoningFormatError(
                f"Model response is still missing required tag(s) after one "
                f"repair pass: {still_missing}. Model={self._provider.model!r}."
            )
        emit(
            "phase_done",
            phase=phase,
            tags=list(tags),
            repaired=True,
            usage=(first.usage + second.usage).model_dump(),
        )
        return tags

    def reason(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        cfg = current()
        budget = max_tokens if max_tokens is not None else cfg.max_tokens
        system = _build_system(context)
        usage_accum: list[Usage] = []
        emit("loop_start", kind_of_loop="reason", model=self._provider.model)

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": current_plan().format(task=task)},
        ]
        step1 = self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["plan", "tradeoffs", "verdict"],
            phase="plan",
        )

        messages.append({"role": "user", "content": current_selfcheck_reason()})
        step3 = self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["verdict"],
            phase="selfcheck",
        )

        total = sum(usage_accum, Usage())
        emit("loop_done", kind_of_loop="reason", usage=total.model_dump())
        return RuntimeResult(
            plan=step1["plan"],
            tradeoffs=step1["tradeoffs"],
            verdict=step3["verdict"] or step1["verdict"],
            usage=total,
        )

    def generate(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        cfg = current()
        budget = max_tokens if max_tokens is not None else cfg.max_tokens
        system = _build_system(context)
        usage_accum: list[Usage] = []
        emit("loop_start", kind_of_loop="generate", model=self._provider.model)

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": current_plan().format(task=task)},
        ]
        step1 = self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["plan", "tradeoffs", "verdict"],
            phase="plan",
        )

        messages.append({"role": "user", "content": current_draft()})
        step2 = self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["code"],
            phase="draft",
        )

        messages.append({"role": "user", "content": current_selfcheck_generate()})
        step3 = self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["verdict", "defense"],
            phase="selfcheck",
        )

        total = sum(usage_accum, Usage())
        emit("loop_done", kind_of_loop="generate", usage=total.model_dump())
        return RuntimeResult(
            plan=step1["plan"],
            tradeoffs=step1["tradeoffs"],
            verdict=step3["verdict"] or step1["verdict"],
            code=step2["code"],
            defense=step3["defense"],
            usage=total,
        )


class CloudRuntime:
    """Stub runtime that points at the future Essarion Cloud reasoning endpoint."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key
        self._model = model

    def reason(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        raise CloudRuntimeNotAvailable(
            "Cloud runtime is coming soon. Use runtime='lite' (default) for now."
        )

    def generate(
        self, *, task: str, context: Context, max_tokens: int | None = None
    ) -> RuntimeResult:
        raise CloudRuntimeNotAvailable(
            "Cloud runtime is coming soon. Use runtime='lite' (default) for now."
        )


def select_runtime(
    *,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> Runtime:
    """Resolve a Runtime from per-call kwargs falling back to module config."""
    cfg = current()
    chosen_runtime = runtime or cfg.runtime
    chosen_provider = provider or cfg.provider
    chosen_api_key = api_key if api_key is not None else cfg.api_key
    chosen_model = model or cfg.model

    if chosen_runtime == "cloud":
        return CloudRuntime(api_key=chosen_api_key, model=chosen_model)
    if chosen_runtime == "lite":
        prov = build_provider(
            name=chosen_provider, api_key=chosen_api_key, model=chosen_model
        )
        return LiteRuntime(prov)
    raise ValueError(
        f"Unknown runtime {chosen_runtime!r}. Expected 'lite' or 'cloud'."
    )
