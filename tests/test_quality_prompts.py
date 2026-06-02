"""The reasoning prompts carry the structural/security lenses and grounding-density
guidance that close the quality gap (shared state & concurrency, trust
boundaries, resource lifecycle; cite file+symbol/line)."""

from __future__ import annotations

from essarion_build import Context
from essarion_build._prompts import current_system, reset_prompts
from essarion_build.agent._agent_exec import _system_prompt


def setup_function() -> None:
    reset_prompts()


def test_system_prompt_has_structural_lenses() -> None:
    s = current_system().lower()
    assert "shared mutable state" in s
    assert "concurrency" in s
    assert "trust boundaries" in s
    assert "resource lifecycle" in s


def test_system_prompt_demands_grounding_with_location() -> None:
    s = current_system().lower()
    assert "symbol or line" in s
    assert "no location is a guess" in s


def test_executor_prompt_drives_unprompted_security_exploration() -> None:
    prompt = _system_prompt(Context()).lower()
    # Analysis tasks must sweep security/concurrency files, not just entrypoints.
    assert "subprocess/shell" in prompt or "subprocess" in prompt
    assert "not just the entrypoints" in prompt
    assert "background" in prompt
    # Grounding density + output discipline.
    assert "symbol or line" in prompt
    assert "don't read the whole repo" in prompt
