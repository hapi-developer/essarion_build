"""Tests for prompt overrides via configure_prompts / reset_prompts."""

from __future__ import annotations

import pytest

from essarion_build import (
    Context,
    LiteRuntime,
    StubProvider,
    configure_prompts,
    reason,
    reset_prompts,
)
from essarion_build._prompts import (
    current_draft,
    current_plan,
    current_selfcheck_generate,
    current_selfcheck_reason,
    current_system,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    """Always start from default prompts; reset after each test."""
    reset_prompts()
    yield
    reset_prompts()


def test_default_prompts() -> None:
    assert "essarion_build" in current_system()
    assert "{task}" in current_plan()
    assert "<code>" in current_draft()


def test_override_system_prompt_lands_in_runtime() -> None:
    configure_prompts(system="YOU ARE TEST PROMPT")
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<verdict>ship</verdict>",
        ]
    )
    rt = LiteRuntime(stub)
    reason("task", context=Context(), _runtime=rt)
    assert "YOU ARE TEST PROMPT" in stub.calls[0]["system"]
    # The original default should NOT appear once overridden.
    assert "essarion_build, a reasoning amplification layer" not in stub.calls[0]["system"]


def test_override_plan_instruction() -> None:
    configure_prompts(plan="MY CUSTOM PLAN PROMPT for {task}")
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<verdict>ship</verdict>",
        ]
    )
    rt = LiteRuntime(stub)
    reason("review jwt", context=Context(), _runtime=rt)
    first_user = stub.calls[0]["messages"][0]
    assert first_user["content"] == "MY CUSTOM PLAN PROMPT for review jwt"


def test_reset_prompts_restores_defaults() -> None:
    configure_prompts(system="OVERRIDE")
    assert current_system() == "OVERRIDE"
    reset_prompts()
    assert "essarion_build" in current_system()


def test_configure_prompts_none_leaves_default() -> None:
    configure_prompts(system=None)
    assert "essarion_build" in current_system()


def test_configure_prompts_empty_string_clears_override() -> None:
    configure_prompts(system="x")
    assert current_system() == "x"
    configure_prompts(system="")
    # empty string falls back to default
    assert "essarion_build" in current_system()
