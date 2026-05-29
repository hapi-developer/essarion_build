"""Tests for environment-variable seeding of config defaults."""

from __future__ import annotations

import importlib

from essarion_build._config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_RUNTIME,
)


def _reload_config(monkeypatch=None):
    """Reload the _config module so env-var defaults are re-read."""
    from essarion_build import _config

    return importlib.reload(_config)


def test_env_seeds_provider(monkeypatch) -> None:
    monkeypatch.setenv("ESSARION_PROVIDER", "anthropic")
    cfg = _reload_config()
    assert cfg.current().provider == "anthropic"


def test_env_seeds_model(monkeypatch) -> None:
    monkeypatch.setenv("ESSARION_MODEL", "openai/gpt-4o")
    cfg = _reload_config()
    assert cfg.current().model == "openai/gpt-4o"


def test_env_seeds_max_tokens(monkeypatch) -> None:
    monkeypatch.setenv("ESSARION_MAX_TOKENS", "1234")
    cfg = _reload_config()
    assert cfg.current().max_tokens == 1234


def test_env_invalid_max_tokens_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("ESSARION_MAX_TOKENS", "not-a-number")
    cfg = _reload_config()
    assert cfg.current().max_tokens == 4096


def test_env_seeds_runtime(monkeypatch) -> None:
    monkeypatch.setenv("ESSARION_RUNTIME", "lite")
    cfg = _reload_config()
    assert cfg.current().runtime == "lite"


def test_env_unset_uses_built_in_defaults(monkeypatch) -> None:
    for var in ("ESSARION_PROVIDER", "ESSARION_MODEL", "ESSARION_MAX_TOKENS", "ESSARION_RUNTIME"):
        monkeypatch.delenv(var, raising=False)
    cfg = _reload_config()
    assert cfg.current().provider == DEFAULT_PROVIDER
    assert cfg.current().model == DEFAULT_MODEL
    assert cfg.current().runtime == DEFAULT_RUNTIME
    assert cfg.current().max_tokens == 4096


def test_configure_still_wins_over_env(monkeypatch) -> None:
    """configure() takes precedence over env at runtime."""
    monkeypatch.setenv("ESSARION_PROVIDER", "anthropic")
    cfg = _reload_config()
    cfg.configure(provider="openai")
    assert cfg.current().provider == "openai"
