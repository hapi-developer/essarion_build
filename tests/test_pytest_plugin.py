"""Tests that the pytest plugin's fixtures are usable."""

from __future__ import annotations

import pytest

from essarion_build import AsyncLiteRuntime, AsyncStubProvider, Context, LiteRuntime, StubProvider

pytest_plugins = ["essarion_build.pytest_plugin"]


def test_essarion_stub_fixture(essarion_stub: StubProvider) -> None:
    assert isinstance(essarion_stub, StubProvider)
    assert essarion_stub.call_count == 0


def test_essarion_runtime_uses_stub_fixture(
    essarion_runtime: LiteRuntime, essarion_stub: StubProvider
) -> None:
    essarion_stub.push("<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>")
    essarion_stub.push("<verdict>ship</verdict>")

    from essarion_build import reason

    r = reason("anything", context=Context(), _runtime=essarion_runtime)
    assert r.verdict == "ship"
    assert essarion_stub.call_count == 2


def test_essarion_context_is_empty(essarion_context: Context) -> None:
    assert essarion_context.builtin_skills == []
    assert essarion_context.repo_files == []


def test_essarion_skills_loads_all(essarion_skills: Context) -> None:
    assert len(essarion_skills.builtin_skills) >= 50


def test_isolated_prompts_resets(isolated_prompts: None) -> None:
    from essarion_build import configure_prompts
    from essarion_build._prompts import current_system

    configure_prompts(system="overridden")
    assert current_system() == "overridden"
    # The fixture's teardown will reset; here we just verify it's not magic.


def test_isolated_providers_lets_us_register_freely(isolated_providers: None) -> None:
    from essarion_build import build_provider, register_provider

    class _Tmp:
        def __init__(self, *, api_key=None, model: str) -> None:
            self.model = model

        def complete(self, *, system, messages, max_tokens):
            raise NotImplementedError

    register_provider("tmp-provider", _Tmp)
    prov = build_provider(name="tmp-provider", api_key=None, model="x")
    assert prov.model == "x"


async def test_essarion_async_runtime(
    essarion_async_runtime: AsyncLiteRuntime,
    essarion_async_stub: AsyncStubProvider,
) -> None:
    essarion_async_stub.push("<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>")
    essarion_async_stub.push("<verdict>ship</verdict>")

    from essarion_build import areason

    r = await areason("anything", context=Context(), _runtime=essarion_async_runtime)
    assert r.verdict == "ship"
