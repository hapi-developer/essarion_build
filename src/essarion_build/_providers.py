"""Internal Provider seam.

Not re-exported at the package level (except the `Stub` provider, which is
re-exported under `essarion_build.testing` so users can write tests against
their own essarion-build workflows).

v0.3 ships these providers:

- **openrouter** (default) — OpenAI-compatible. The cheap-default story.
- **anthropic** — direct Claude API. Uses prompt caching.
- **openai** — direct OpenAI API.
- **gemini** — Google Gemini.
- **ollama** — local OSS models via Ollama. Free / private. No key required.
- **stub** — in-memory, scripted responses. For tests.

Users can register their own providers via `register_provider(name, factory)`.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Iterator, Protocol

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


class StreamChunk(BaseModel):
    """A streamed delta from Provider.stream(). `text` is the partial token(s),
    `usage` is non-zero only on the final chunk."""

    text: str = ""
    usage: Usage = Usage()
    done: bool = False


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


class StreamingProvider(Provider, Protocol):
    """Optional capability: emit a stream of StreamChunk events.

    Providers that implement this can be driven by `stream_reason`/`stream_generate`.
    Providers that don't only support the buffered `complete()` path.
    """

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> Iterator[StreamChunk]:
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

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> Iterator[StreamChunk]:
        from anthropic import (
            APIStatusError,
            AuthenticationError,
            RateLimitError,
        )

        try:
            with self._client.messages.stream(
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
            ) as stream:
                for text in stream.text_stream:
                    yield StreamChunk(text=text)
                final = stream.get_final_message()
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

        usage_obj = getattr(final, "usage", None)
        if usage_obj is None:
            yield StreamChunk(done=True)
            return
        prompt = getattr(usage_obj, "input_tokens", 0) or 0
        completion = getattr(usage_obj, "output_tokens", 0) or 0
        cached_read = getattr(usage_obj, "cache_read_input_tokens", 0) or 0
        cached_write = getattr(usage_obj, "cache_creation_input_tokens", 0) or 0
        yield StreamChunk(
            done=True,
            usage=Usage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
                cached_tokens=cached_read + cached_write,
            ),
        )


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


def _sleep_backoff(attempt: int) -> None:
    """Sleep before the (attempt+1)-th try. Indirected so tests can monkeypatch."""
    time.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))


class _OpenAICompatibleProvider:
    """Shared transport for OpenAI-compatible chat completions (OpenAI, OpenRouter).

    Subclasses override `_provider_label`, the base URL, and headers. The HTTP
    client is per-call so file descriptors don't leak when the runtime raises
    mid-loop.
    """

    _provider_label: str = "openai-compatible"
    _base_url: str = OPENAI_BASE_URL

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

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        body = self._build_body(system=system, messages=messages, max_tokens=max_tokens)
        last_error: Exception | None = None
        with httpx.Client(
            base_url=self._base_url,
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
                        f"{self._provider_label} network error for model {self.model!r}: {e}"
                    ) from e

                if response.status_code in _RETRYABLE_STATUSES and attempt + 1 < _MAX_HTTP_ATTEMPTS:
                    _sleep_backoff(attempt)
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


class _OpenRouterProvider(_OpenAICompatibleProvider):
    """OpenRouter — OpenAI-compatible router across many providers."""

    _provider_label = "OpenRouter"
    _base_url = OPENROUTER_BASE_URL

    def __init__(self, *, api_key: str | None = None, model: str) -> None:
        super().__init__(api_key=api_key, model=model, env_var="OPENROUTER_API_KEY")

    def _headers(self) -> dict[str, str]:
        h = super()._headers()
        # OpenRouter encourages identifying the integration so models can
        # be billed and rate-limited correctly.
        h["HTTP-Referer"] = "https://essarion.com"
        h["X-Title"] = "essarion-build"
        return h


class _OpenAIProvider(_OpenAICompatibleProvider):
    """Direct-to-OpenAI provider for users who want to bypass OpenRouter."""

    _provider_label = "OpenAI"
    _base_url = OPENAI_BASE_URL

    def __init__(self, *, api_key: str | None = None, model: str) -> None:
        super().__init__(api_key=api_key, model=model, env_var="OPENAI_API_KEY")


def _parse_openai_compatible_response(
    data: dict[str, Any], *, model: str, provider_label: str = "OpenAI-compatible"
) -> ProviderResponse:
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderResponseError(
            f"{provider_label} returned an unexpected response shape for model {model!r}: {data!r}"
        ) from e

    raw_usage = data.get("usage") or {}
    prompt = int(raw_usage.get("prompt_tokens", 0) or 0)
    completion = int(raw_usage.get("completion_tokens", 0) or 0)
    total = int(raw_usage.get("total_tokens", prompt + completion) or 0)
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


# Backwards compat alias used by tests/users that imported the old name.
_parse_openrouter_response = _parse_openai_compatible_response


class _GeminiProvider:
    """Google Gemini direct provider.

    Uses Gemini's REST API. We collapse the multi-turn 'contents' shape onto
    the same {role, content} interface the rest of the SDK uses. Roles
    "assistant" → "model" (Gemini's wire format).
    """

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

    def _build_body(
        self, *, system: str, messages: list[dict[str, Any]], max_tokens: int
    ) -> dict[str, Any]:
        contents: list[dict[str, Any]] = []
        for m in messages:
            role = m["role"]
            wire_role = "model" if role == "assistant" else "user"
            contents.append(
                {"role": wire_role, "parts": [{"text": m["content"]}]}
            )
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        body = self._build_body(system=system, messages=messages, max_tokens=max_tokens)
        path = f"/models/{self.model}:generateContent"
        params = {"key": self._api_key}
        last_error: Exception | None = None
        with httpx.Client(
            base_url=GEMINI_BASE_URL,
            timeout=httpx.Timeout(120.0),
            headers={"Content-Type": "application/json"},
        ) as client:
            for attempt in range(_MAX_HTTP_ATTEMPTS):
                try:
                    response = client.post(path, json=body, params=params)
                except httpx.HTTPError as e:
                    last_error = e
                    if attempt + 1 < _MAX_HTTP_ATTEMPTS:
                        _sleep_backoff(attempt)
                        continue
                    raise ProviderHTTPError(
                        f"Gemini network error for model {self.model!r}: {e}"
                    ) from e

                if response.status_code in _RETRYABLE_STATUSES and attempt + 1 < _MAX_HTTP_ATTEMPTS:
                    _sleep_backoff(attempt)
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


def _parse_gemini_response(data: dict[str, Any], *, model: str) -> ProviderResponse:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderResponseError(
            f"Gemini returned an unexpected response shape for model {model!r}: {data!r}"
        ) from e

    usage_meta = data.get("usageMetadata") or {}
    prompt = int(usage_meta.get("promptTokenCount", 0) or 0)
    completion = int(usage_meta.get("candidatesTokenCount", 0) or 0)
    total = int(usage_meta.get("totalTokenCount", prompt + completion) or 0)
    cached = int(usage_meta.get("cachedContentTokenCount", 0) or 0)
    return ProviderResponse(
        text=text,
        usage=Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cached_tokens=cached,
        ),
    )


class _OllamaProvider:
    """Local Ollama provider for OSS models (llama, qwen, mistral, …).

    No API key required. Reads OLLAMA_BASE_URL or defaults to
    http://localhost:11434.
    """

    def __init__(self, *, api_key: str | None = None, model: str) -> None:
        # api_key is ignored (Ollama is unauthenticated by default) but kept
        # in the signature for symmetry with build_provider().
        del api_key
        self._base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
        self.model = model

    def complete(
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
        with httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(300.0),  # local OSS models can be slow
        ) as client:
            for attempt in range(_MAX_HTTP_ATTEMPTS):
                try:
                    response = client.post("/api/chat", json=body)
                except httpx.HTTPError as e:
                    last_error = e
                    if attempt + 1 < _MAX_HTTP_ATTEMPTS:
                        _sleep_backoff(attempt)
                        continue
                    raise ProviderHTTPError(
                        f"Ollama network error for model {self.model!r} at "
                        f"{self._base_url}: {e}"
                    ) from e

                if response.status_code in _RETRYABLE_STATUSES and attempt + 1 < _MAX_HTTP_ATTEMPTS:
                    _sleep_backoff(attempt)
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


def _parse_ollama_response(data: dict[str, Any], *, model: str) -> ProviderResponse:
    try:
        text = data["message"]["content"] or ""
    except (KeyError, TypeError) as e:
        raise ProviderResponseError(
            f"Ollama returned an unexpected response shape for model {model!r}: {data!r}"
        ) from e
    prompt = int(data.get("prompt_eval_count", 0) or 0)
    completion = int(data.get("eval_count", 0) or 0)
    return ProviderResponse(
        text=text,
        usage=Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        ),
    )


class StubProvider:
    """In-memory provider with scripted responses. Public — for tests.

    Users wiring `essarion_build` into their own systems can use this to write
    deterministic tests against `reason()` / `generate()` without hitting any
    real provider. Each `complete()` call pops the next scripted response.

    >>> stub = StubProvider(responses=[
    ...     "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>",
    ...     "<verdict>ship</verdict>",
    ... ])
    >>> from essarion_build import reason, Context
    >>> from essarion_build._runtime import LiteRuntime
    >>> r = reason("task", context=Context(), _runtime=LiteRuntime(stub))
    >>> stub.call_count
    2
    """

    def __init__(
        self,
        *,
        responses: list[str | ProviderResponse] | None = None,
        model: str = "stub-model",
    ) -> None:
        self.model = model
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
        """Append a scripted response to the queue."""
        self._responses.append(self._coerce(response))

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        if not self._responses:
            raise ProviderResponseError(
                "StubProvider exhausted: no more scripted responses. "
                f"Already served {self.call_count} call(s)."
            )
        self.calls.append(
            {"system": system, "messages": list(messages), "max_tokens": max_tokens}
        )
        return self._responses.pop(0)


# Registry of provider constructors. Public-facing names → factory(api_key, model).
ProviderFactory = Callable[..., Provider]

_PROVIDER_REGISTRY: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Register a custom provider by name.

    The factory must accept `api_key=None` and `model=...` kwargs and return
    an object that exposes a `model` attribute and a `complete()` method
    matching the `Provider` protocol.

    Calling this with a built-in provider name overrides the built-in.
    """
    _PROVIDER_REGISTRY[name] = factory


def unregister_provider(name: str) -> None:
    """Remove a previously registered custom provider. No-op if unknown."""
    _PROVIDER_REGISTRY.pop(name, None)


def list_providers() -> list[str]:
    """All provider names recognized by build_provider() (built-in + custom)."""
    builtins = ["openrouter", "anthropic", "openai", "gemini", "ollama", "stub"]
    custom = [n for n in _PROVIDER_REGISTRY if n not in builtins]
    return sorted(builtins + custom)


def build_provider(*, name: str, api_key: str | None, model: str) -> Provider:
    """Construct a provider by name.

    v0.3 built-ins: openrouter (default), anthropic, openai, gemini, ollama, stub.
    Custom providers registered via `register_provider()` are honored too.
    """
    if name in _PROVIDER_REGISTRY:
        return _PROVIDER_REGISTRY[name](api_key=api_key, model=model)
    if name == "openrouter":
        return _OpenRouterProvider(api_key=api_key, model=model)
    if name == "anthropic":
        return _AnthropicProvider(api_key=api_key, model=model)
    if name == "openai":
        return _OpenAIProvider(api_key=api_key, model=model)
    if name == "gemini":
        return _GeminiProvider(api_key=api_key, model=model)
    if name == "ollama":
        return _OllamaProvider(api_key=api_key, model=model)
    if name == "stub":
        return StubProvider(model=model)
    raise ProviderNotAvailable(
        f"Provider {name!r} is not available. "
        f"Built-in: {', '.join(list_providers())}. "
        "Register a custom provider with essarion_build.register_provider()."
    )
