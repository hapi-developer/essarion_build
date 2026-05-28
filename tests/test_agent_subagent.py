"""Tests for the parallel-subagent dispatcher."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from essarion_build import Context, ProviderResponse, Usage
from essarion_build._providers import _PROVIDER_REGISTRY
from essarion_build.agent._subagent import (
    SubAgentSpec,
    aggregate_usage,
    run_subagent,
    run_subagents_parallel,
)


# ---------- a deterministic provider we register by name ----------

class _ScriptedProvider:
    """Each call sleeps for `delay` seconds then returns a scripted response.

    Used to verify parallelism: 3 subagents with delay=0.3s should finish in
    ~0.3s if parallel, ~0.9s if serial.
    """

    _shared_lock = threading.Lock()
    _shared_calls: list[float] = []  # timestamps of every call across the test
    _delay = 0.3
    _responses: list[str] = [
        # default scripts; reset per-test
    ]

    def __init__(self, *, api_key=None, model: str) -> None:
        self.model = model

    def complete(self, *, system, messages, max_tokens):
        time.sleep(self._delay)
        with self._shared_lock:
            self._shared_calls.append(time.time())
        # Always return a complete plan + verdict so the runtime doesn't ask
        # for repairs.
        text = (
            "<plan>1. step</plan>"
            "<tradeoffs>- chosen: x</tradeoffs>"
            "<verdict>ship</verdict>"
        )
        return ProviderResponse(text=text, usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


def _install_scripted_provider(monkeypatch, delay: float = 0.3):
    _ScriptedProvider._shared_calls = []
    _ScriptedProvider._delay = delay
    _PROVIDER_REGISTRY["scripted"] = lambda *, api_key=None, model: _ScriptedProvider(
        api_key=api_key, model=model
    )

    def cleanup():
        _PROVIDER_REGISTRY.pop("scripted", None)

    monkeypatch.setattr(
        "essarion_build._providers._PROVIDER_REGISTRY",
        _PROVIDER_REGISTRY,
    )
    # Use a finalizer via the fixture caller; here we just register cleanup.
    import atexit

    atexit.register(cleanup)
    return cleanup


def test_run_subagent_succeeds_and_carries_usage(monkeypatch, tmp_path: Path) -> None:
    _install_scripted_provider(monkeypatch, delay=0.0)
    spec = SubAgentSpec(name="researcher", role="researcher", task="study the repo")
    result = run_subagent(
        spec,
        parent_context=Context(),
        project_cwd=tmp_path,
        parent_provider="scripted",
        parent_model="any",
    )
    assert result.ok
    assert "step" in result.plan
    # reason() = plan + selfcheck = 2 provider calls × 15 tokens each
    assert result.usage.total_tokens == 30
    assert result.mode == "reason"


def test_run_subagent_handles_exceptions(monkeypatch, tmp_path: Path) -> None:
    """An unknown provider should surface as result.error, not raise."""
    spec = SubAgentSpec(name="researcher", role="researcher", task="x")
    result = run_subagent(
        spec,
        parent_context=Context(),
        project_cwd=tmp_path,
        parent_provider="nope",
        parent_model="m",
    )
    assert not result.ok
    assert "nope" in result.error.lower() or "providernotavailable" in result.error.lower()


def test_run_subagents_parallel_runs_in_parallel(monkeypatch, tmp_path: Path) -> None:
    """Three subagents with 0.3s simulated provider delay should finish in
    ~0.3s (parallel), not ~0.9s (serial)."""
    _install_scripted_provider(monkeypatch, delay=0.3)
    specs = [
        SubAgentSpec(name=f"sub{i}", role="researcher", task=f"task {i}")
        for i in range(3)
    ]
    start = time.time()
    results = run_subagents_parallel(
        specs,
        parent_context=Context(),
        project_cwd=tmp_path,
        parent_provider="scripted",
        parent_model="any",
        max_concurrency=3,
    )
    elapsed = time.time() - start
    assert len(results) == 3
    assert all(r.ok for r in results)
    # Tight bound: parallel = ~0.6s for 2 calls (reason mode = plan + selfcheck)
    # at 0.3s each, all running concurrently. Serial would be 1.8s.
    assert elapsed < 1.2, f"expected parallel, took {elapsed:.2f}s"


def test_run_subagents_parallel_preserves_input_order(
    monkeypatch, tmp_path: Path
) -> None:
    _install_scripted_provider(monkeypatch, delay=0.0)
    names = ["alpha", "beta", "gamma", "delta"]
    specs = [
        SubAgentSpec(name=n, role="researcher", task=f"task {n}")
        for n in names
    ]
    results = run_subagents_parallel(
        specs,
        parent_context=Context(),
        project_cwd=tmp_path,
        parent_provider="scripted",
        parent_model="any",
        max_concurrency=4,
    )
    assert [r.name for r in results] == names


def test_run_subagents_one_failure_does_not_kill_others(
    monkeypatch, tmp_path: Path
) -> None:
    """A subagent with an unknown provider fails; the others still complete."""
    _install_scripted_provider(monkeypatch, delay=0.0)
    specs = [
        SubAgentSpec(name="ok1", role="researcher", task="a"),
        SubAgentSpec(name="boom", role="researcher", task="b", provider="nope"),
        SubAgentSpec(name="ok2", role="researcher", task="c"),
    ]
    results = run_subagents_parallel(
        specs,
        parent_context=Context(),
        project_cwd=tmp_path,
        parent_provider="scripted",
        parent_model="any",
        max_concurrency=3,
    )
    assert results[0].ok
    assert not results[1].ok
    assert results[2].ok


def test_aggregate_usage_sums_subagent_usages(monkeypatch, tmp_path: Path) -> None:
    _install_scripted_provider(monkeypatch, delay=0.0)
    specs = [
        SubAgentSpec(name=f"sub{i}", role="researcher", task="x")
        for i in range(3)
    ]
    results = run_subagents_parallel(
        specs,
        parent_context=Context(),
        project_cwd=tmp_path,
        parent_provider="scripted",
        parent_model="any",
    )
    total = aggregate_usage(results)
    # Each subagent runs reason (2 provider calls × 15 total_tokens) = 30
    # × 3 subagents = 90 tokens
    assert total.total_tokens == 90


def test_on_done_callback_fires_per_subagent(monkeypatch, tmp_path: Path) -> None:
    _install_scripted_provider(monkeypatch, delay=0.0)
    specs = [
        SubAgentSpec(name=f"sub{i}", role="researcher", task="x")
        for i in range(3)
    ]
    callback_names: list[str] = []

    def on_done(result):
        callback_names.append(result.name)

    run_subagents_parallel(
        specs,
        parent_context=Context(),
        project_cwd=tmp_path,
        parent_provider="scripted",
        parent_model="any",
        on_done=on_done,
    )
    assert set(callback_names) == {"sub0", "sub1", "sub2"}


def test_role_default_skills_loaded(monkeypatch, tmp_path: Path) -> None:
    """The implementer role inherits its default skill set."""
    _install_scripted_provider(monkeypatch, delay=0.0)

    # Capture the system prompt the scripted provider saw.
    seen: dict = {}

    class _Capturing:
        def __init__(self, *, api_key=None, model: str) -> None:
            self.model = model

        def complete(self, *, system, messages, max_tokens):
            seen["system"] = system
            return ProviderResponse(
                text="<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
                usage=Usage(),
            )

    _PROVIDER_REGISTRY["capture"] = lambda *, api_key=None, model: _Capturing(api_key=api_key, model=model)
    try:
        spec = SubAgentSpec(name="impl", role="implementer", task="x")
        run_subagent(
            spec,
            parent_context=Context(),
            project_cwd=tmp_path,
            parent_provider="capture",
            parent_model="m",
        )
        # implementer's default skill set includes "secure_coding".
        assert "secure_coding" in seen["system"]
    finally:
        _PROVIDER_REGISTRY.pop("capture", None)


def test_implementer_role_runs_generate_not_reason(
    monkeypatch, tmp_path: Path
) -> None:
    """Implementer subagent uses generate() so it produces code."""
    # Scripted responses for generate(): plan, draft, selfcheck.
    class _GenScripted:
        responses = [
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<code>def x(): pass</code>",
            "<verdict>ship</verdict><defense>ok</defense>",
        ]
        index = 0

        def __init__(self, *, api_key=None, model: str) -> None:
            self.model = model

        def complete(self, *, system, messages, max_tokens):
            text = self.responses[self.index]
            self.index += 1
            return ProviderResponse(text=text, usage=Usage(prompt_tokens=5, total_tokens=5))

    _PROVIDER_REGISTRY["genscript"] = lambda *, api_key=None, model: _GenScripted(api_key=api_key, model=model)
    try:
        spec = SubAgentSpec(name="impl", role="implementer", task="write x()")
        result = run_subagent(
            spec,
            parent_context=Context(),
            project_cwd=tmp_path,
            parent_provider="genscript",
            parent_model="m",
        )
        assert result.mode == "generate"
        assert "def x" in result.code
    finally:
        _PROVIDER_REGISTRY.pop("genscript", None)
