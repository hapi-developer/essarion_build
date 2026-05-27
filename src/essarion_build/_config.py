"""Module-level configuration: defaults consumed by reason() and generate().

Defaults are tuned for cheap reasoning amplification: OpenRouter as the
provider, a cheap GPT-class model. The whole point is to make a *cheap*
model reason like a better one — not to be a wrapper for an expensive one.
Users can override either via configure() or per-call kwargs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_RUNTIME = "lite"
DEFAULT_PROVIDER = "openrouter"


class _Config(BaseModel):
    runtime: str = DEFAULT_RUNTIME
    provider: str = DEFAULT_PROVIDER
    api_key: str | None = None
    model: str = DEFAULT_MODEL
    max_tokens: int = Field(default=4096, ge=1)


_CONFIG = _Config()


def configure(
    *,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> None:
    """Set module-level defaults for reason() and generate().

    Per-call kwargs always win over these defaults.
    """
    if runtime is not None:
        _CONFIG.runtime = runtime
    if provider is not None:
        _CONFIG.provider = provider
    if api_key is not None:
        _CONFIG.api_key = api_key
    if model is not None:
        _CONFIG.model = model
    if max_tokens is not None:
        _CONFIG.max_tokens = max_tokens


def current() -> _Config:
    return _CONFIG
