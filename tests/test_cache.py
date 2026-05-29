"""Tests for ResponseCache and CachingProvider."""

from __future__ import annotations

from essarion_build import (
    CachingProvider,
    Context,
    LiteRuntime,
    ResponseCache,
    StubProvider,
    Usage,
    reason,
)
from essarion_build._cache import _cache_key
from essarion_build._providers import ProviderResponse


def test_cache_key_is_stable() -> None:
    k1 = _cache_key(provider_name="p", model="m", system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)
    k2 = _cache_key(provider_name="p", model="m", system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)
    assert k1 == k2


def test_cache_key_varies_with_input() -> None:
    a = _cache_key(provider_name="p", model="m", system="s", messages=[], max_tokens=10)
    b = _cache_key(provider_name="p", model="m", system="DIFFERENT", messages=[], max_tokens=10)
    assert a != b


def test_response_cache_round_trip(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    response = ProviderResponse(text="cached body", usage=Usage(prompt_tokens=99))
    cache.put("abc", response)
    fetched = cache.get("abc")
    assert fetched is not None
    assert fetched.text == "cached body"
    assert fetched.usage.prompt_tokens == 99


def test_response_cache_miss(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    assert cache.get("nope") is None
    assert cache.misses == 1


def test_caching_provider_serves_cached_response_on_repeat(tmp_path) -> None:
    """A second call with identical args returns the cached response without
    consuming another stub script entry."""
    stub = StubProvider(
        responses=[
            ProviderResponse(text="first", usage=Usage(prompt_tokens=10, total_tokens=12)),
        ]
    )
    cache = ResponseCache(tmp_path)
    wrapped = CachingProvider(stub, cache, provider_name="stub")

    a = wrapped.complete(system="sys", messages=[{"role": "user", "content": "u"}], max_tokens=100)
    b = wrapped.complete(system="sys", messages=[{"role": "user", "content": "u"}], max_tokens=100)
    assert a.text == b.text == "first"
    assert cache.hits == 1
    # Only one underlying provider call happened.
    assert stub.call_count == 1


def test_caching_provider_in_full_loop(tmp_path) -> None:
    """End-to-end: caching applied to a LiteRuntime stub-driven reason() call."""
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<verdict>ship</verdict>",
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",  # only reached if no cache hit
            "<verdict>ship</verdict>",
        ]
    )
    cache = ResponseCache(tmp_path)
    wrapped = CachingProvider(stub, cache, provider_name="stub")
    rt = LiteRuntime(wrapped)

    r1 = reason("task", context=Context(), _runtime=rt)
    r2 = reason("task", context=Context(), _runtime=rt)

    assert r1.verdict == r2.verdict == "ship"
    # Both calls in r1 are now cached, so r2 takes zero underlying calls.
    assert stub.call_count == 2
    assert cache.hits == 2


def test_response_cache_clear(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put("abc", ProviderResponse(text="x", usage=Usage()))
    assert cache.get("abc") is not None
    cache.clear()
    assert cache.get("abc") is None
