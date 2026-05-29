"""Tests for the async API: areason(), agenerate(), AsyncLiteRuntime, AsyncStubProvider."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from essarion_build import (
    AsyncLiteRuntime,
    AsyncStubProvider,
    Context,
    Generation,
    Reasoning,
    ReasoningFormatError,
    Usage,
    agenerate,
    areason,
)
from essarion_build._async_providers import (
    build_async_provider,
    register_async_provider,
    unregister_async_provider,
)
from essarion_build._providers import ProviderResponse
from essarion_build.exceptions import (
    ProviderAuthError,
    ProviderHTTPError,
    ProviderNotAvailable,
    ProviderRateLimitError,
)


async def test_areason_shape() -> None:
    stub = AsyncStubProvider(
        responses=[
            (
                "<plan>1. validate alg header</plan>"
                "<tradeoffs>- chosen: whitelist</tradeoffs>"
                "<verdict>preliminary</verdict>"
            ),
            "<verdict>final: ship</verdict>",
        ]
    )
    rt = AsyncLiteRuntime(stub)
    r = await areason("task", context=Context(), _runtime=rt)
    assert isinstance(r, Reasoning)
    assert "validate alg header" in r.plan
    assert r.verdict == "final: ship"
    assert stub.call_count == 2


async def test_agenerate_shape() -> None:
    stub = AsyncStubProvider(
        responses=[
            (
                "<plan>1. reject alg=none</plan>"
                "<tradeoffs>- chosen: whitelist</tradeoffs>"
                "<verdict>preliminary</verdict>"
            ),
            "<code>def verify():\n    pass</code>",
            (
                "<verdict>final: ship</verdict>"
                "<defense>The whitelist closes the alg=none family.</defense>"
            ),
        ]
    )
    rt = AsyncLiteRuntime(stub)
    g = await agenerate("task", context=Context(), _runtime=rt)
    assert isinstance(g, Generation)
    assert "reject alg=none" in g.reasoning.plan
    assert "def verify" in g.code
    assert "whitelist" in g.defense
    assert stub.call_count == 3


async def test_async_tag_repair() -> None:
    stub = AsyncStubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<code>x=1</code>",
            "<verdict>ship</verdict>",  # missing defense
            "<defense>safe</defense>",
        ]
    )
    rt = AsyncLiteRuntime(stub)
    g = await agenerate("anything", context=Context(), _runtime=rt)
    assert g.defense == "safe"
    assert stub.call_count == 4


async def test_async_tag_repair_eventually_raises() -> None:
    stub = AsyncStubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<code>x=1</code>",
            "<verdict>ship</verdict>",
            "(still no defense tag here)",
        ]
    )
    rt = AsyncLiteRuntime(stub)
    with pytest.raises(ReasoningFormatError):
        await agenerate("anything", context=Context(), _runtime=rt)


async def test_async_usage_aggregates() -> None:
    stub = AsyncStubProvider(
        responses=[
            ProviderResponse(
                text="<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
                usage=Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
            ),
            ProviderResponse(
                text="<verdict>ship</verdict>",
                usage=Usage(prompt_tokens=50, completion_tokens=5, total_tokens=55),
            ),
        ]
    )
    r = await areason("task", context=Context(), _runtime=AsyncLiteRuntime(stub))
    assert r.usage.total_tokens == 175


async def test_async_per_call_max_tokens() -> None:
    stub = AsyncStubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>",
            "<verdict>ship</verdict>",
        ]
    )
    await areason(
        "task", context=Context(), _runtime=AsyncLiteRuntime(stub), max_tokens=321
    )
    assert stub.calls[0]["max_tokens"] == 321
    assert stub.calls[1]["max_tokens"] == 321


async def test_async_register_custom_provider() -> None:
    """A custom async provider can be registered and built by name."""

    class _MyAsyncProvider:
        def __init__(self, *, api_key=None, model: str) -> None:
            self.model = model

        async def complete(self, *, system, messages, max_tokens):
            return ProviderResponse(text="<plan>x</plan>", usage=Usage())

    register_async_provider("my-custom-async", _MyAsyncProvider)
    try:
        prov = build_async_provider(name="my-custom-async", api_key=None, model="m")
        assert prov.model == "m"
        resp = await prov.complete(system="s", messages=[], max_tokens=10)
        assert resp.text == "<plan>x</plan>"
    finally:
        unregister_async_provider("my-custom-async")


async def test_async_build_unknown_raises() -> None:
    with pytest.raises(ProviderNotAvailable):
        build_async_provider(name="xyz-unknown", api_key="x", model="m")


# Async OpenRouter HTTP mapping
class _AsyncMockTransport:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _install_async_transport(monkeypatch, scripted):
    transport = _AsyncMockTransport(scripted)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(transport.handle_async_request)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    async def fast_sleep(attempt):
        return None

    monkeypatch.setattr(
        "essarion_build._async_providers._async_sleep_backoff", fast_sleep
    )
    return transport


def _ok_response():
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "<plan>1</plan>"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


async def test_async_openrouter_retries_then_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    transport = _install_async_transport(
        monkeypatch, [httpx.Response(429, text="slow"), _ok_response()]
    )
    prov = build_async_provider(name="openrouter", api_key=None, model="m")
    r = await prov.complete(system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)
    assert "<plan>" in r.text
    assert len(transport.requests) == 2


async def test_async_openrouter_401_maps_to_auth(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    _install_async_transport(monkeypatch, [httpx.Response(401, text="bad")])
    prov = build_async_provider(name="openrouter", api_key=None, model="m")
    with pytest.raises(ProviderAuthError):
        await prov.complete(system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)


async def test_async_openrouter_persistent_429(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    _install_async_transport(
        monkeypatch, [httpx.Response(429, text=str(i)) for i in range(3)]
    )
    prov = build_async_provider(name="openrouter", api_key=None, model="m")
    with pytest.raises(ProviderRateLimitError):
        await prov.complete(system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)


async def test_async_openrouter_persistent_500(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    _install_async_transport(
        monkeypatch, [httpx.Response(500, text="oops") for _ in range(3)]
    )
    prov = build_async_provider(name="openrouter", api_key=None, model="m")
    with pytest.raises(ProviderHTTPError):
        await prov.complete(system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)


async def test_async_stub_exhausted_raises() -> None:
    stub = AsyncStubProvider(responses=["<plan>x</plan>"])
    await stub.complete(system="s", messages=[], max_tokens=1)
    from essarion_build.exceptions import ProviderResponseError

    with pytest.raises(ProviderResponseError):
        await stub.complete(system="s", messages=[], max_tokens=1)


async def test_async_top_level_areason_uses_default_runtime(monkeypatch) -> None:
    """Hitting areason() without _runtime falls back through select_async_runtime."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    _install_async_transport(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>"
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            ),
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "<verdict>ship</verdict>"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            ),
        ],
    )
    r = await areason("task", context=Context())
    assert r.verdict == "ship"
