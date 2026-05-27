"""Internal Provider seam.

Not re-exported at the package level. v0 ships two concrete providers:

- **OpenRouter** (default) — talks to ~any model via a single OpenAI-compatible
  endpoint. The cheap-default story: amplify a cheap coding model's reasoning
  rather than be a wrapper for an expensive one.
- **Anthropic** — talks directly to the Claude API for users who already have
  an `ANTHROPIC_API_KEY`.

Both are accessed via the same `Provider` protocol. v0.2 can add Gemini,
local-OSS via Ollama, etc., without breaking the user-facing surface.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import httpx

from .exceptions import ProviderNotAvailable


class Provider(Protocol):
    """A thin chat-completion seam.

    `messages` is a list of {"role": "user" | "assistant", "content": str} dicts.
    The provider handles transport, auth, and the per-API shape (system prompt
    placement, etc.).
    """

    model: str

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> str:
        ...


class _AnthropicProvider:
    """Talks to the Anthropic Claude API.

    Uses prompt caching on the system block so the 3 calls in a reasoning loop
    share a cached prefix.
    """

    def __init__(self, *, api_key: str | None = None, model: str) -> None:
        # Imported here so a missing/broken anthropic install only fails when
        # someone actually uses this provider, not at package import time.
        from anthropic import Anthropic

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Pass api_key=... to configure() "
                "or export ANTHROPIC_API_KEY in your environment."
            )
        self._client = Anthropic(api_key=resolved_key)
        self.model = model

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        )
        out: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                out.append(block.text)
        return "".join(out)


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class _OpenRouterProvider:
    """Talks to OpenRouter's OpenAI-compatible chat completions endpoint.

    Default provider in v0. OpenRouter routes to ~any model behind one API,
    which keeps the SDK's BYOK story honest while staying cheap.
    """

    def __init__(self, *, api_key: str | None = None, model: str) -> None:
        resolved_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Pass api_key=... to configure() "
                "or export OPENROUTER_API_KEY in your environment."
            )
        self._api_key = resolved_key
        self.model = model
        self._client = httpx.Client(
            base_url=OPENROUTER_BASE_URL,
            timeout=httpx.Timeout(120.0),
            headers={
                "Authorization": f"Bearer {resolved_key}",
                "Content-Type": "application/json",
                # OpenRouter encourages identifying the integration so models
                # can be billed and rate-limited correctly.
                "HTTP-Referer": "https://essarion.com",
                "X-Title": "essarion-build",
            },
        )

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> str:
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                *messages,
            ],
        }
        response = self._client.post("/chat/completions", json=body)
        response.raise_for_status()
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(
                f"OpenRouter returned an unexpected response shape: {data!r}"
            ) from e


def build_provider(*, name: str, api_key: str | None, model: str) -> Provider:
    """Construct a provider by name. v0 knows 'openrouter' (default) and 'anthropic'."""
    if name == "openrouter":
        return _OpenRouterProvider(api_key=api_key, model=model)
    if name == "anthropic":
        return _AnthropicProvider(api_key=api_key, model=model)
    raise ProviderNotAvailable(
        f"Provider {name!r} is not available in v0. "
        "Supported: 'openrouter' (default), 'anthropic'."
    )
