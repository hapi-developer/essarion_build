"""Runtime protocol + LiteRuntime (3-step loop) + CloudRuntime (stub)."""

from __future__ import annotations

import re
from typing import Any, Protocol

from ._config import current
from ._context import Context
from ._prompts import (
    DRAFT_INSTRUCTION,
    PLAN_INSTRUCTION,
    SELFCHECK_GENERATE_INSTRUCTION,
    SELFCHECK_REASON_INSTRUCTION,
    SYSTEM_PROMPT,
)
from ._providers import Provider, build_provider
from .exceptions import CloudRuntimeNotAvailable


def _extract_tag(text: str, tag: str) -> str:
    """Extract the body of <tag>...</tag>. Returns empty string if absent."""
    pattern = re.compile(rf"<{tag}>(.*?)</{tag}>", re.DOTALL | re.IGNORECASE)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _build_system(context: Context) -> str:
    """Prepend the frozen system prompt with the rendered context block."""
    block = context.to_prompt_block()
    return f"{SYSTEM_PROMPT}\n\n{block}"


class Runtime(Protocol):
    """The seam essarion_build calls through. v0 has two concrete implementations."""

    def reason(self, *, task: str, context: Context) -> dict[str, str]:
        """Run the reasoning-only loop and return the parsed fields."""
        ...

    def generate(self, *, task: str, context: Context) -> dict[str, str]:
        """Run the full reason-and-draft loop and return the parsed fields."""
        ...


class LiteRuntime:
    """Drives the reasoning loop locally via a single Provider.

    Three steps:
      1. plan     — produces <plan>, <tradeoffs>, <verdict>
      2. draft    — (generate() only) produces <code>
      3. selfcheck — refined <verdict> and (for generate) <defense>
    """

    def __init__(self, provider: Provider) -> None:
        self._provider = provider

    def reason(self, *, task: str, context: Context) -> dict[str, str]:
        cfg = current()
        system = _build_system(context)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": PLAN_INSTRUCTION.format(task=task)},
        ]
        step1 = self._provider.complete(
            system=system, messages=messages, max_tokens=cfg.max_tokens
        )

        messages.append({"role": "assistant", "content": step1})
        messages.append({"role": "user", "content": SELFCHECK_REASON_INSTRUCTION})
        step3 = self._provider.complete(
            system=system, messages=messages, max_tokens=cfg.max_tokens
        )

        # Plan + tradeoffs come from step 1; refined verdict from step 3.
        return {
            "plan": _extract_tag(step1, "plan"),
            "tradeoffs": _extract_tag(step1, "tradeoffs"),
            "verdict": _extract_tag(step3, "verdict") or _extract_tag(step1, "verdict"),
        }

    def generate(self, *, task: str, context: Context) -> dict[str, str]:
        cfg = current()
        system = _build_system(context)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": PLAN_INSTRUCTION.format(task=task)},
        ]
        step1 = self._provider.complete(
            system=system, messages=messages, max_tokens=cfg.max_tokens
        )

        messages.append({"role": "assistant", "content": step1})
        messages.append({"role": "user", "content": DRAFT_INSTRUCTION})
        step2 = self._provider.complete(
            system=system, messages=messages, max_tokens=cfg.max_tokens
        )

        messages.append({"role": "assistant", "content": step2})
        messages.append({"role": "user", "content": SELFCHECK_GENERATE_INSTRUCTION})
        step3 = self._provider.complete(
            system=system, messages=messages, max_tokens=cfg.max_tokens
        )

        return {
            "plan": _extract_tag(step1, "plan"),
            "tradeoffs": _extract_tag(step1, "tradeoffs"),
            "verdict": _extract_tag(step3, "verdict") or _extract_tag(step1, "verdict"),
            "code": _extract_tag(step2, "code"),
            "defense": _extract_tag(step3, "defense"),
        }


class CloudRuntime:
    """Stub runtime that points at the future Essarion Cloud reasoning endpoint."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key
        self._model = model

    def reason(self, *, task: str, context: Context) -> dict[str, str]:
        raise CloudRuntimeNotAvailable(
            "Cloud runtime is coming soon. Use runtime='lite' (default) for now."
        )

    def generate(self, *, task: str, context: Context) -> dict[str, str]:
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
