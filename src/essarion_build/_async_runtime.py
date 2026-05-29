"""Async LiteRuntime — mirrors the sync `LiteRuntime` for `areason()` / `agenerate()`.

Same prompts, same tag-repair logic. Only the provider transport is async.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from ._async_providers import AsyncProvider, build_async_provider
from ._config import current
from ._context import Context
from ._effort import (
    DEFAULT_EFFORT,
    EFFORT_AUTO,
    EFFORT_DEEP,
    EFFORT_QUICK,
    EFFORT_STANDARD,
    MAX_AUTO_ESCALATIONS,
    effort_for_complexity,
    plan_refinement_steps,
    runs_reason_selfcheck,
    validate_effort,
    verdict_signals_risk,
)
from ._prompts import (
    current_alt_plan,
    current_critique_plan,
    current_draft,
    current_plan,
    current_revise_plan,
    current_selfcheck_generate,
    current_selfcheck_reason,
    current_synthesize_plan,
    current_triage,
)
from ._providers import Usage
from ._runtime import RuntimeResult, _build_system, _extract_tag, _repair_prompt
from .exceptions import CloudRuntimeNotAvailable, ReasoningFormatError


class AsyncRuntime(Protocol):
    async def reason(
        self,
        *,
        task: str,
        context: Context,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> RuntimeResult:
        ...

    async def generate(
        self,
        *,
        task: str,
        context: Context,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> RuntimeResult:
        ...


class AsyncLiteRuntime:
    """Async sibling of `LiteRuntime`. Drives the same 3-step loop on an `AsyncProvider`."""

    def __init__(self, provider: AsyncProvider) -> None:
        self._provider = provider

    async def _step(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        usage_accum: list[Usage],
        required_tags: list[str],
    ) -> dict[str, str]:
        first = await self._provider.complete(
            system=system, messages=messages, max_tokens=max_tokens
        )
        usage_accum.append(first.usage)
        messages.append({"role": "assistant", "content": first.text})

        tags = {t: _extract_tag(first.text, t) for t in required_tags}
        missing = [t for t, body in tags.items() if not body]
        if not missing:
            return tags

        messages.append({"role": "user", "content": _repair_prompt(missing)})
        second = await self._provider.complete(
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
            raise ReasoningFormatError(
                f"Model response is still missing required tag(s) after one "
                f"repair pass: {still_missing}. Model={self._provider.model!r}."
            )
        return tags

    async def _triage(
        self, *, task: str, system: str, budget: int, usage_accum: list[Usage]
    ) -> int:
        """One cheap async classification call. Returns complexity 1..5."""
        triage_budget = min(budget, 256)
        resp = await self._provider.complete(
            system=system,
            messages=[{"role": "user", "content": current_triage().format(task=task)}],
            max_tokens=triage_budget,
        )
        usage_accum.append(resp.usage)
        raw = _extract_tag(resp.text, "complexity") or resp.text
        match = re.search(r"[1-5]", raw)
        n = int(match.group()) if match else 3
        return max(1, min(5, n))

    async def _resolve_effort(
        self, *, task: str, system: str, budget: int,
        usage_accum: list[Usage], effort: str | None,
    ) -> str:
        e = validate_effort(effort or DEFAULT_EFFORT)
        if e != EFFORT_AUTO:
            return e
        complexity = await self._triage(
            task=task, system=system, budget=budget, usage_accum=usage_accum
        )
        return effort_for_complexity(complexity)

    async def _run_plan_phase(
        self, *, system: str, messages: list[dict[str, Any]],
        budget: int, usage_accum: list[Usage], effort: str,
    ) -> tuple[str, str, str]:
        step = await self._step(
            system=system, messages=messages, max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["plan", "tradeoffs", "verdict"],
        )
        plan, tradeoffs, verdict = step["plan"], step["tradeoffs"], step["verdict"]
        for ref in plan_refinement_steps(effort):
            if ref == "critique":
                messages.append({"role": "user", "content": current_critique_plan()})
                await self._step(
                    system=system, messages=messages, max_tokens=budget,
                    usage_accum=usage_accum, required_tags=["critique"],
                )
            elif ref == "revise":
                messages.append({"role": "user", "content": current_revise_plan()})
                r = await self._step(
                    system=system, messages=messages, max_tokens=budget,
                    usage_accum=usage_accum,
                    required_tags=["plan", "tradeoffs", "verdict"],
                )
                plan, tradeoffs, verdict = r["plan"], r["tradeoffs"], r["verdict"]
            elif ref == "alt":
                messages.append({"role": "user", "content": current_alt_plan()})
                await self._step(
                    system=system, messages=messages, max_tokens=budget,
                    usage_accum=usage_accum,
                    required_tags=["plan", "tradeoffs", "verdict"],
                )
            elif ref == "synthesize":
                messages.append({"role": "user", "content": current_synthesize_plan()})
                s = await self._step(
                    system=system, messages=messages, max_tokens=budget,
                    usage_accum=usage_accum,
                    required_tags=["plan", "tradeoffs", "verdict"],
                )
                plan, tradeoffs, verdict = s["plan"], s["tradeoffs"], s["verdict"]
        return plan, tradeoffs, verdict

    async def _escalate_plan_once(
        self, *, system: str, messages: list[dict[str, Any]],
        budget: int, usage_accum: list[Usage],
    ) -> tuple[str, str, str]:
        """One async critique → revise round on the existing plan thread."""
        messages.append({"role": "user", "content": current_critique_plan()})
        await self._step(
            system=system, messages=messages, max_tokens=budget,
            usage_accum=usage_accum, required_tags=["critique"],
        )
        messages.append({"role": "user", "content": current_revise_plan()})
        r = await self._step(
            system=system, messages=messages, max_tokens=budget,
            usage_accum=usage_accum, required_tags=["plan", "tradeoffs", "verdict"],
        )
        return r["plan"], r["tradeoffs"], r["verdict"]

    async def reason(
        self,
        *,
        task: str,
        context: Context,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> RuntimeResult:
        cfg = current()
        budget = max_tokens if max_tokens is not None else cfg.max_tokens
        system = _build_system(context)
        usage_accum: list[Usage] = []

        was_auto = validate_effort(effort or DEFAULT_EFFORT) == EFFORT_AUTO
        resolved = await self._resolve_effort(
            task=task, system=system, budget=budget,
            usage_accum=usage_accum, effort=effort,
        )
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": current_plan().format(task=task)},
        ]
        plan, tradeoffs, verdict = await self._run_plan_phase(
            system=system, messages=messages, budget=budget,
            usage_accum=usage_accum, effort=resolved,
        )
        if runs_reason_selfcheck(resolved):
            messages.append({"role": "user", "content": current_selfcheck_reason()})
            sc = await self._step(
                system=system, messages=messages, max_tokens=budget,
                usage_accum=usage_accum, required_tags=["verdict"],
            )
            verdict = sc["verdict"] or verdict

        escalations = 0
        while (
            was_auto
            and escalations < MAX_AUTO_ESCALATIONS
            and resolved in (EFFORT_QUICK, EFFORT_STANDARD)
            and verdict_signals_risk(verdict)
        ):
            plan, tradeoffs, verdict = await self._escalate_plan_once(
                system=system, messages=messages, budget=budget,
                usage_accum=usage_accum,
            )
            messages.append({"role": "user", "content": current_selfcheck_reason()})
            sc2 = await self._step(
                system=system, messages=messages, max_tokens=budget,
                usage_accum=usage_accum, required_tags=["verdict"],
            )
            verdict = sc2["verdict"] or verdict
            resolved = EFFORT_DEEP
            escalations += 1

        return RuntimeResult(
            plan=plan,
            tradeoffs=tradeoffs,
            verdict=verdict,
            usage=sum(usage_accum, Usage()),
            effort=resolved,
        )

    async def generate(
        self,
        *,
        task: str,
        context: Context,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> RuntimeResult:
        cfg = current()
        budget = max_tokens if max_tokens is not None else cfg.max_tokens
        system = _build_system(context)
        usage_accum: list[Usage] = []

        was_auto = validate_effort(effort or DEFAULT_EFFORT) == EFFORT_AUTO
        resolved = await self._resolve_effort(
            task=task, system=system, budget=budget,
            usage_accum=usage_accum, effort=effort,
        )
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": current_plan().format(task=task)},
        ]
        plan, tradeoffs, verdict = await self._run_plan_phase(
            system=system, messages=messages, budget=budget,
            usage_accum=usage_accum, effort=resolved,
        )

        if (
            was_auto
            and resolved in (EFFORT_QUICK, EFFORT_STANDARD)
            and verdict_signals_risk(verdict)
        ):
            plan, tradeoffs, verdict = await self._escalate_plan_once(
                system=system, messages=messages, budget=budget,
                usage_accum=usage_accum,
            )
            resolved = EFFORT_DEEP

        messages.append({"role": "user", "content": current_draft()})
        step2 = await self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["code"],
        )

        messages.append({"role": "user", "content": current_selfcheck_generate()})
        step3 = await self._step(
            system=system,
            messages=messages,
            max_tokens=budget,
            usage_accum=usage_accum,
            required_tags=["verdict", "defense"],
        )

        return RuntimeResult(
            plan=plan,
            tradeoffs=tradeoffs,
            verdict=step3["verdict"] or verdict,
            code=step2["code"],
            defense=step3["defense"],
            usage=sum(usage_accum, Usage()),
            effort=resolved,
        )


class AsyncCloudRuntime:
    """Async stub for the future Cloud runtime."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key
        self._model = model

    async def reason(
        self,
        *,
        task: str,
        context: Context,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> RuntimeResult:
        raise CloudRuntimeNotAvailable(
            "Cloud runtime is coming soon. Use runtime='lite' (default) for now."
        )

    async def generate(
        self,
        *,
        task: str,
        context: Context,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> RuntimeResult:
        raise CloudRuntimeNotAvailable(
            "Cloud runtime is coming soon. Use runtime='lite' (default) for now."
        )


def select_async_runtime(
    *,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> AsyncRuntime:
    """Async sibling of `select_runtime`."""
    cfg = current()
    chosen_runtime = runtime or cfg.runtime
    chosen_provider = provider or cfg.provider
    chosen_api_key = api_key if api_key is not None else cfg.api_key
    chosen_model = model or cfg.model

    if chosen_runtime == "cloud":
        return AsyncCloudRuntime(api_key=chosen_api_key, model=chosen_model)
    if chosen_runtime == "lite":
        prov = build_async_provider(
            name=chosen_provider, api_key=chosen_api_key, model=chosen_model
        )
        return AsyncLiteRuntime(prov)
    raise ValueError(
        f"Unknown runtime {chosen_runtime!r}. Expected 'lite' or 'cloud'."
    )
