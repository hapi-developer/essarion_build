"""On-disk JSON response cache for provider calls.

The cache key is a SHA-256 of (provider_name, model, system, messages,
max_tokens). On a cache hit, the loop skips the network entirely. Off by
default; opt in with `essarion_build.configure(cache_dir=...)`.

Useful when:
- iterating on Context or prompts and you don't want to pay for the same plan
  twice
- writing deterministic integration tests against real providers
- working offline: previously seen prompts still return their cached answer.

NOT useful in production where you want fresh model responses; leave it off.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from ._providers import Provider, ProviderResponse, Usage


def _cache_key(
    *,
    provider_name: str,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> str:
    payload = {
        "provider": provider_name,
        "model": model,
        "system": system,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return digest


class ResponseCache:
    """Thread-unsafe, process-local JSON file cache. Suitable for dev iteration."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def _path_for(self, key: str) -> Path:
        # Two levels of fan-out so individual directories don't explode.
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> ProviderResponse | None:
        path = self._path_for(key)
        if not path.exists():
            self.misses += 1
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self.misses += 1
            return None
        self.hits += 1
        return ProviderResponse(
            text=data["text"], usage=Usage(**data.get("usage", {}))
        )

    def put(self, key: str, response: ProviderResponse) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "text": response.text,
                    "usage": response.usage.model_dump(),
                    "cached_at": time.time(),
                },
                f,
                ensure_ascii=False,
            )
        os.replace(tmp, path)

    def clear(self) -> None:
        """Wipe every cached entry under the root."""
        if not self.root.exists():
            return
        for path in self.root.rglob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass
        # Best-effort prune of empty subdirs.
        for d in sorted(self.root.glob("*"), reverse=True):
            try:
                if d.is_dir():
                    d.rmdir()
            except OSError:
                pass


class CachingProvider:
    """Provider wrapper that consults a `ResponseCache` before each call.

    Wraps any object satisfying the `Provider` protocol; preserves `model`.
    """

    def __init__(self, inner: Provider, cache: ResponseCache, *, provider_name: str = "wrapped") -> None:
        self._inner = inner
        self._cache = cache
        self._provider_name = provider_name
        self.model = inner.model

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        key = _cache_key(
            provider_name=self._provider_name,
            model=self.model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        response = self._inner.complete(
            system=system, messages=messages, max_tokens=max_tokens
        )
        self._cache.put(key, response)
        return response


__all__ = ["ResponseCache", "CachingProvider"]
