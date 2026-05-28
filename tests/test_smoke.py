"""Smoke tests: imports clean, Context builds, mocked Runtime produces the right shape.

No network calls anywhere. Live verification against real providers happens
in a separate step where OPENROUTER_API_KEY (or ANTHROPIC_API_KEY) is set.
"""

from __future__ import annotations

import httpx
import pytest

import essarion_build
from essarion_build import (
    CloudRuntimeNotAvailable,
    Context,
    ContextError,
    Generation,
    ProviderAuthError,
    ProviderHTTPError,
    ProviderNotAvailable,
    ProviderRateLimitError,
    ProviderResponseError,
    Reasoning,
    ReasoningFormatError,
    Usage,
    configure,
    generate,
    list_reasoned,
    list_skills,
    reason,
    reasoned,
)
from essarion_build._config import DEFAULT_MODEL, DEFAULT_PROVIDER, current
from essarion_build._decorators import _clear_registry_for_tests
from essarion_build._providers import (
    ProviderResponse,
    _OpenRouterProvider,
    _parse_openrouter_response,
    build_provider,
)
from essarion_build._runtime import LiteRuntime, _extract_tag, select_runtime


# -------------------- import / version / defaults --------------------

def test_version() -> None:
    assert essarion_build.__version__ == "0.4.1"


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
    # v0.2 set
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
    # v0.3 additions
    "rust_idioms",
    "go_idioms",
    "sql_idioms",
    "react_patterns",
    "accessibility",
    "internationalization",
    "caching",
    "microservices",
    "feature_flags",
    "event_driven",
    "state_management",
    "llm_integration",
    "release_engineering",
    "incident_response",
    "dx",
    "migrations",
    "dependency_injection",
    "cloud_infra",
    "kubernetes",
    "code_style",
    "code_smells",
    "code_organization",
    "networking",
    "containers",
    "distributed_systems",
    "ml_engineering",
    "web_security",
    "build_systems",
    "code_search",
    "code_with_llms",
    "observability_practice",
    "code_review_practice",
    "agile_practice",
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
    """Returns scripted ProviderResponse objects for the calls in the loop. No network."""

    model = "fake-model"

    def __init__(self, responses: list[str | ProviderResponse]) -> None:
        normalized: list[ProviderResponse] = []
        for r in responses:
            if isinstance(r, ProviderResponse):
                normalized.append(r)
            else:
                normalized.append(ProviderResponse(text=r, usage=Usage()))
        self._responses = normalized
        self.calls: list[dict] = []

    def complete(self, *, system: str, messages, max_tokens: int) -> ProviderResponse:
        self.calls.append({"system": system, "messages": list(messages), "max_tokens": max_tokens})
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
    assert isinstance(r.usage, Usage)
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


# -------------------- Tag repair (the cheap-model survival kit) --------------------

def test_tag_repair_fills_missing_defense() -> None:
    """When the selfcheck response is missing <defense>, the runtime asks once
    for just that tag and merges it in. This is the difference between
    'works on Sonnet' and 'works on gpt-4o-mini too'."""
    fake = _FakeProvider(
        [
            "<plan>1. do</plan><tradeoffs>- a</tradeoffs><verdict>p</verdict>",
            "<code>x=1</code>",
            "<verdict>final: ship</verdict>",  # ← <defense> missing
            "<defense>It is safe because the input is type-checked.</defense>",  # repair
        ]
    )
    rt = LiteRuntime(fake)
    g = generate("anything", context=Context(), _runtime=rt)

    assert g.defense == "It is safe because the input is type-checked."
    assert len(fake.calls) == 4  # 3 normal + 1 repair


def test_tag_repair_gives_up_after_one_attempt() -> None:
    """Two consecutive failures → ReasoningFormatError, not silently empty."""
    fake = _FakeProvider(
        [
            "<plan>1. do</plan><tradeoffs>- a</tradeoffs><verdict>p</verdict>",
            "<code>x=1</code>",
            "<verdict>final: ship</verdict>",  # ← <defense> missing
            "(still no defense tag here)",  # ← repair also fails
        ]
    )
    rt = LiteRuntime(fake)
    with pytest.raises(ReasoningFormatError) as exc:
        generate("anything", context=Context(), _runtime=rt)
    assert "defense" in str(exc.value)


def test_no_repair_when_response_is_complete() -> None:
    """Happy path: no extra call when the model behaves."""
    fake = _FakeProvider(
        [
            "<plan>1. do</plan><tradeoffs>- a</tradeoffs><verdict>ship</verdict>",
            "<verdict>ship</verdict>",
        ]
    )
    rt = LiteRuntime(fake)
    reason("anything", context=Context(), _runtime=rt)
    assert len(fake.calls) == 2


# -------------------- Usage tracking --------------------

def test_usage_arithmetic() -> None:
    a = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15, cached_tokens=2)
    b = Usage(prompt_tokens=20, completion_tokens=7, total_tokens=27, cached_tokens=3)
    c = a + b
    assert c.prompt_tokens == 30
    assert c.completion_tokens == 12
    assert c.total_tokens == 42
    assert c.cached_tokens == 5


def test_reasoning_usage_aggregates_across_calls() -> None:
    fake = _FakeProvider(
        [
            ProviderResponse(
                text="<plan>1. do</plan><tradeoffs>- a</tradeoffs><verdict>p</verdict>",
                usage=Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
            ),
            ProviderResponse(
                text="<verdict>ship</verdict>",
                usage=Usage(prompt_tokens=120, completion_tokens=8, total_tokens=128),
            ),
        ]
    )
    rt = LiteRuntime(fake)
    r = reason("anything", context=Context(), _runtime=rt)
    assert r.usage.prompt_tokens == 220
    assert r.usage.completion_tokens == 28
    assert r.usage.total_tokens == 248


def test_generation_usage_includes_repair_call() -> None:
    """Token usage from a repair pass is counted toward the total."""
    fake = _FakeProvider(
        [
            ProviderResponse(
                text="<plan>1. do</plan><tradeoffs>- a</tradeoffs><verdict>p</verdict>",
                usage=Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
            ),
            ProviderResponse(
                text="<code>x=1</code>",
                usage=Usage(prompt_tokens=50, completion_tokens=5, total_tokens=55),
            ),
            ProviderResponse(
                text="<verdict>ship</verdict>",  # ← missing defense
                usage=Usage(prompt_tokens=80, completion_tokens=4, total_tokens=84),
            ),
            ProviderResponse(
                text="<defense>safe</defense>",
                usage=Usage(prompt_tokens=90, completion_tokens=3, total_tokens=93),
            ),
        ]
    )
    rt = LiteRuntime(fake)
    g = generate("anything", context=Context(), _runtime=rt)
    assert g.usage.total_tokens == 120 + 55 + 84 + 93
    # The Reasoning view sees the same total.
    assert g.reasoning.usage.total_tokens == g.usage.total_tokens


# -------------------- Per-call max_tokens --------------------

def test_per_call_max_tokens_overrides_config() -> None:
    fake = _FakeProvider(
        [
            "<plan>1. do</plan><tradeoffs>- a</tradeoffs><verdict>ship</verdict>",
            "<verdict>ship</verdict>",
        ]
    )
    rt = LiteRuntime(fake)
    reason("anything", context=Context(), _runtime=rt, max_tokens=123)
    assert fake.calls[0]["max_tokens"] == 123
    assert fake.calls[1]["max_tokens"] == 123


def test_max_tokens_defaults_to_module_config() -> None:
    fake = _FakeProvider(
        [
            "<plan>1. do</plan><tradeoffs>- a</tradeoffs><verdict>ship</verdict>",
            "<verdict>ship</verdict>",
        ]
    )
    rt = LiteRuntime(fake)
    reason("anything", context=Context(), _runtime=rt)
    assert fake.calls[0]["max_tokens"] == current().max_tokens


# -------------------- Runtime selection / errors --------------------

def test_cloud_runtime_raises() -> None:
    with pytest.raises(CloudRuntimeNotAvailable) as exc:
        reason("anything", context=Context(), runtime="cloud")
    assert "coming soon" in str(exc.value).lower()

    with pytest.raises(CloudRuntimeNotAvailable):
        generate("anything", context=Context(), runtime="cloud")


def test_provider_not_available() -> None:
    with pytest.raises(ProviderNotAvailable) as exc:
        build_provider(name="palmyra-mistral-xyz", api_key="x", model="x")
    assert "palmyra-mistral-xyz" in str(exc.value)
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


# -------------------- OpenRouter HTTP error mapping --------------------

class _MockTransport:
    """Minimal httpx transport: returns a scripted response (or raises) per call."""

    def __init__(self, scripted) -> None:
        self._scripted = list(scripted)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _install_openrouter_transport(monkeypatch, scripted) -> _MockTransport:
    """Patch httpx.Client to use a MockTransport for the OpenRouter call."""
    transport = _MockTransport(scripted)
    original_init = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(transport.handle_request)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched_init)
    # Speed up the retry tests.
    monkeypatch.setattr("essarion_build._providers._sleep_backoff", lambda attempt: None)
    return transport


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "<plan>1</plan>"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        },
    )


def test_openrouter_maps_401_to_auth_error(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    _install_openrouter_transport(
        monkeypatch, [httpx.Response(401, text="invalid key")]
    )
    prov = build_provider(name="openrouter", api_key=None, model="openai/gpt-4o-mini")
    with pytest.raises(ProviderAuthError) as exc:
        prov.complete(system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)
    assert "openai/gpt-4o-mini" in str(exc.value)


def test_openrouter_retries_on_429_then_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    transport = _install_openrouter_transport(
        monkeypatch,
        [httpx.Response(429, text="slow down"), _ok_response()],
    )
    prov = build_provider(name="openrouter", api_key=None, model="openai/gpt-4o-mini")
    result = prov.complete(
        system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10
    )
    assert result.text == "<plan>1</plan>"
    assert result.usage.prompt_tokens == 5
    assert len(transport.requests) == 2


def test_openrouter_429_eventually_raises_after_retries(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    _install_openrouter_transport(
        monkeypatch,
        [httpx.Response(429, text=str(i)) for i in range(3)],
    )
    prov = build_provider(name="openrouter", api_key=None, model="openai/gpt-4o-mini")
    with pytest.raises(ProviderRateLimitError):
        prov.complete(system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)


def test_openrouter_500_retries_then_raises_http_error(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    _install_openrouter_transport(
        monkeypatch,
        [httpx.Response(500, text="oops") for _ in range(3)],
    )
    prov = build_provider(name="openrouter", api_key=None, model="openai/gpt-4o-mini")
    with pytest.raises(ProviderHTTPError):
        prov.complete(system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)


def test_openrouter_unknown_400_raises_http_error(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    _install_openrouter_transport(monkeypatch, [httpx.Response(400, text="bad")])
    prov = build_provider(name="openrouter", api_key=None, model="openai/gpt-4o-mini")
    with pytest.raises(ProviderHTTPError) as exc:
        prov.complete(system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)
    assert "400" in str(exc.value)


def test_openrouter_response_parse_error(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    _install_openrouter_transport(
        monkeypatch, [httpx.Response(200, json={"unexpected": "shape"})]
    )
    prov = build_provider(name="openrouter", api_key=None, model="openai/gpt-4o-mini")
    with pytest.raises(ProviderResponseError):
        prov.complete(system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)


def test_openrouter_network_error_retries(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    transport = _install_openrouter_transport(
        monkeypatch,
        [httpx.ConnectError("no route"), _ok_response()],
    )
    prov = build_provider(name="openrouter", api_key=None, model="openai/gpt-4o-mini")
    result = prov.complete(
        system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10
    )
    assert result.text == "<plan>1</plan>"
    assert len(transport.requests) == 2


def test_parse_openrouter_response_extracts_cached_tokens() -> None:
    response = _parse_openrouter_response(
        {
            "choices": [{"message": {"content": "hi"}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "total_tokens": 110,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
        },
        model="m",
    )
    assert response.usage.cached_tokens == 40


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
