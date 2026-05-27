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
import time
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from .exceptions import (
    ProviderAuthError,
    ProviderHTTPError,
    ProviderNotAvailable,
    ProviderRateLimitError,
    ProviderResponseError,
)


class Usage(BaseModel):
    """Token usage for one or more provider calls.

    `cached_tokens` is provider-reported cache hits (Anthropic prompt caching,
    OpenRouter prompt caching where supported). Zero when the provider doesn't
    report it.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
        )


class ProviderResponse(BaseModel):
    """One Provider.complete() result: the text and the usage it cost."""

    text: str
    usage: Usage


# HTTP retry policy for transient failures. Two retries with short exponential
# backoff — enough to absorb a single 429 / 502 blip without papering over real
# outages or driving up cost on cheap models.
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_HTTP_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0


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
    ) -> ProviderResponse:
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
    ) -> ProviderResponse:
        from anthropic import (
            APIStatusError,
            AuthenticationError,
            RateLimitError,
        )

        try:
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
        except AuthenticationError as e:
            raise ProviderAuthError(
                f"Anthropic rejected the API key for model {self.model!r}: {e}"
            ) from e
        except RateLimitError as e:
            raise ProviderRateLimitError(
                f"Anthropic rate-limited the request for model {self.model!r}: {e}"
            ) from e
        except APIStatusError as e:
            raise ProviderHTTPError(
                f"Anthropic returned HTTP {e.status_code} for model {self.model!r}: {e}"
            ) from e

        out: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                out.append(block.text)

        usage_obj = getattr(response, "usage", None)
        if usage_obj is None:
            usage = Usage()
        else:
            prompt = getattr(usage_obj, "input_tokens", 0) or 0
            completion = getattr(usage_obj, "output_tokens", 0) or 0
            cached_read = getattr(usage_obj, "cache_read_input_tokens", 0) or 0
            cached_write = getattr(usage_obj, "cache_creation_input_tokens", 0) or 0
            usage = Usage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
                cached_tokens=cached_read + cached_write,
            )
        return ProviderResponse(text="".join(out), usage=usage)


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _sleep_backoff(attempt: int) -> None:
    """Sleep before the (attempt+1)-th try. Indirected so tests can monkeypatch."""
    time.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))


class _OpenRouterProvider:
    """Talks to OpenRouter's OpenAI-compatible chat completions endpoint.

    Default provider in v0. OpenRouter routes to ~any model behind one API,
    which keeps the SDK's BYOK story honest while staying cheap.

    The HTTP client is created per `complete()` call so the provider never
    leaks file descriptors when reason()/generate() raise mid-loop.
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

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            # OpenRouter encourages identifying the integration so models can
            # be billed and rate-limited correctly.
            "HTTP-Referer": "https://essarion.com",
            "X-Title": "essarion-build",
        }

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                *messages,
            ],
        }

        last_error: Exception | None = None
        with httpx.Client(
            base_url=OPENROUTER_BASE_URL,
            timeout=httpx.Timeout(120.0),
            headers=self._headers(),
        ) as client:
            for attempt in range(_MAX_HTTP_ATTEMPTS):
                try:
                    response = client.post("/chat/completions", json=body)
                except httpx.HTTPError as e:
                    last_error = e
                    if attempt + 1 < _MAX_HTTP_ATTEMPTS:
                        _sleep_backoff(attempt)
                        continue
                    raise ProviderHTTPError(
                        f"OpenRouter network error for model {self.model!r}: {e}"
                    ) from e

                if response.status_code in _RETRYABLE_STATUSES and attempt + 1 < _MAX_HTTP_ATTEMPTS:
                    _sleep_backoff(attempt)
                    continue

                if response.status_code in (401, 403):
                    raise ProviderAuthError(
                        f"OpenRouter rejected the API key (HTTP {response.status_code}) "
                        f"for model {self.model!r}: {response.text[:500]}"
                    )
                if response.status_code == 429:
                    raise ProviderRateLimitError(
                        f"OpenRouter rate-limited the request for model {self.model!r}: "
                        f"{response.text[:500]}"
                    )
                if response.status_code >= 400:
                    raise ProviderHTTPError(
                        f"OpenRouter returned HTTP {response.status_code} for model "
                        f"{self.model!r}: {response.text[:500]}"
                    )

                return _parse_openrouter_response(response.json(), model=self.model)

        # Defensive: the loop above always returns or raises, but guard anyway.
        raise ProviderHTTPError(
            f"OpenRouter network error for model {self.model!r}: {last_error}"
        )


def _parse_openrouter_response(data: dict[str, Any], *, model: str) -> ProviderResponse:
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderResponseError(
            f"OpenRouter returned an unexpected response shape for model {model!r}: {data!r}"
        ) from e

    raw_usage = data.get("usage") or {}
    prompt = int(raw_usage.get("prompt_tokens", 0) or 0)
    completion = int(raw_usage.get("completion_tokens", 0) or 0)
    total = int(raw_usage.get("total_tokens", prompt + completion) or 0)
    # OpenRouter sometimes nests cached counts inside prompt_tokens_details.
    cached = 0
    details = raw_usage.get("prompt_tokens_details") or {}
    if isinstance(details, dict):
        cached = int(details.get("cached_tokens", 0) or 0)
    usage = Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cached_tokens=cached,
    )
    return ProviderResponse(text=text, usage=usage)


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
