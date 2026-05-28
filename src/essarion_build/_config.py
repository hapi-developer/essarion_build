"""Module-level configuration: defaults consumed by reason() and generate().

Defaults are tuned for cheap reasoning amplification: OpenRouter as the
provider, a cheap GPT-class model. The whole point is to make a *cheap*
model reason like a better one — not to be a wrapper for an expensive one.
Users can override either via configure() or per-call kwargs.

Defaults can also be seeded from the environment at import time:

    ESSARION_PROVIDER=anthropic
    ESSARION_MODEL=claude-sonnet-4-6
    ESSARION_MAX_TOKENS=3000
    ESSARION_RUNTIME=lite

Per-call kwargs > configure() > environment > built-in defaults.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_RUNTIME = "lite"
DEFAULT_PROVIDER = "openrouter"
DEFAULT_EFFORT = "standard"


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


class _Config(BaseModel):
    runtime: str = Field(default_factory=lambda: os.environ.get("ESSARION_RUNTIME") or DEFAULT_RUNTIME)
    provider: str = Field(default_factory=lambda: os.environ.get("ESSARION_PROVIDER") or DEFAULT_PROVIDER)
    api_key: str | None = None
    model: str = Field(default_factory=lambda: os.environ.get("ESSARION_MODEL") or DEFAULT_MODEL)
    max_tokens: int = Field(default_factory=lambda: _env_int("ESSARION_MAX_TOKENS", 4096), ge=1)
    effort: str = Field(default_factory=lambda: os.environ.get("ESSARION_EFFORT") or DEFAULT_EFFORT)


_CONFIG = _Config()


def configure(
    *,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    effort: str | None = None,
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
    if effort is not None:
        _CONFIG.effort = effort


def current() -> _Config:
    return _CONFIG
