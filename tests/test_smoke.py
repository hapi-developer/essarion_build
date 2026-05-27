"""Smoke tests: imports clean, Context builds, mocked Runtime produces the right shape.

No network calls anywhere. Live verification against real providers happens
in a separate step where OPENROUTER_API_KEY (or ANTHROPIC_API_KEY) is set.
"""

from __future__ import annotations

import pytest

import essarion_build
from essarion_build import (
    CloudRuntimeNotAvailable,
    Context,
    ContextError,
    Generation,
    ProviderNotAvailable,
    Reasoning,
    configure,
    generate,
    list_reasoned,
    list_skills,
    reason,
    reasoned,
)
from essarion_build._config import DEFAULT_MODEL, DEFAULT_PROVIDER, current
from essarion_build._decorators import _clear_registry_for_tests
from essarion_build._providers import build_provider
from essarion_build._runtime import LiteRuntime, _extract_tag, select_runtime


# -------------------- import / version / defaults --------------------

def test_version() -> None:
    assert essarion_build.__version__ == "0.1.0"


def test_imports_clean() -> None:
    assert callable(reason)
    assert callable(generate)
    assert callable(reasoned)
    assert callable(configure)
    assert callable(list_reasoned)
    assert callable(list_skills)


def test_default_config_is_cheap_byok() -> None:
    """The whole point of v0: cheap model, BYOK via OpenRouter."""
    assert DEFAULT_PROVIDER == "openrouter"
    assert DEFAULT_MODEL == "openai/gpt-4o-mini"


# -------------------- skills (bundled coding practice) --------------------

EXPECTED_SKILLS = {
    "secure_coding",
    "error_handling",
    "testing",
    "code_review",
    "refactoring",
    "performance",
    "api_design",
    "data_modeling",
    "concurrency",
    "dependency_management",
    "git_workflow",
    "documentation",
    "debugging",
    "logging",
    "database_design",
    "cli_design",
    "python_idioms",
    "typescript_idioms",
    "auth_security",
    "observability",
    "scope_discipline",
}


def test_list_skills_contains_expected() -> None:
    names = set(list_skills())
    missing = EXPECTED_SKILLS - names
    assert not missing, f"Missing skills: {missing}"
    # And there are no surprise additions outside the expected set.
    assert names == EXPECTED_SKILLS


def test_with_skill_loads_body() -> None:
    ctx = Context().with_skill("secure_coding")
    assert len(ctx.builtin_skills) == 1
    s = ctx.builtin_skills[0]
    assert s.name == "secure_coding"
    assert "Validate at boundaries" in s.body  # sanity-check the actual content


def test_with_skills_loads_multiple() -> None:
    ctx = Context().with_skills(["testing", "scope_discipline"])
    names = [s.name for s in ctx.builtin_skills]
    assert names == ["testing", "scope_discipline"]


def test_with_all_skills_loads_everything() -> None:
    ctx = Context().with_all_skills()
    names = {s.name for s in ctx.builtin_skills}
    assert names == EXPECTED_SKILLS


def test_with_unknown_skill_raises() -> None:
    with pytest.raises(ContextError) as exc:
        Context().with_skill("not_a_real_skill")
    assert "not_a_real_skill" in str(exc.value)


def test_skills_render_in_prompt_block() -> None:
    block = Context().with_skill("testing").to_prompt_block()
    assert "<skills>" in block
    assert '<skill name="testing">' in block
    assert "Test behavior, not implementation" in block


# -------------------- Context (repo / docs / stubs) --------------------

def test_context_builds_empty() -> None:
    ctx = Context()
    block = ctx.to_prompt_block()
    assert block == "<context>\n</context>"


def test_context_add_repo(tmp_path) -> None:
    (tmp_path / "a.py").write_text("print('hello')\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("x = 1\n")
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    (tmp_path / "ignored.txt").write_text("you should not see me")

    ctx = Context().add_repo(tmp_path)
    paths = {f.path for f in ctx.repo_files}
    assert "a.py" in paths
    assert "sub/b.py" in paths
    assert "ignored.txt" not in paths

    block = ctx.to_prompt_block()
    assert "<repo>" in block
    assert '<file path="a.py">' in block
    assert "print('hello')" in block


def test_context_add_repo_missing_path(tmp_path) -> None:
    with pytest.raises(ContextError):
        Context().add_repo(tmp_path / "does-not-exist")


def test_context_interop_stubs() -> None:
    ctx = Context().add_sourcipedia_topic("jwt").add_agent_skill("auth_review")
    assert ctx.sources[0].topic == "jwt"
    assert ctx.agent_skills[0].name == "auth_review"
    block = ctx.to_prompt_block()
    assert '<source topic="jwt">' in block
    assert '<agent_skill name="auth_review">' in block


# -------------------- Runtime loop (mocked Provider) --------------------

def test_extract_tag() -> None:
    text = "<plan>1. do thing\n2. do other thing</plan><verdict>ship</verdict>"
    assert _extract_tag(text, "plan") == "1. do thing\n2. do other thing"
    assert _extract_tag(text, "verdict") == "ship"
    assert _extract_tag(text, "missing") == ""


class _FakeProvider:
    """Returns scripted responses for the calls in the loop. No network."""

    model = "fake-model"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, *, system: str, messages, max_tokens: int) -> str:
        self.calls.append({"system": system, "messages": messages, "max_tokens": max_tokens})
        return self._responses.pop(0)


def test_lite_reason_shape() -> None:
    fake = _FakeProvider(
        [
            (
                "<plan>1. validate alg header\n2. verify signature</plan>"
                "<tradeoffs>- chosen: strict alg whitelist\n- rejected: trust client</tradeoffs>"
                "<verdict>preliminary: ship pending self-check</verdict>"
            ),
            "<verdict>final: ship</verdict>",
        ]
    )
    rt = LiteRuntime(fake)
    r = reason("harden JWT signature check", context=Context(), _runtime=rt)

    assert isinstance(r, Reasoning)
    assert "validate alg header" in r.plan
    assert "strict alg whitelist" in r.tradeoffs
    assert r.verdict == "final: ship"
    assert len(fake.calls) == 2


def test_lite_generate_shape() -> None:
    fake = _FakeProvider(
        [
            (
                "<plan>1. reject alg=none</plan>"
                "<tradeoffs>- chosen: whitelist\n- rejected: blacklist</tradeoffs>"
                "<verdict>preliminary: ship</verdict>"
            ),
            "<code>def verify(token):\n    assert header.alg in ALLOWED_ALGS</code>",
            "<verdict>final: ship</verdict><defense>The whitelist closes the alg=none family of attacks.</defense>",
        ]
    )
    rt = LiteRuntime(fake)
    g = generate("harden JWT signature check", context=Context(), _runtime=rt)

    assert isinstance(g, Generation)
    assert "reject alg=none" in g.reasoning.plan
    assert "ALLOWED_ALGS" in g.code
    assert "whitelist" in g.defense
    assert len(fake.calls) == 3


def test_skills_are_included_in_system_prompt_when_added() -> None:
    """If the user added skills to Context, they end up in the system prompt
    every call sees."""
    fake = _FakeProvider(
        [
            "<plan>1. do</plan><tradeoffs>- chosen: a</tradeoffs><verdict>ship</verdict>",
            "<verdict>ship</verdict>",
        ]
    )
    rt = LiteRuntime(fake)
    ctx = Context().with_skill("scope_discipline")
    reason("anything", context=ctx, _runtime=rt)

    # The first (and every) call must include the skill body in its system prompt.
    assert "scope_discipline" in fake.calls[0]["system"]
    assert "Solve the stated problem" in fake.calls[0]["system"]


# -------------------- Runtime selection / errors --------------------

def test_cloud_runtime_raises() -> None:
    with pytest.raises(CloudRuntimeNotAvailable) as exc:
        reason("anything", context=Context(), runtime="cloud")
    assert "coming soon" in str(exc.value).lower()

    with pytest.raises(CloudRuntimeNotAvailable):
        generate("anything", context=Context(), runtime="cloud")


def test_provider_not_available() -> None:
    with pytest.raises(ProviderNotAvailable) as exc:
        build_provider(name="gemini", api_key="x", model="x")
    assert "gemini" in str(exc.value)
    assert "openrouter" in str(exc.value)


def test_select_runtime_unknown() -> None:
    with pytest.raises(ValueError):
        select_runtime(runtime="quantum")


def test_openrouter_missing_key(monkeypatch) -> None:
    """OpenRouter provider raises if neither kwarg nor env var has a key."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc:
        build_provider(name="openrouter", api_key=None, model="openai/gpt-4o-mini")
    assert "OPENROUTER_API_KEY" in str(exc.value)


def test_anthropic_missing_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc:
        build_provider(name="anthropic", api_key=None, model="claude-sonnet-4-6")
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_openrouter_construct_with_key(monkeypatch) -> None:
    """Constructing OpenRouterProvider with a key should not network."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    prov = build_provider(name="openrouter", api_key=None, model="openai/gpt-4o-mini")
    assert prov.model == "openai/gpt-4o-mini"


# -------------------- @reasoned registry --------------------

def test_reasoned_registers() -> None:
    _clear_registry_for_tests()

    ctx = Context()

    @reasoned(context=ctx)
    def my_func(x: int) -> int:
        return x + 1

    # Original body still runs — the decorator does not wrap.
    assert my_func(2) == 3

    entries = list_reasoned()
    assert len(entries) == 1
    assert entries[0].fn is my_func
    assert entries[0].context is ctx


# -------------------- auth + configure --------------------

def test_auth_stub() -> None:
    from essarion_build.auth import from_platform_api

    with pytest.raises(NotImplementedError):
        from_platform_api("tok_123")


def test_configure_round_trips() -> None:
    cfg = current()
    original_model = cfg.model
    original_provider = cfg.provider
    try:
        configure(model="some-other-model", provider="anthropic")
        assert cfg.model == "some-other-model"
        assert cfg.provider == "anthropic"
    finally:
        configure(model=original_model, provider=original_provider)
