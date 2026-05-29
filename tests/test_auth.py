"""Tests for auth helpers (from_env, from_platform_api)."""

from __future__ import annotations

import pytest

from essarion_build.auth import Credential, from_env, from_platform_api


def test_from_env_prefers_openrouter(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-y")
    c = from_env()
    assert c.provider == "openrouter"
    assert c.api_key == "or-x"


def test_from_env_falls_through_to_anthropic(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-y")
    c = from_env()
    assert c.provider == "anthropic"
    assert c.api_key == "ant-y"


def test_from_env_explicit_provider_order(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "oa-z")
    c = from_env("openai", "anthropic")
    assert c.provider == "openai"


def test_from_env_gemini_accepts_google_api_key(monkeypatch) -> None:
    for var in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "g-key")
    c = from_env("gemini")
    assert c.provider == "gemini"
    assert c.api_key == "g-key"


def test_from_env_ollama_is_keyless(monkeypatch) -> None:
    c = from_env("ollama")
    assert c.provider == "ollama"
    assert c.api_key is None


def test_from_env_none_set_raises(monkeypatch) -> None:
    for var in (
        "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError) as exc:
        from_env()
    assert "OPENROUTER_API_KEY" in str(exc.value)


def test_from_env_unknown_provider_raises_value_error() -> None:
    with pytest.raises(ValueError):
        from_env("not-a-real-provider")


def test_from_platform_api_still_stub() -> None:
    with pytest.raises(NotImplementedError):
        from_platform_api("tok-xyz")


def test_from_platform_api_rejects_empty_token() -> None:
    with pytest.raises(ValueError):
        from_platform_api("")
    with pytest.raises(ValueError):
        from_platform_api("   ")
