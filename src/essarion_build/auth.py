"""Platform API auth helpers.

The full Platform API (essarion-cloud-issued credentials with org/project
scoping, expiry, rotation) lands when the Cloud backend is publicly
exposed. Until then this module provides two practical surfaces:

1. `from_env(*providers)` — read whichever provider key is set, return a
   `Credential` you can pass to `configure()`. Useful for shell scripts
   and CI that source `.env` files.
2. `from_platform_api(token)` — stub for the future Cloud-issued token
   exchange. Currently raises `NotImplementedError`.
"""

from __future__ import annotations

import os
from typing import Iterable

from pydantic import BaseModel


_PROVIDER_ENV: dict[str, tuple[str, ...]] = {
    "openrouter": ("OPENROUTER_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "ollama": (),  # no key needed
}


class Credential(BaseModel):
    """A resolved provider credential."""

    provider: str
    api_key: str | None


def from_env(*providers: str) -> Credential:
    """Return the first credential found in the environment.

    If `providers` is empty, the search order is the SDK's default:
    openrouter, anthropic, openai, gemini. (Ollama is skipped because it
    needs no key — call `Credential(provider="ollama", api_key=None)`
    directly if you want to opt in to local OSS.)

    Raises `RuntimeError` if none of the requested providers have a key.
    """
    candidates: Iterable[str] = providers or (
        "openrouter",
        "anthropic",
        "openai",
        "gemini",
    )
    tried: list[str] = []
    for provider in candidates:
        envs = _PROVIDER_ENV.get(provider)
        if envs is None:
            raise ValueError(f"unknown provider {provider!r}")
        if not envs:
            return Credential(provider=provider, api_key=None)
        for env in envs:
            tried.append(env)
            value = os.environ.get(env)
            if value:
                return Credential(provider=provider, api_key=value)
    raise RuntimeError(
        f"No provider credential found. Tried env vars: {', '.join(tried)}. "
        "Set one of them, or pass `api_key=` directly to configure()."
    )


def from_platform_api(token: str) -> Credential:
    """Exchange an Essarion Platform API token for runtime credentials.

    Stub in v0.3; lands when the Platform API is publicly exposed. The
    token's value is checked for non-emptiness so the stub error path is
    distinguishable from a typo, but otherwise the call always raises.
    """
    if not isinstance(token, str) or not token.strip():
        raise ValueError("from_platform_api: token must be a non-empty string")
    raise NotImplementedError(
        "Platform API auth is coming soon. "
        "For now, pass api_key=... directly to configure() or use from_env()."
    )


__all__ = ["Credential", "from_env", "from_platform_api"]
