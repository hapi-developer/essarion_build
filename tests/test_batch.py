"""Tests for the batch runner."""

from __future__ import annotations

import asyncio

import pytest

from essarion_build import (
    AsyncLiteRuntime,
    AsyncStubProvider,
    BatchResult,
    Context,
    batch_generate,
    batch_reason,
    run_batch,
)


def _plan_resp() -> str:
    return "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>"


def _selfcheck_resp() -> str:
    return "<verdict>ship</verdict>"


def _gen_resps() -> list[str]:
    return [
        _plan_resp(),
        "<code>def x():\n    pass</code>",
        "<verdict>ship</verdict><defense>safe</defense>",
    ]


async def test_batch_reason_runs_each_task_independently() -> None:
    """Two tasks → two stubs (one per task) → two Reasonings."""

    stubs = [
        AsyncStubProvider(responses=[_plan_resp(), _selfcheck_resp()]),
        AsyncStubProvider(responses=[_plan_resp(), _selfcheck_resp()]),
    ]

    # Per-task runtimes via fork: use a custom call site that swaps stubs.
    from essarion_build import _async_api, _batch

    original = _batch.areason
    pool = list(stubs)

    async def fake_areason(task, **kwargs):
        rt = AsyncLiteRuntime(pool.pop(0))
        kwargs["_runtime"] = rt
        return await _async_api.areason(task, **kwargs)

    _batch.areason = fake_areason
    try:
        results = await batch_reason(
            ["task A", "task B"], context=Context(), max_concurrency=2
        )
    finally:
        _batch.areason = original

    assert len(results) == 2
    assert all(r.verdict == "ship" for r in results)
    assert all(s.call_count == 2 for s in stubs)


async def test_batch_generate_runs_each_task_independently() -> None:
    stubs = [AsyncStubProvider(responses=_gen_resps()) for _ in range(3)]
    from essarion_build import _async_api, _batch

    original = _batch.agenerate
    pool = list(stubs)

    async def fake_agenerate(task, **kwargs):
        rt = AsyncLiteRuntime(pool.pop(0))
        kwargs["_runtime"] = rt
        return await _async_api.agenerate(task, **kwargs)

    _batch.agenerate = fake_agenerate
    try:
        results = await batch_generate(
            ["A", "B", "C"], context=Context(), max_concurrency=3
        )
    finally:
        _batch.agenerate = original

    assert len(results) == 3
    assert all("def x" in r.code for r in results)


async def test_batch_failure_does_not_kill_other_tasks() -> None:
    """One task raises; others succeed; result list has Exception in the slot."""
    good = AsyncStubProvider(responses=[_plan_resp(), _selfcheck_resp()])
    bad = AsyncStubProvider(responses=[])  # exhausted → ProviderResponseError

    from essarion_build import _async_api, _batch

    original = _batch.areason
    pool = [good, bad]

    async def fake_areason(task, **kwargs):
        rt = AsyncLiteRuntime(pool.pop(0))
        kwargs["_runtime"] = rt
        return await _async_api.areason(task, **kwargs)

    _batch.areason = fake_areason
    try:
        results = await batch_reason(
            ["good", "bad"], context=Context(), max_concurrency=2
        )
    finally:
        _batch.areason = original

    assert isinstance(results, BatchResult)
    assert len(results.ok) == 1
    assert len(results.errors) == 1


def test_run_batch_sync_helper() -> None:
    """`run_batch(coro)` is the bridge from sync code."""
    stubs = [
        AsyncStubProvider(responses=[_plan_resp(), _selfcheck_resp()]),
        AsyncStubProvider(responses=[_plan_resp(), _selfcheck_resp()]),
    ]
    from essarion_build import _async_api, _batch

    original = _batch.areason
    pool = list(stubs)

    async def fake_areason(task, **kwargs):
        rt = AsyncLiteRuntime(pool.pop(0))
        kwargs["_runtime"] = rt
        return await _async_api.areason(task, **kwargs)

    _batch.areason = fake_areason
    try:
        results = run_batch(
            batch_reason(["A", "B"], context=Context(), max_concurrency=2)
        )
    finally:
        _batch.areason = original

    assert len(results) == 2
