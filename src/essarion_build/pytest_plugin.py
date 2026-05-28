"""Pytest plugin: convenient fixtures for testing essarion-build workflows.

Activate by adding `essarion_build.pytest_plugin` to your conftest.py's
`pytest_plugins`:

    # conftest.py
    pytest_plugins = ["essarion_build.pytest_plugin"]

Or list it under `[tool.pytest.ini_options].plugins` in pyproject.toml.

Fixtures provided:

- `essarion_stub`           — fresh StubProvider for each test
- `essarion_async_stub`     — fresh AsyncStubProvider for each test
- `essarion_runtime`        — LiteRuntime(essarion_stub)
- `essarion_async_runtime`  — AsyncLiteRuntime(essarion_async_stub)
- `essarion_context`        — empty Context
- `essarion_skills`         — Context().with_all_skills()
- `isolated_prompts`        — auto-reset prompt overrides per test
- `isolated_telemetry`      — auto-clear telemetry callback per test
- `isolated_providers`      — snapshot/restore the custom-provider registry
"""

from __future__ import annotations

import pytest

from . import (
    AsyncLiteRuntime,
    AsyncStubProvider,
    Context,
    LiteRuntime,
    StubProvider,
    configure_telemetry,
    reset_prompts,
)


@pytest.fixture
def essarion_stub() -> StubProvider:
    """A fresh `StubProvider` with no scripted responses yet — push() them."""
    return StubProvider(responses=[])


@pytest.fixture
def essarion_async_stub() -> AsyncStubProvider:
    """A fresh `AsyncStubProvider` with no scripted responses yet."""
    return AsyncStubProvider(responses=[])


@pytest.fixture
def essarion_runtime(essarion_stub: StubProvider) -> LiteRuntime:
    """A `LiteRuntime` backed by the `essarion_stub` fixture."""
    return LiteRuntime(essarion_stub)


@pytest.fixture
def essarion_async_runtime(
    essarion_async_stub: AsyncStubProvider,
) -> AsyncLiteRuntime:
    return AsyncLiteRuntime(essarion_async_stub)


@pytest.fixture
def essarion_context() -> Context:
    """An empty Context — convenient for skill-injection / repo-add tests."""
    return Context()


@pytest.fixture
def essarion_skills() -> Context:
    """A Context preloaded with every bundled skill."""
    return Context().with_all_skills()


@pytest.fixture(autouse=False)
def isolated_prompts():
    """Reset prompt overrides before and after the test."""
    reset_prompts()
    yield
    reset_prompts()


@pytest.fixture(autouse=False)
def isolated_telemetry():
    """Clear the telemetry callback before and after the test."""
    configure_telemetry(on_event=None, enabled=False)
    yield
    configure_telemetry(on_event=None, enabled=False)


@pytest.fixture(autouse=False)
def isolated_providers():
    """Snapshot and restore both the sync and async provider registries."""
    from . import _async_providers, _providers

    sync_snapshot = dict(_providers._PROVIDER_REGISTRY)
    async_snapshot = dict(_async_providers._ASYNC_PROVIDER_REGISTRY)
    _providers._PROVIDER_REGISTRY.clear()
    _async_providers._ASYNC_PROVIDER_REGISTRY.clear()
    yield
    _providers._PROVIDER_REGISTRY.clear()
    _providers._PROVIDER_REGISTRY.update(sync_snapshot)
    _async_providers._ASYNC_PROVIDER_REGISTRY.clear()
    _async_providers._ASYNC_PROVIDER_REGISTRY.update(async_snapshot)
