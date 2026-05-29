"""Response cache: skip duplicate provider calls during dev iteration.

Run with:
    OPENROUTER_API_KEY=... python examples/08_cache.py
"""

from __future__ import annotations

import time

from essarion_build import (
    CachingProvider,
    Context,
    LiteRuntime,
    ResponseCache,
    build_provider,
    reason,
)


def main() -> None:
    cache = ResponseCache("./.essarion-cache")
    inner = build_provider(name="openrouter", api_key=None, model="openai/gpt-4o-mini")
    provider = CachingProvider(inner, cache, provider_name="openrouter")
    rt = LiteRuntime(provider)
    ctx = Context().with_skills(["python_idioms", "scope_discipline"])

    # First call: hits the network. Slow.
    t0 = time.perf_counter()
    r1 = reason("review my approach to email validation", context=ctx, _runtime=rt)
    t1 = time.perf_counter()

    # Identical call: served from cache. Fast.
    r2 = reason("review my approach to email validation", context=ctx, _runtime=rt)
    t2 = time.perf_counter()

    print(f"first call:  {t1 - t0:.2f}s")
    print(f"second call: {t2 - t1:.2f}s")
    print(f"cache hits:  {cache.hits}, misses: {cache.misses}")
    assert r1.verdict == r2.verdict


if __name__ == "__main__":
    main()
