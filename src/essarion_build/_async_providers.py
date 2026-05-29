"""Async Provider implementations.

Mirrors `_providers.py` for users who want to call `areason()` / `agenerate()`
from an async context. The Async providers share the same retry / error /
usage-parsing logic; only the transport differs.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, AsyncIterator, Callable, Protocol

import httpx
from pydantic import BaseModel

from ._providers import (
    DEFAULT_OLLAMA_BASE_URL,
    GEMINI_BASE_URL,
    OPENAI_BASE_URL,
    OPENROUTER_BASE_URL,
    ProviderResponse,
    StreamChunk,
    Usage,
    _parse_gemini_response,
    _parse_ollama_response,
    _parse_openai_compatible_response,
    _stub_auto_text,
    _stub_estimate_usage,
)
from .exceptions import (
    ProviderAuthError,
    ProviderHTTPError,
    ProviderNotAvailable,
    ProviderRateLimitError,
    ProviderResponseError,
)


_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_HTTP_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0


async def _async_sleep_backoff(attempt: int) -> None:
    await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))


class AsyncProvider(Protocol):
    """Async chat-completion seam. Mirrors `Provider` but with awaitables."""

    model: str

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        ...


class AsyncStreamingProvider(AsyncProvider, Protocol):
    """Optional capability: async streaming."""

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> AsyncIterator[StreamChunk]:
        ...


class _AsyncOpenAICompatibleProvider:
    """Shared async transport for OpenAI-compatible APIs (OpenAI, OpenRouter)."""

    _provider_label = "openai-compatible"
    _base_url = OPENAI_BASE_URL

    def __init__(self, *, api_key: str | None, model: str, env_var: str) -> None:
        resolved_key = api_key or os.environ.get(env_var)
        if not resolved_key:
            raise RuntimeError(
                f"{env_var} is not set. Pass api_key=... to configure() "
                f"or export {env_var} in your environment."
            )
        self._api_key = resolved_key
        self.model = model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_body(
        self, *, system: str, messages: list[dict[str, Any]], max_tokens: int
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                *messages,
            ],
        }

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        body = self._build_body(system=system, messages=messages, max_tokens=max_tokens)
        last_error: Exception | None = None
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(120.0),
            headers=self._headers(),
        ) as client:
            for attempt in range(_MAX_HTTP_ATTEMPTS):
                try:
                    response = await client.post("/chat/completions", json=body)
                except httpx.HTTPError as e:
                    last_error = e
                    if attempt + 1 < _MAX_HTTP_ATTEMPTS:
                        await _async_sleep_backoff(attempt)
                        continue
                    raise ProviderHTTPError(
                        f"{self._provider_label} network error for model {self.model!r}: {e}"
                    ) from e

                if response.status_code in _RETRYABLE_STATUSES and attempt + 1 < _MAX_HTTP_ATTEMPTS:
                    await _async_sleep_backoff(attempt)
                    continue

                if response.status_code in (401, 403):
                    raise ProviderAuthError(
                        f"{self._provider_label} rejected the API key (HTTP {response.status_code}) "
                        f"for model {self.model!r}: {response.text[:500]}"
                    )
                if response.status_code == 429:
                    raise ProviderRateLimitError(
                        f"{self._provider_label} rate-limited the request for model {self.model!r}: "
                        f"{response.text[:500]}"
                    )
                if response.status_code >= 400:
                    raise ProviderHTTPError(
                        f"{self._provider_label} returned HTTP {response.status_code} for model "
                        f"{self.model!r}: {response.text[:500]}"
                    )

                return _parse_openai_compatible_response(
                    response.json(), model=self.model, provider_label=self._provider_label
                )

        raise ProviderHTTPError(
            f"{self._provider_label} network error for model {self.model!r}: {last_error}"
        )


class _AsyncOpenRouterProvider(_AsyncOpenAICompatibleProvider):
    _provider_label = "OpenRouter"
    _base_url = OPENROUTER_BASE_URL

    def __init__(self, *, api_key: str | None = None, model: str) -> None:
        super().__init__(api_key=api_key, model=model, env_var="OPENROUTER_API_KEY")

    def _headers(self) -> dict[str, str]:
        h = super()._headers()
        h["HTTP-Referer"] = "https://essarion.com"
        h["X-Title"] = "essarion-build"
        return h


class _AsyncOpenAIProvider(_AsyncOpenAICompatibleProvider):
    _provider_label = "OpenAI"
    _base_url = OPENAI_BASE_URL

    def __init__(self, *, api_key: str | None = None, model: str) -> None:
        super().__init__(api_key=api_key, model=model, env_var="OPENAI_API_KEY")


class _AsyncAnthropicProvider:
    """Async wrapper around the Anthropic SDK's AsyncAnthropic client."""

    def __init__(self, *, api_key: str | None = None, model: str) -> None:
        from anthropic import AsyncAnthropic

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Pass api_key=... to configure() "
                "or export ANTHROPIC_API_KEY in your environment."
            )
        self._client = AsyncAnthropic(api_key=resolved_key)
        self.model = model

    async def complete(
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
            response = await self._client.messages.create(
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


class _AsyncGeminiProvider:
    def __init__(self, *, api_key: str | None = None, model: str) -> None:
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get(
            "GOOGLE_API_KEY"
        )
        if not resolved_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Pass api_key=... to configure() "
                "or export GEMINI_API_KEY (or GOOGLE_API_KEY) in your environment."
            )
        self._api_key = resolved_key
        self.model = model

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        contents: list[dict[str, Any]] = []
        for m in messages:
            wire_role = "model" if m["role"] == "assistant" else "user"
            contents.append(
                {"role": wire_role, "parts": [{"text": m["content"]}]}
            )
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        path = f"/models/{self.model}:generateContent"
        params = {"key": self._api_key}
        last_error: Exception | None = None
        async with httpx.AsyncClient(
            base_url=GEMINI_BASE_URL,
            timeout=httpx.Timeout(120.0),
            headers={"Content-Type": "application/json"},
        ) as client:
            for attempt in range(_MAX_HTTP_ATTEMPTS):
                try:
                    response = await client.post(path, json=body, params=params)
                except httpx.HTTPError as e:
                    last_error = e
                    if attempt + 1 < _MAX_HTTP_ATTEMPTS:
                        await _async_sleep_backoff(attempt)
                        continue
                    raise ProviderHTTPError(
                        f"Gemini network error for model {self.model!r}: {e}"
                    ) from e

                if response.status_code in _RETRYABLE_STATUSES and attempt + 1 < _MAX_HTTP_ATTEMPTS:
                    await _async_sleep_backoff(attempt)
                    continue

                if response.status_code in (401, 403):
                    raise ProviderAuthError(
                        f"Gemini rejected the API key (HTTP {response.status_code}) "
                        f"for model {self.model!r}: {response.text[:500]}"
                    )
                if response.status_code == 429:
                    raise ProviderRateLimitError(
                        f"Gemini rate-limited the request for model {self.model!r}: "
                        f"{response.text[:500]}"
                    )
                if response.status_code >= 400:
                    raise ProviderHTTPError(
                        f"Gemini returned HTTP {response.status_code} for model "
                        f"{self.model!r}: {response.text[:500]}"
                    )

                return _parse_gemini_response(response.json(), model=self.model)

        raise ProviderHTTPError(
            f"Gemini network error for model {self.model!r}: {last_error}"
        )


class _AsyncOllamaProvider:
    def __init__(self, *, api_key: str | None = None, model: str) -> None:
        del api_key
        self._base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
        self.model = model

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        body = {
            "model": self.model,
            "stream": False,
            "options": {"num_predict": max_tokens},
            "messages": [
                {"role": "system", "content": system},
                *messages,
            ],
        }
        last_error: Exception | None = None
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=httpx.Timeout(300.0)
        ) as client:
            for attempt in range(_MAX_HTTP_ATTEMPTS):
                try:
                    response = await client.post("/api/chat", json=body)
                except httpx.HTTPError as e:
                    last_error = e
                    if attempt + 1 < _MAX_HTTP_ATTEMPTS:
                        await _async_sleep_backoff(attempt)
                        continue
                    raise ProviderHTTPError(
                        f"Ollama network error for model {self.model!r}: {e}"
                    ) from e

                if response.status_code in _RETRYABLE_STATUSES and attempt + 1 < _MAX_HTTP_ATTEMPTS:
                    await _async_sleep_backoff(attempt)
                    continue

                if response.status_code >= 400:
                    raise ProviderHTTPError(
                        f"Ollama returned HTTP {response.status_code} for model "
                        f"{self.model!r}: {response.text[:500]}"
                    )

                return _parse_ollama_response(response.json(), model=self.model)

        raise ProviderHTTPError(
            f"Ollama network error for model {self.model!r}: {last_error}"
        )


class AsyncStubProvider:
    """Async counterpart to `StubProvider`. Public — for users' async tests.

    Like `StubProvider`, supports a strict **scripted** mode (default) and an
    **auto-respond** mode (``auto_respond=True``) that synthesizes a
    well-formed response per phase once the scripted queue is empty.
    ``build_async_provider(name="stub")`` / `configure(provider="stub")` use
    auto-respond so async smoke tests work with no scripting.
    """

    def __init__(
        self,
        *,
        responses: list[str | ProviderResponse] | None = None,
        model: str = "async-stub-model",
        auto_respond: bool = False,
    ) -> None:
        self.model = model
        self.auto_respond = auto_respond
        self._responses: list[ProviderResponse] = []
        for r in responses or []:
            self._responses.append(self._coerce(r))
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _coerce(r: str | ProviderResponse) -> ProviderResponse:
        if isinstance(r, ProviderResponse):
            return r
        return ProviderResponse(text=r, usage=Usage())

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def push(self, response: str | ProviderResponse) -> None:
        self._responses.append(self._coerce(response))

    def _record(self, system: str, messages: list[dict[str, Any]], max_tokens: int) -> None:
        self.calls.append(
            {"system": system, "messages": list(messages), "max_tokens": max_tokens}
        )

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        if self._responses:
            self._record(system, messages, max_tokens)
            return self._responses.pop(0)
        if self.auto_respond:
            self._record(system, messages, max_tokens)
            text = _stub_auto_text(messages)
            return ProviderResponse(
                text=text, usage=_stub_estimate_usage(system, messages, text)
            )
        raise ProviderResponseError(
            "AsyncStubProvider exhausted: no more scripted responses "
            f"(served {self.call_count} call(s) so far). One areason()/agenerate() "
            "runs several provider calls — plan, self-check, draft, etc. — so "
            "either script one response per phase via AsyncStubProvider(responses="
            "[...]) / push(...), or pass auto_respond=True for a stub that answers "
            'every phase automatically (this is what configure(provider="stub") uses).'
        )


AsyncProviderFactory = Callable[..., AsyncProvider]

_ASYNC_PROVIDER_REGISTRY: dict[str, AsyncProviderFactory] = {}


def register_async_provider(name: str, factory: AsyncProviderFactory) -> None:
    """Register a custom async provider. See `register_provider`."""
    _ASYNC_PROVIDER_REGISTRY[name] = factory


def unregister_async_provider(name: str) -> None:
    _ASYNC_PROVIDER_REGISTRY.pop(name, None)


def build_async_provider(*, name: str, api_key: str | None, model: str) -> AsyncProvider:
    """Construct an async provider by name."""
    if name in _ASYNC_PROVIDER_REGISTRY:
        return _ASYNC_PROVIDER_REGISTRY[name](api_key=api_key, model=model)
    if name == "openrouter":
        return _AsyncOpenRouterProvider(api_key=api_key, model=model)
    if name == "anthropic":
        return _AsyncAnthropicProvider(api_key=api_key, model=model)
    if name == "openai":
        return _AsyncOpenAIProvider(api_key=api_key, model=model)
    if name == "gemini":
        return _AsyncGeminiProvider(api_key=api_key, model=model)
    if name == "ollama":
        return _AsyncOllamaProvider(api_key=api_key, model=model)
    if name == "stub":
        # Auto-respond so `configure(provider="stub")` works with no scripting.
        return AsyncStubProvider(model=model, auto_respond=True)
    raise ProviderNotAvailable(
        f"Async provider {name!r} is not available. "
        "Built-in: openrouter, anthropic, openai, gemini, ollama, stub."
    )
